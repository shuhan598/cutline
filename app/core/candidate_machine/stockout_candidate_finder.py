# 断料候选机台组件：输入 AlgorithmSnapshot 与 AlgorithmStockoutWarningResult 列表，输出 AlgorithmStockoutCandidateResult 列表

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
    AlgorithmStockoutCandidateMachine,
    AlgorithmStockoutCandidateResult,
    AlgorithmStockoutWarningResult,
)


class StockoutCandidateFinder:
    """为触发的断料预警，按全局耗尽紧迫度顺序查找同工序同尺寸同形状的在产机台。"""

    def find_algorithm(
        self,
        snapshot: AlgorithmSnapshot,
        warnings: list[AlgorithmStockoutWarningResult],
    ) -> list[AlgorithmStockoutCandidateResult]:
        context = CandidateContext(snapshot)
        return [
            self._for_algorithm_warning(warning, context)
            for warning in warnings
        ]

    def _for_algorithm_warning(
        self,
        warning: AlgorithmStockoutWarningResult,
        context: CandidateContext,
    ) -> AlgorithmStockoutCandidateResult:
        context.validate_warning_relation(warning)
        target_order, target_product = context.order_product(
            warning.order_code
        )
        if target_product.wafer_size != warning.wafer_size:
            raise CandidateMachineCalculationError(
                f"{target_order.order_code} warning wafer_size "
                f"{warning.wafer_size} does not match target product "
                f"wafer_size {target_product.wafer_size}"
            )

        candidates: list[AlgorithmStockoutCandidateMachine] = []
        for runtime in context.runtime_by_machine_code.values():
            if runtime.status != "running":
                continue
            candidate_agv = context.candidate_agv(runtime.machine_code)
            if candidate_agv.order_code == warning.order_code:
                continue

            _, machine = context.machine_context(runtime.machine_code)
            machine_workshop_code = context.machine_workshop_code(
                runtime.machine_code
            )
            if machine_workshop_code != warning.workshop_code:
                continue
            if machine.process_code != warning.upstream_process_code:
                continue

            _, current_product = context.order_product(
                candidate_agv.order_code
            )
            if current_product.wafer_size != warning.wafer_size:
                continue
            if not is_wafer_spec_compatible(
                current_wafer_spec=candidate_agv.wafer_spec,
                target_wafer_spec=warning.wafer_spec,
                workshop_code=machine_workshop_code,
                process_name=machine.process_name,
            ):
                continue
            if not is_source_grade_compatible(
                current_source_grade=current_product.source_grade,
                target_source_grade=target_product.source_grade,
            ):
                continue

            utilization_rate, idle_rate = calculate_runtime_load(
                input_quantity_30m=runtime.input_quantity_30m,
                output_quantity_30m=runtime.output_quantity_30m,
            )
            hourly_output = calculate_hourly_output(
                runtime.output_quantity_30m
            )
            candidates.append(
                AlgorithmStockoutCandidateMachine(
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
                    target_order_code=target_order.order_code,
                    target_product_code=target_product.product_code,
                    target_wafer_size=target_product.wafer_size,
                    target_wafer_spec=warning.wafer_spec,
                    target_source_grade=target_product.source_grade,
                    input_quantity_30m=runtime.input_quantity_30m,
                    output_quantity_30m=runtime.output_quantity_30m,
                    current_output_rate_per_hour=hourly_output,
                    contribution_capacity=hourly_output,
                    utilization_rate=utilization_rate,
                    idle_rate=idle_rate,
                )
            )

        candidates.sort(
            key=lambda candidate: (
                -candidate.idle_rate,
                candidate.machine_code,
            )
        )
        return AlgorithmStockoutCandidateResult(
            warning_type="stockout",
            workshop_code=warning.workshop_code,
            buffer_code=warning.buffer_code,
            warning_order_code=warning.order_code,
            target_product_code=target_product.product_code,
            target_wafer_size=target_product.wafer_size,
            target_wafer_spec=warning.wafer_spec,
            target_source_grade=target_product.source_grade,
            upstream_process_code=warning.upstream_process_code,
            downstream_process_code=warning.downstream_process_code,
            capacity_gap=warning.net_consumption_rate,
            candidates=candidates,
        )
