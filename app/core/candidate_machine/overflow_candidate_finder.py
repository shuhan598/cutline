# 溢满切走候选池：在产工序i、生产预警型号X、存在同尺寸同形状且有缺口的目标型号Y

from math import isfinite

from app.core.candidate_machine.candidate_context import CandidateContext
from app.core.candidate_machine.errors import CandidateMachineCalculationError
from app.core.candidate_machine.machine_load import (
    calculate_hourly_output,
    calculate_runtime_load,
)
from app.core.candidate_machine.product_compatibility import (
    is_source_grade_compatible,
    is_wafer_spec_compatible,
)
from app.core.buffer_aggregation.models import MainBufferGroup
from app.schemas.request_schema import AlgorithmSnapshot
from app.schemas.result_schema import (
    AlgorithmIntervalNetRateResult,
    AlgorithmOrderGrowthDetail,
    AlgorithmOverflowCandidateMachine,
    AlgorithmOverflowCandidateResult,
    AlgorithmOverflowTargetOption,
    AlgorithmOverflowWarningResult,
)


class OverflowCandidateFinder:
    """为触发的溢满预警查找可切走的在产机台及其目标型号Y。"""

    def find_algorithm(
        self,
        snapshot: AlgorithmSnapshot,
        warnings: list[AlgorithmOverflowWarningResult],
        interval_results: list[AlgorithmIntervalNetRateResult] | None = None,
    ) -> list[AlgorithmOverflowCandidateResult]:
        context = CandidateContext(snapshot)
        return [
            self._for_algorithm_warning(
                warning,
                context,
                interval_results or [],
            )
            for warning in warnings
        ]

    def _for_algorithm_warning(
        self,
        warning: AlgorithmOverflowWarningResult,
        context: CandidateContext,
        interval_results: list[AlgorithmIntervalNetRateResult],
    ) -> AlgorithmOverflowCandidateResult:
        if context.main_buffer_batch.groups_by_group_key:
            return self._for_batch_warning(
                warning=warning,
                context=context,
                interval_results=interval_results,
            )
        context.validate_warning_relation(warning)
        source_detail = self._select_source_detail(warning)
        source_order, source_product = context.order_product(
            source_detail.order_code
        )
        if source_product.wafer_size != source_detail.wafer_size:
            raise CandidateMachineCalculationError(
                f"{source_order.order_code} source detail wafer_size "
                f"{source_detail.wafer_size} does not match source product "
                f"wafer_size {source_product.wafer_size}"
            )

        candidates: list[AlgorithmOverflowCandidateMachine] = []
        for runtime in context.runtime_by_machine_code.values():
            if runtime.status != "running":
                continue
            candidate_agv = context.candidate_agv(runtime.machine_code)
            if candidate_agv.order_code != source_detail.order_code:
                continue

            _, machine = context.machine_context(runtime.machine_code)
            machine_workshop_code = context.machine_workshop_code(
                runtime.machine_code
            )
            if machine_workshop_code != warning.workshop_code:
                continue
            if machine.process_code != warning.upstream_process_code:
                continue
            if not is_wafer_spec_compatible(
                current_wafer_spec=candidate_agv.wafer_spec,
                target_wafer_spec=source_detail.wafer_spec,
                workshop_code=machine_workshop_code,
                process_name=machine.process_name,
            ):
                continue

            _, current_product = context.order_product(
                candidate_agv.order_code
            )
            hourly_output = calculate_hourly_output(
                runtime.output_quantity_30m
            )
            target_options = self._algorithm_target_options(
                warning=warning,
                source_detail=source_detail,
                source_product=source_product,
                machine=machine,
                machine_workshop_code=machine_workshop_code,
                candidate_agv=candidate_agv,
                hourly_output=hourly_output,
                context=context,
                interval_results=interval_results,
            )
            if not target_options:
                continue

            utilization_rate, idle_rate = calculate_runtime_load(
                input_quantity_30m=runtime.input_quantity_30m,
                output_quantity_30m=runtime.output_quantity_30m,
            )
            candidates.append(
                AlgorithmOverflowCandidateMachine(
                    machine_code=runtime.machine_code,
                    machine_name=machine.machine_name,
                    status=runtime.status,
                    workshop_code=machine_workshop_code,
                    process_code=machine.process_code,
                    process_name=machine.process_name,
                    current_order_code=candidate_agv.order_code,
                    current_order_name=candidate_agv.product_name,
                    current_product_code=current_product.product_code,
                    current_wafer_size=current_product.wafer_size,
                    current_wafer_spec=candidate_agv.wafer_spec,
                    current_source_grade=current_product.source_grade,
                    input_quantity_30m=runtime.input_quantity_30m,
                    output_quantity_30m=runtime.output_quantity_30m,
                    current_output_rate_per_hour=hourly_output,
                    reduced_capacity=hourly_output,
                    utilization_rate=utilization_rate,
                    idle_rate=idle_rate,
                    target_options=target_options,
                )
            )

        candidates.sort(
            key=lambda candidate: (
                -candidate.utilization_rate,
                candidate.machine_code,
            )
        )
        return AlgorithmOverflowCandidateResult(
            warning_type="overflow",
            workshop_code=warning.workshop_code,
            buffer_code=warning.buffer_code,
            upstream_process_code=warning.upstream_process_code,
            downstream_process_code=warning.downstream_process_code,
            source_order_code=source_order.order_code,
            source_product_code=source_product.product_code,
            source_wafer_size=source_product.wafer_size,
            source_wafer_spec=source_detail.wafer_spec,
            source_source_grade=source_product.source_grade,
            source_growth_rate=source_detail.growth_rate,
            source_net_consumption_rate=(
                source_detail.net_consumption_rate
            ),
            candidates=candidates,
        )

    def _for_batch_warning(
        self,
        *,
        warning: AlgorithmOverflowWarningResult,
        context: CandidateContext,
        interval_results: list[AlgorithmIntervalNetRateResult],
    ) -> AlgorithmOverflowCandidateResult:
        context.validate_warning_relation(warning)
        source_group = context.warning_group(warning)
        if source_group is None:
            raise CandidateMachineCalculationError(
                "overflow source group cannot be located"
            )
        intervals_by_group = {
            result.group_key: result
            for result in interval_results
            if result.group_key is not None
        }
        source_interval = intervals_by_group.get(source_group.group_key)
        if source_interval is None:
            raise CandidateMachineCalculationError(
                "overflow source group rate cannot be located"
            )
        source_rate = self._inventory_change_rate(source_interval)
        if not isfinite(source_rate):
            raise CandidateMachineCalculationError(
                "overflow source group rate must be finite"
            )
        source_order, source_product = context.order_product(
            source_group.order_code
        )
        if source_product.wafer_size != source_interval.wafer_size:
            raise CandidateMachineCalculationError(
                f"{source_order.order_code} source interval wafer_size "
                f"{source_interval.wafer_size} does not match source product "
                f"wafer_size {source_product.wafer_size}"
            )

        target_groups = self._batch_target_groups(
            source_group=source_group,
            context=context,
            intervals_by_group=intervals_by_group,
        )
        candidates: list[AlgorithmOverflowCandidateMachine] = []
        if source_group.auto_donate_eligible:
            for runtime in context.runtime_by_machine_code.values():
                if runtime.status != "running":
                    continue
                candidate_agv = context.candidate_agv(runtime.machine_code)
                if candidate_agv.order_code != source_group.order_code:
                    continue

                _, machine = context.machine_context(runtime.machine_code)
                machine_workshop_code = context.machine_workshop_code(
                    runtime.machine_code
                )
                if machine_workshop_code != source_group.workshop_code:
                    continue
                if machine.process_code != warning.upstream_process_code:
                    continue
                if not is_wafer_spec_compatible(
                    current_wafer_spec=candidate_agv.wafer_spec,
                    target_wafer_spec=source_interval.wafer_spec,
                    workshop_code=machine_workshop_code,
                    process_name=machine.process_name,
                ):
                    continue

                _, current_product = context.order_product(
                    candidate_agv.order_code
                )
                hourly_output = calculate_hourly_output(
                    runtime.output_quantity_30m
                )
                options = self._batch_target_options(
                    source_product=source_product,
                    machine=machine,
                    machine_workshop_code=machine_workshop_code,
                    candidate_agv=candidate_agv,
                    hourly_output=hourly_output,
                    context=context,
                    target_groups=target_groups,
                )
                if not options:
                    continue
                utilization_rate, idle_rate = calculate_runtime_load(
                    input_quantity_30m=runtime.input_quantity_30m,
                    output_quantity_30m=runtime.output_quantity_30m,
                )
                candidates.append(
                    AlgorithmOverflowCandidateMachine(
                        machine_code=runtime.machine_code,
                        machine_name=machine.machine_name,
                        status=runtime.status,
                        workshop_code=machine_workshop_code,
                        process_code=machine.process_code,
                        process_name=machine.process_name,
                        current_order_code=candidate_agv.order_code,
                        current_order_name=candidate_agv.product_name,
                        current_product_code=current_product.product_code,
                        current_wafer_size=current_product.wafer_size,
                        current_wafer_spec=candidate_agv.wafer_spec,
                        current_source_grade=current_product.source_grade,
                        input_quantity_30m=runtime.input_quantity_30m,
                        output_quantity_30m=runtime.output_quantity_30m,
                        current_output_rate_per_hour=hourly_output,
                        reduced_capacity=hourly_output,
                        utilization_rate=utilization_rate,
                        idle_rate=idle_rate,
                        target_options=options,
                        source_group_key=source_group.group_key,
                    )
                )

        candidates.sort(
            key=lambda candidate: (
                -candidate.utilization_rate,
                candidate.machine_code,
            )
        )
        return AlgorithmOverflowCandidateResult(
            warning_type="overflow",
            workshop_code=source_group.workshop_code,
            buffer_code=source_group.representative_buffer_code or "",
            upstream_process_code=warning.upstream_process_code,
            downstream_process_code=warning.downstream_process_code,
            source_order_code=source_order.order_code,
            source_product_code=source_product.product_code,
            source_wafer_size=source_product.wafer_size,
            source_wafer_spec=source_interval.wafer_spec,
            source_source_grade=source_product.source_grade,
            source_growth_rate=source_rate,
            source_net_consumption_rate=-source_rate,
            candidates=candidates,
            source_group_key=source_group.group_key,
        )

    def _batch_target_groups(
        self,
        *,
        source_group: MainBufferGroup,
        context: CandidateContext,
        intervals_by_group,
    ) -> list[tuple[MainBufferGroup, AlgorithmIntervalNetRateResult, float]]:
        result = []
        batch = context.main_buffer_batch
        for target_key in batch.group_keys_by_physical_buffer_key.get(
            source_group.physical_buffer_key, ()
        ):
            target_group = batch.groups_by_group_key.get(target_key)
            if target_group is None:
                continue
            if target_group.group_key == source_group.group_key:
                continue
            if target_group.main_id == source_group.main_id:
                continue
            if target_group.order_code == source_group.order_code:
                continue
            if not target_group.auto_receive_eligible:
                continue
            target_interval = intervals_by_group.get(target_group.group_key)
            if target_interval is None:
                continue
            target_rate = self._inventory_change_rate(target_interval)
            if not isfinite(target_rate):
                continue
            capacity_gap = max(
                0.0,
                -target_rate,
            )
            if capacity_gap <= 0:
                continue
            result.append((target_group, target_interval, capacity_gap))
        return result

    def _batch_target_options(
        self,
        *,
        source_product,
        machine,
        machine_workshop_code: str,
        candidate_agv,
        hourly_output: float,
        context: CandidateContext,
        target_groups,
    ) -> list[AlgorithmOverflowTargetOption]:
        options: list[AlgorithmOverflowTargetOption] = []
        for target_group, target_interval, capacity_gap in target_groups:
            target_order, target_product = context.order_product(
                target_group.order_code
            )
            if target_product.wafer_size != target_interval.wafer_size:
                raise CandidateMachineCalculationError(
                    f"{target_order.order_code} target interval wafer_size "
                    f"{target_interval.wafer_size} does not match target "
                    f"product wafer_size {target_product.wafer_size}"
                )
            if target_order.workshop_code != target_group.workshop_code:
                continue
            if target_product.wafer_size != source_product.wafer_size:
                continue
            if not is_wafer_spec_compatible(
                current_wafer_spec=candidate_agv.wafer_spec,
                target_wafer_spec=target_interval.wafer_spec,
                workshop_code=machine_workshop_code,
                process_name=machine.process_name,
            ):
                continue
            if not is_source_grade_compatible(
                current_source_grade=source_product.source_grade,
                target_source_grade=target_product.source_grade,
            ):
                continue
            options.append(
                AlgorithmOverflowTargetOption(
                    target_order_code=target_order.order_code,
                    target_product_code=target_product.product_code,
                    target_wafer_size=target_product.wafer_size,
                    target_wafer_spec=target_interval.wafer_spec,
                    target_source_grade=target_product.source_grade,
                    target_buffer_code=(
                        target_group.representative_buffer_code
                    ),
                    target_workshop_code=target_group.workshop_code,
                    target_upstream_process_code=(
                        target_interval.upstream_process_code
                    ),
                    target_downstream_process_code=(
                        target_interval.downstream_process_code
                    ),
                    capacity_gap=capacity_gap,
                    estimated_contribution_capacity=hourly_output,
                    target_group_key=target_group.group_key,
                )
            )
        options.sort(
            key=lambda option: (
                -option.capacity_gap,
                option.target_order_code,
                option.target_buffer_code or "",
            )
        )
        return options

    @staticmethod
    def _inventory_change_rate(
        result: AlgorithmIntervalNetRateResult,
    ) -> float:
        if result.inventory_change_rate is not None:
            return result.inventory_change_rate
        return -result.net_consumption_rate

    def _select_source_detail(
        self,
        warning: AlgorithmOverflowWarningResult,
    ) -> AlgorithmOrderGrowthDetail:
        positive_details = [
            detail
            for detail in warning.order_growth_details
            if detail.growth_rate > 0
        ]
        if not positive_details:
            raise CandidateMachineCalculationError(
                f"{warning.buffer_code} has no positive growth source order"
            )
        return min(
            positive_details,
            key=lambda detail: (
                -detail.growth_rate,
                detail.order_code,
            ),
        )

    def _algorithm_target_options(
        self,
        *,
        warning: AlgorithmOverflowWarningResult,
        source_detail: AlgorithmOrderGrowthDetail,
        source_product,
        machine,
        machine_workshop_code: str,
        candidate_agv,
        hourly_output: float,
        context: CandidateContext,
        interval_results: list[AlgorithmIntervalNetRateResult],
    ) -> list[AlgorithmOverflowTargetOption]:
        options: list[AlgorithmOverflowTargetOption] = []
        for target_detail in warning.order_growth_details:
            if target_detail.order_code == source_detail.order_code:
                continue
            if target_detail.net_consumption_rate <= 0:
                continue

            target_order, target_product = context.order_product(
                target_detail.order_code
            )
            if target_product.wafer_size != target_detail.wafer_size:
                raise CandidateMachineCalculationError(
                    f"{target_order.order_code} target detail wafer_size "
                    f"{target_detail.wafer_size} does not match target "
                    f"product wafer_size {target_product.wafer_size}"
                )
            if target_order.workshop_code != warning.workshop_code:
                continue
            if target_product.wafer_size != source_product.wafer_size:
                continue
            if not is_wafer_spec_compatible(
                current_wafer_spec=candidate_agv.wafer_spec,
                target_wafer_spec=target_detail.wafer_spec,
                workshop_code=machine_workshop_code,
                process_name=machine.process_name,
            ):
                continue
            if not is_source_grade_compatible(
                current_source_grade=source_product.source_grade,
                target_source_grade=target_product.source_grade,
            ):
                continue

            target_interval = self._unique_target_interval(
                warning=warning,
                target_detail=target_detail,
                interval_results=interval_results,
            )

            options.append(
                AlgorithmOverflowTargetOption(
                    target_order_code=target_order.order_code,
                    target_product_code=target_product.product_code,
                    target_wafer_size=target_product.wafer_size,
                    target_wafer_spec=target_detail.wafer_spec,
                    target_source_grade=target_product.source_grade,
                    target_buffer_code=(
                        target_interval.buffer_code
                        if target_interval is not None
                        else None
                    ),
                    target_workshop_code=(
                        target_interval.workshop_code
                        if target_interval is not None
                        else None
                    ),
                    target_upstream_process_code=(
                        target_interval.upstream_process_code
                        if target_interval is not None
                        else None
                    ),
                    target_downstream_process_code=(
                        target_interval.downstream_process_code
                        if target_interval is not None
                        else None
                    ),
                    capacity_gap=target_detail.net_consumption_rate,
                    estimated_contribution_capacity=hourly_output,
                )
            )

        options.sort(
            key=lambda option: (
                -option.capacity_gap,
                option.target_order_code,
            )
        )
        return options

    def _unique_target_interval(
        self,
        *,
        warning: AlgorithmOverflowWarningResult,
        target_detail: AlgorithmOrderGrowthDetail,
        interval_results: list[AlgorithmIntervalNetRateResult],
    ) -> AlgorithmIntervalNetRateResult | None:
        matches = [
            interval
            for interval in interval_results
            if interval.order_code == target_detail.order_code
            and interval.wafer_size == target_detail.wafer_size
            and interval.wafer_spec == target_detail.wafer_spec
            and interval.workshop_code == warning.workshop_code
            and interval.upstream_process_code
            == warning.upstream_process_code
            and interval.net_consumption_rate
            == target_detail.net_consumption_rate
        ]
        if len(matches) != 1:
            return None
        return matches[0]
