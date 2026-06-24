# 切线评估门面：调用管道，把内部结果对象映射为对外 CutlineEvaluateResponse

from typing import List, Optional

from app.schemas.common_schema import CutlineEvent
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.response_schema import (
    CutlineEvaluateResponse,
    CutlinePlan,
    ManualIntervention,
    ReturnSuggestion,
    SelectedMachine,
    WarningResult,
)
from app.schemas.result_schema import (
    ManualInterventionResult,
    OverflowWarningResult,
    PlanResult,
    ReturnResult,
    SilkScreenOrderResult,
    StockoutWarningResult,
)
from app.service.cutline_pipeline import CutlinePipeline


class CutlineService:
    """对外统一入口：evaluate(snapshot) -> CutlineEvaluateResponse。"""

    def __init__(self, pipeline: Optional[CutlinePipeline] = None):
        self._pipeline = pipeline or CutlinePipeline()

    def evaluate(self, snapshot: CutlineSnapshot) -> CutlineEvaluateResponse:
        result = self._pipeline.run(snapshot)

        warnings_out: List[WarningResult] = []
        for warning in result.warnings:
            if warning.warning_triggered:
                warnings_out.append(self._stockout_warning(snapshot, warning))
        for overflow in result.overflow_warnings:
            if overflow.warning_triggered:
                warnings_out.append(self._overflow_warning(snapshot, overflow))
        for order in result.silk_orders:
            if order.triggered:
                warnings_out.append(self._silk_warning(order))

        plans_out = [self._plan(snapshot, plan) for plan in result.plans]
        interventions_out = [
            self._intervention(snapshot, item) for item in result.manual_interventions
        ]
        return_out = [
            self._return_suggestion(snapshot, item)
            for item in result.return_results
            if item.triggered
        ]
        tracked_out = [self._tracked_event(snapshot, item) for item in result.return_results]

        return CutlineEvaluateResponse(
            success=True,
            message="",
            warnings=warnings_out,
            plans=plans_out,
            manual_interventions=interventions_out,
            return_suggestions=return_out,
            tracked_events=tracked_out,
        )

    def _stockout_warning(self, snapshot, warning: StockoutWarningResult) -> WarningResult:
        return WarningResult(
            warning_time=snapshot.current_time,
            warning_type=warning.warning_type,
            buffer_code=warning.buffer_code,
            cycle_code=warning.cycle_code,
            cycle_name=warning.cycle_name,
            workshop_code=warning.workshop_code,
            workshop_name=warning.workshop_name,
            upstream_process_code=warning.process_from,
            downstream_process_code=warning.process_to,
            product_code=warning.product_code,
            inventory_quantity=warning.inventory_quantity,
            net_rate=warning.net_rate_per_hour,
            prediction_minutes=warning.depletion_minutes,
            cutline_lead_minutes=warning.cutline_lead_minutes,
        )

    def _overflow_warning(self, snapshot, warning: OverflowWarningResult) -> WarningResult:
        return WarningResult(
            warning_time=snapshot.current_time,
            warning_type=warning.warning_type,
            buffer_code=warning.buffer_code,
            cycle_code=warning.cycle_code,
            cycle_name=warning.cycle_name,
            workshop_code=warning.workshop_code,
            workshop_name=warning.workshop_name,
            upstream_process_code=warning.process_from,
            downstream_process_code=warning.process_to,
            product_code=warning.product_code,
            inventory_quantity=warning.segment_inventory,
            net_rate=warning.net_rate_per_hour,
            prediction_minutes=warning.overflow_minutes,
            cutline_lead_minutes=warning.cutline_lead_minutes,
        )

    def _silk_warning(self, order: SilkScreenOrderResult) -> WarningResult:
        return WarningResult(
            warning_time=order.preparation_time,
            warning_type=order.warning_type,
            buffer_code="",
            upstream_process_code=order.process_code,
            downstream_process_code=order.process_code,
            product_code=order.product_code or "",
            prediction_minutes=None,
            message="silk_screen_clear_preparation",
        )

    def _plan(self, snapshot, plan: PlanResult) -> CutlinePlan:
        warning = WarningResult(
            warning_time=snapshot.current_time,
            warning_type=plan.warning_type,
            buffer_code=plan.buffer_code,
            cycle_code=plan.cycle_code,
            cycle_name=plan.cycle_name,
            workshop_code=plan.workshop_code,
            workshop_name=plan.workshop_name,
            upstream_process_code=plan.process_from,
            downstream_process_code=plan.process_to,
            product_code=plan.product_code,
        )
        return CutlinePlan(
            warning=warning,
            selected_machines=[self._selected(m) for m in plan.selected_machines],
            total_contribution_capacity=plan.total_contribution_capacity,
            remaining_capacity_gap=plan.remaining_capacity_gap,
            requires_silk_screen_clear=plan.requires_silk_screen_clear,
            silk_screen_clear_minutes=plan.silk_screen_clear_minutes,
        )

    def _intervention(self, snapshot, item: ManualInterventionResult) -> ManualIntervention:
        warning = WarningResult(
            warning_time=snapshot.current_time,
            warning_type=item.warning_type,
            buffer_code=item.buffer_code,
            cycle_code=item.cycle_code,
            cycle_name=item.cycle_name,
            workshop_code=item.workshop_code,
            workshop_name=item.workshop_name,
            upstream_process_code=item.process_from,
            downstream_process_code=item.process_to,
            product_code=item.product_code,
        )
        return ManualIntervention(
            warning=warning,
            reason=item.reason,
            required_capacity=item.required_capacity,
            candidate_machines=[self._selected(m) for m in item.candidates],
        )

    def _return_suggestion(self, snapshot, item: ReturnResult) -> ReturnSuggestion:
        return ReturnSuggestion(
            suggestion_time=snapshot.current_time,
            equipment_code=item.equipment_code,
            product_code=item.product_code,
            original_product_code=item.original_product_code,
            buffer_code=item.buffer_code,
            upstream_process_code=item.process_from,
            downstream_process_code=item.process_to,
            negative_start_time=item.negative_start_time,
            negative_duration_minutes=item.negative_duration_minutes,
            inventory_quantity=item.inventory_quantity,
            safety_inventory_quantity=item.safety_inventory_quantity,
            net_rate=item.net_rate_per_hour,
        )

    def _tracked_event(self, snapshot, item: ReturnResult) -> CutlineEvent:
        return CutlineEvent(
            equipment_code=item.equipment_code,
            cut_time=snapshot.current_time,
            previous_product_code=item.original_product_code or "",
            next_product_code=item.product_code,
            negative_start_time=item.negative_start_time,
        )

    def _selected(self, machine) -> SelectedMachine:
        return SelectedMachine(
            equipment_code=machine.equipment_code,
            workshop_code=machine.workshop_code,
            workshop_name=machine.workshop_name,
            current_product_code=machine.current_product_code,
            target_product_code=machine.target_product_code,
            wafer_size=machine.wafer_size,
            shape_code=machine.shape_code,
            process_code=machine.process_code,
            utilization_rate=machine.utilization_rate,
            idle_rate=machine.idle_rate,
            contribution_capacity=machine.contribution_capacity_per_hour,
        )
