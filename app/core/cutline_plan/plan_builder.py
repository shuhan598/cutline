"""把机台选择结果构建为自动计划或人工干预决策。"""

from app.schemas.request_schema import AlgorithmSnapshot
from app.schemas.result_schema import (
    AlgorithmCutlineDecisionResult,
    AlgorithmManualInterventionResult,
    AlgorithmOverflowCutlinePlan,
    AlgorithmOverflowSelectionResult,
    AlgorithmOverflowWarningResult,
    AlgorithmStockoutCutlinePlan,
    AlgorithmStockoutSelectionResult,
    AlgorithmStockoutWarningResult,
)


class CutlinePlanBuilder:
    """根据风险是否完全解除构建自动计划或人工干预结果。"""

    def build_stockout_decision(
        self,
        snapshot: AlgorithmSnapshot,
        warning: AlgorithmStockoutWarningResult,
        selection_result: AlgorithmStockoutSelectionResult,
    ) -> AlgorithmCutlineDecisionResult:
        if selection_result.risk_resolved:
            return AlgorithmCutlineDecisionResult(
                plan=AlgorithmStockoutCutlinePlan(
                    plan_id=self._algorithm_plan_id(
                        "stockout",
                        snapshot,
                        warning.buffer_code,
                        warning.order_code,
                    ),
                    calculation_time=snapshot.current_time,
                    workshop_code=warning.workshop_code,
                    buffer_code=warning.buffer_code,
                    order_code=warning.order_code,
                    wafer_size=warning.wafer_size,
                    wafer_spec=warning.wafer_spec,
                    upstream_process_code=warning.upstream_process_code,
                    downstream_process_code=warning.downstream_process_code,
                    initial_capacity_gap=(
                        selection_result.initial_capacity_gap
                    ),
                    total_contribution_capacity=(
                        selection_result.total_contribution_capacity
                    ),
                    remaining_capacity_gap=(
                        selection_result.remaining_capacity_gap
                    ),
                    selected_machines=[
                        item.model_copy(deep=True)
                        for item in selection_result.selected_machines
                    ],
                ),
                manual_intervention=None,
            )

        return AlgorithmCutlineDecisionResult(
            plan=None,
            manual_intervention=self._algorithm_manual_intervention(
                warning_type="stockout",
                warning_time=warning.warning_time,
                workshop_code=warning.workshop_code,
                buffer_code=warning.buffer_code,
                order_code=warning.order_code,
                source_order_code=None,
                wafer_size=warning.wafer_size,
                wafer_spec=warning.wafer_spec,
                upstream_process_code=warning.upstream_process_code,
                downstream_process_code=warning.downstream_process_code,
                reason=(
                    selection_result.failure_reason
                    or "stockout_risk_not_resolved"
                ),
                initial_risk_value=selection_result.initial_capacity_gap,
                remaining_risk_value=(
                    selection_result.remaining_capacity_gap
                ),
                selection_result=selection_result,
            ),
        )

    def build_overflow_decision(
        self,
        snapshot: AlgorithmSnapshot,
        warning: AlgorithmOverflowWarningResult,
        selection_result: AlgorithmOverflowSelectionResult,
    ) -> AlgorithmCutlineDecisionResult:
        if selection_result.risk_resolved:
            return AlgorithmCutlineDecisionResult(
                plan=AlgorithmOverflowCutlinePlan(
                    plan_id=self._algorithm_plan_id(
                        "overflow",
                        snapshot,
                        warning.buffer_code,
                        selection_result.source_order_code,
                    ),
                    calculation_time=snapshot.current_time,
                    workshop_code=warning.workshop_code,
                    buffer_code=warning.buffer_code,
                    source_order_code=selection_result.source_order_code,
                    source_wafer_size=selection_result.source_wafer_size,
                    source_wafer_spec=selection_result.source_wafer_spec,
                    upstream_process_code=warning.upstream_process_code,
                    downstream_process_code=warning.downstream_process_code,
                    initial_growth_rate=selection_result.initial_growth_rate,
                    total_reduced_capacity=(
                        selection_result.total_reduced_capacity
                    ),
                    remaining_growth_rate=(
                        selection_result.remaining_growth_rate
                    ),
                    updated_overflow_minutes=(
                        selection_result.updated_overflow_minutes
                    ),
                    selected_machines=[
                        item.model_copy(deep=True)
                        for item in selection_result.selected_machines
                    ],
                ),
                manual_intervention=None,
            )

        return AlgorithmCutlineDecisionResult(
            plan=None,
            manual_intervention=self._algorithm_manual_intervention(
                warning_type="overflow",
                warning_time=warning.warning_time,
                workshop_code=warning.workshop_code,
                buffer_code=warning.buffer_code,
                order_code=None,
                source_order_code=selection_result.source_order_code,
                wafer_size=selection_result.source_wafer_size,
                wafer_spec=selection_result.source_wafer_spec,
                upstream_process_code=warning.upstream_process_code,
                downstream_process_code=warning.downstream_process_code,
                reason=(
                    selection_result.failure_reason
                    or "overflow_risk_not_resolved"
                ),
                initial_risk_value=selection_result.initial_growth_rate,
                remaining_risk_value=selection_result.remaining_growth_rate,
                selection_result=selection_result,
            ),
        )

    def _algorithm_manual_intervention(
        self,
        *,
        warning_type: str,
        warning_time,
        workshop_code: str,
        buffer_code: str,
        order_code: str | None,
        source_order_code: str | None,
        wafer_size: str,
        wafer_spec: str,
        upstream_process_code: str,
        downstream_process_code: str,
        reason: str,
        initial_risk_value: float,
        remaining_risk_value: float,
        selection_result,
    ) -> AlgorithmManualInterventionResult:
        passed = [
            item.model_copy(deep=True)
            for item in selection_result.selected_machines
        ]
        rejected = [
            item.model_copy(deep=True)
            for item in selection_result.rejected_machines
        ]
        passed_codes = {item.machine_code for item in passed}
        evaluated_codes = passed_codes | {
            item.machine_code for item in rejected
        }
        rejected_codes = evaluated_codes - passed_codes
        return AlgorithmManualInterventionResult(
            warning_type=warning_type,
            warning_time=warning_time,
            workshop_code=workshop_code,
            buffer_code=buffer_code,
            order_code=order_code,
            source_order_code=source_order_code,
            wafer_size=wafer_size,
            wafer_spec=wafer_spec,
            upstream_process_code=upstream_process_code,
            downstream_process_code=downstream_process_code,
            reason=reason,
            initial_risk_value=initial_risk_value,
            remaining_risk_value=remaining_risk_value,
            evaluated_candidate_count=len(evaluated_codes),
            passed_candidate_count=len(passed_codes),
            rejected_candidate_count=len(rejected_codes),
            passed_machines=passed,
            rejected_machines=rejected,
        )

    def _algorithm_plan_id(
        self,
        warning_type: str,
        snapshot: AlgorithmSnapshot,
        buffer_code: str,
        order_code: str,
    ) -> str:
        return (
            f"{warning_type}:{snapshot.current_time.isoformat()}:"
            f"{buffer_code}:{order_code}"
        )
