# 溢满切走候选池：在产工序i、生产预警型号X、存在同尺寸同形状且有缺口的目标型号Y

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
            if runtime.current_order_code != source_detail.order_code:
                continue

            _, machine, line = context.machine_context(runtime.machine_code)
            if line.workshop_code != warning.workshop_code:
                continue
            if machine.process_code != warning.upstream_process_code:
                continue
            if line.wafer_spec != source_detail.wafer_spec:
                continue

            hourly_output = calculate_hourly_output(
                runtime.output_quantity_30m
            )
            target_options = self._algorithm_target_options(
                warning=warning,
                source_detail=source_detail,
                source_product=source_product,
                machine=machine,
                line=line,
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
                    workshop_code=line.workshop_code,
                    process_code=machine.process_code,
                    process_name=machine.process_name,
                    current_order_code=source_order.order_code,
                    current_product_code=source_product.product_code,
                    current_wafer_size=source_product.wafer_size,
                    current_wafer_spec=line.wafer_spec,
                    current_source_grade=source_product.source_grade,
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
        line,
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
                current_wafer_spec=line.wafer_spec,
                target_wafer_spec=target_detail.wafer_spec,
                workshop_code=line.workshop_code,
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
