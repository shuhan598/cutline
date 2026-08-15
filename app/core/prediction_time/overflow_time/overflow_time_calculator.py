"""汇总同一 main 的订单库存与速率，预测唯一的物理溢满结果。"""

from collections import defaultdict

from app.core.buffer_aggregation.models import MainBufferGroup
from app.core.prediction_time.errors import PredictionTimeCalculationError
from app.schemas.common_schema import (
    AlgorithmBufferMaster,
    AlgorithmBufferProcessRelation,
)
from app.schemas.request_schema import AlgorithmSnapshot
from app.schemas.result_schema import (
    AlgorithmBufferOverflowTimeResult,
    AlgorithmIntervalNetRateResult,
    AlgorithmOrderGrowthDetail,
)


class OverflowTimeCalculator:
    """溢满时间计算组件"""

    def calculate_algorithm(
        self,
        snapshot: AlgorithmSnapshot,
        net_rate_results: list[AlgorithmIntervalNetRateResult],
    ) -> list[AlgorithmBufferOverflowTimeResult]:
        if snapshot.main_buffer_batch.groups_by_group_key:
            return self._calculate_from_batch(snapshot, net_rate_results)

        buffer_by_code: dict[str, AlgorithmBufferMaster] = {}
        for buffer in snapshot.buffer_masters:
            if buffer.buffer_code in buffer_by_code:
                raise PredictionTimeCalculationError(
                    f"{buffer.buffer_code} duplicate buffer master"
                )
            buffer_by_code[buffer.buffer_code] = buffer

        relation_by_buffer: dict[
            str, AlgorithmBufferProcessRelation
        ] = {}
        for relation in snapshot.buffer_process_relations:
            if relation.buffer_code in relation_by_buffer:
                raise PredictionTimeCalculationError(
                    f"{relation.buffer_code} duplicate process relation"
                )
            relation_by_buffer[relation.buffer_code] = relation

        # 溢满属于物理 main，订单 rate 在这里汇总为一个物理增长率。
        rates_by_main: dict[
            str, list[AlgorithmIntervalNetRateResult]
        ] = defaultdict(list)
        buffer_codes_by_main: dict[str, set[str]] = defaultdict(set)
        context_by_main: dict[str, AlgorithmBufferProcessRelation] = {}
        main_by_buffer_code: dict[str, str] = {}
        seen_intervals: set[tuple[str, str, str, str, str, str]] = set()
        for net_rate in net_rate_results:
            main_id = net_rate.main_id.strip()
            if not main_id:
                raise PredictionTimeCalculationError(
                    f"{net_rate.buffer_code} main_id cannot be blank"
                )

            buffer_codes = sorted(
                set(net_rate.buffer_codes) | {net_rate.buffer_code}
            )
            for buffer_code in buffer_codes:
                if buffer_code not in buffer_by_code:
                    raise PredictionTimeCalculationError(
                        f"{buffer_code} buffer master does not exist"
                    )
                relation = relation_by_buffer.get(buffer_code)
                if relation is None:
                    raise PredictionTimeCalculationError(
                        f"{buffer_code} process relation does not exist"
                    )

                existing_main_id = main_by_buffer_code.get(buffer_code)
                if existing_main_id is not None and existing_main_id != main_id:
                    raise PredictionTimeCalculationError(
                        f"{buffer_code} belongs to both main_id "
                        f"{existing_main_id} and {main_id}"
                    )
                main_by_buffer_code[buffer_code] = main_id

                existing_context = context_by_main.get(main_id)
                if existing_context is None:
                    context_by_main[main_id] = relation
                elif (
                    existing_context.workshop_code != relation.workshop_code
                    or existing_context.upstream_process_code
                    != relation.upstream_process_code
                    or existing_context.downstream_process_code
                    != relation.downstream_process_code
                ):
                    raise PredictionTimeCalculationError(
                        f"{main_id} buffer {buffer_code} process interval "
                        "does not match other physical buffers"
                    )

            interval_key = (
                main_id,
                net_rate.order_code,
                net_rate.wafer_spec,
                net_rate.workshop_code,
                net_rate.upstream_process_code,
                net_rate.downstream_process_code,
            )
            if interval_key in seen_intervals:
                raise PredictionTimeCalculationError(
                    f"{net_rate.buffer_code} {net_rate.order_code} "
                    "duplicate interval net rate"
                )
            seen_intervals.add(interval_key)
            rates_by_main[main_id].append(net_rate)
            buffer_codes_by_main[main_id].update(buffer_codes)

        return [
            self._calculate_algorithm_buffer(
                main_id,
                sorted(buffer_codes_by_main[main_id]),
                buffer_by_code,
                context_by_main[main_id],
                rates_by_main[main_id],
            )
            for main_id in sorted(rates_by_main)
        ]

    def _calculate_from_batch(
        self,
        snapshot: AlgorithmSnapshot,
        net_rate_results: list[AlgorithmIntervalNetRateResult],
    ) -> list[AlgorithmBufferOverflowTimeResult]:
        rates_by_key = {}
        for rate in net_rate_results:
            if rate.group_key is None:
                continue
            if rate.group_key in rates_by_key:
                raise PredictionTimeCalculationError(
                    f"{rate.group_key} duplicate interval net rate"
                )
            rates_by_key[rate.group_key] = rate

        results: list[AlgorithmBufferOverflowTimeResult] = []
        batch = snapshot.main_buffer_batch
        physical_by_main = dict(batch.physical_main_buffers_by_main_id)
        if not physical_by_main:
            # 兼容仍由调用方手工构造内部聚合批次的场景。
            for main_id, groups in batch.groups_by_main_id.items():
                if not groups:
                    continue
                first = groups[0]
                from app.core.buffer_aggregation.models import PhysicalMainBufferState

                physical_by_main[main_id] = PhysicalMainBufferState(
                    main_id=main_id,
                    workshop_code=first.workshop_code,
                    ordered_service_process_codes=first.ordered_service_process_codes,
                    physical_buffer_key=first.physical_buffer_key,
                    buffer_codes=tuple(sorted({code for group in groups for code in group.buffer_codes})),
                    total_inventory=sum(group.total_inventory for group in groups),
                    total_capacity=first.total_capacity,
                    remaining_capacity=(first.total_capacity - sum(group.total_inventory for group in groups) if first.total_capacity is not None else None),
                    representative_buffer_code=first.representative_buffer_code,
                    order_codes=tuple(group.order_code for group in groups if group.order_code),
                    stockout_eligible=first.stockout_eligible,
                    overflow_eligible=first.overflow_eligible,
                    stockout_warning_eligible=first.stockout_warning_eligible,
                    overflow_warning_eligible=first.overflow_warning_eligible,
                    auto_receive_eligible=first.auto_receive_eligible,
                    auto_donate_eligible=first.auto_donate_eligible,
                )
        # 每个 main 最多生成一个物理溢满结果，订单贡献保留在明细中。
        for main_id, physical in sorted(physical_by_main.items()):
            if not physical.overflow_eligible or physical.total_capacity is None:
                continue
            groups = [
                group
                for group in batch.groups_by_main_id.get(main_id, ())
                if group.order_code and group.group_key in rates_by_key
            ]
            if not groups:
                continue
            rates = [rates_by_key[group.group_key] for group in groups]
            results.append(self._calculate_physical_main(physical, groups, rates))
        return results

    def _calculate_physical_main(self, physical, groups, rates):
        details = [
            AlgorithmOrderGrowthDetail(
                order_code=rate.order_code,
                wafer_size=rate.wafer_size,
                wafer_spec=rate.wafer_spec,
                current_quantity=group.total_inventory,
                upstream_output_rate=rate.upstream_output_rate,
                downstream_input_rate=rate.downstream_input_rate,
                net_consumption_rate=rate.net_consumption_rate,
                growth_rate=(
                    rate.inventory_change_rate
                    if rate.inventory_change_rate is not None
                    else -rate.net_consumption_rate
                ),
            )
            for group, rate in zip(groups, rates)
        ]
        growth = sum(detail.growth_rate for detail in details)
        total_capacity = physical.total_capacity
        total_inventory = physical.total_inventory
        remaining = total_capacity - total_inventory
        overflow_minutes = (
            0.0
            if remaining <= 0
            else remaining / growth * 60
            if growth > 0
            else None
        )
        source = max(
            (rate for rate in rates if (rate.inventory_change_rate if rate.inventory_change_rate is not None else -rate.net_consumption_rate) > 0),
            key=lambda rate: ((rate.inventory_change_rate if rate.inventory_change_rate is not None else -rate.net_consumption_rate), rate.order_code),
            default=None,
        )
        representative = (
            next((rate.buffer_code for rate in rates if source and rate.order_code == source.order_code), None)
            or physical.representative_buffer_code
            or ""
        )
        return AlgorithmBufferOverflowTimeResult(
            main_id=physical.main_id,
            buffer_code=representative,
            buffer_codes=list(physical.buffer_codes),
            workshop_code=physical.workshop_code,
            upstream_process_code=physical.ordered_service_process_codes[0] if len(physical.ordered_service_process_codes) > 0 else "",
            downstream_process_code=physical.ordered_service_process_codes[1] if len(physical.ordered_service_process_codes) > 1 else "",
            max_capacity=total_capacity,
            total_inventory=total_inventory,
            remaining_capacity=remaining,
            buffer_growth_rate=growth,
            overflow_minutes=overflow_minutes,
            order_growth_details=details,
            group_key=(
                next((rate.group_key for rate in rates if rate.group_key and source and rate.order_code == source.order_code), None)
            ),
        )

    def _calculate_batch_group(
        self,
        group: MainBufferGroup,
        net_rate: AlgorithmIntervalNetRateResult,
    ) -> AlgorithmBufferOverflowTimeResult:
        if group.total_capacity is None:
            raise PredictionTimeCalculationError(
                f"{group.main_id} overflow-eligible group has no capacity"
            )
        representative = group.representative_buffer_code
        if representative is None:
            raise PredictionTimeCalculationError(
                f"{group.main_id} overflow-eligible group has no representative"
            )
        if len(group.ordered_service_process_codes) != 2:
            raise PredictionTimeCalculationError(
                f"{group.main_id} overflow-eligible group has invalid processes"
            )
        inventory_change_rate = (
            net_rate.inventory_change_rate
            if net_rate.inventory_change_rate is not None
            else -net_rate.net_consumption_rate
        )
        remaining_capacity = group.total_capacity - group.total_inventory
        if remaining_capacity <= 0:
            overflow_minutes = 0.0
        elif inventory_change_rate > 0:
            overflow_minutes = remaining_capacity / inventory_change_rate * 60
        else:
            overflow_minutes = None
        upstream_process, downstream_process = (
            group.ordered_service_process_codes
        )
        return AlgorithmBufferOverflowTimeResult(
            main_id=group.main_id,
            buffer_code=representative,
            buffer_codes=list(group.buffer_codes),
            workshop_code=group.workshop_code,
            upstream_process_code=upstream_process,
            downstream_process_code=downstream_process,
            max_capacity=group.total_capacity,
            total_inventory=group.total_inventory,
            remaining_capacity=remaining_capacity,
            buffer_growth_rate=inventory_change_rate,
            overflow_minutes=overflow_minutes,
            order_growth_details=[
                AlgorithmOrderGrowthDetail(
                    order_code=net_rate.order_code,
                    wafer_size=net_rate.wafer_size,
                    wafer_spec=net_rate.wafer_spec,
                    current_quantity=group.total_inventory,
                    upstream_output_rate=net_rate.upstream_output_rate,
                    downstream_input_rate=net_rate.downstream_input_rate,
                    net_consumption_rate=net_rate.net_consumption_rate,
                    growth_rate=inventory_change_rate,
                )
            ],
            group_key=group.group_key,
        )

    def _calculate_algorithm_buffer(
        self,
        main_id: str,
        buffer_codes: list[str],
        buffer_by_code: dict[str, AlgorithmBufferMaster],
        relation: AlgorithmBufferProcessRelation,
        net_rates: list[AlgorithmIntervalNetRateResult],
    ) -> AlgorithmBufferOverflowTimeResult:
        order_growth_details = [
            AlgorithmOrderGrowthDetail(
                order_code=net_rate.order_code,
                wafer_size=net_rate.wafer_size,
                wafer_spec=net_rate.wafer_spec,
                current_quantity=net_rate.current_quantity,
                upstream_output_rate=net_rate.upstream_output_rate,
                downstream_input_rate=net_rate.downstream_input_rate,
                net_consumption_rate=net_rate.net_consumption_rate,
                growth_rate=-net_rate.net_consumption_rate,
            )
            for net_rate in net_rates
        ]
        total_inventory = sum(
            detail.current_quantity for detail in order_growth_details
        )
        buffer_growth_rate = sum(
            detail.growth_rate for detail in order_growth_details
        )
        max_capacity = sum(
            buffer_by_code[buffer_code].max_capacity
            for buffer_code in buffer_codes
        )
        remaining_capacity = max_capacity - total_inventory

        if total_inventory >= max_capacity:
            overflow_minutes = 0.0
        elif buffer_growth_rate > 0:
            overflow_minutes = (
                remaining_capacity / buffer_growth_rate * 60
            )
        else:
            overflow_minutes = None

        return AlgorithmBufferOverflowTimeResult(
            main_id=main_id,
            buffer_code=buffer_codes[0],
            buffer_codes=buffer_codes,
            workshop_code=relation.workshop_code,
            upstream_process_code=relation.upstream_process_code,
            downstream_process_code=relation.downstream_process_code,
            max_capacity=max_capacity,
            total_inventory=total_inventory,
            remaining_capacity=remaining_capacity,
            buffer_growth_rate=buffer_growth_rate,
            overflow_minutes=overflow_minutes,
            order_growth_details=order_growth_details,
        )
