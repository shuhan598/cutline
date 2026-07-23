from collections import defaultdict

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
