# 切线评估门面：调用管道，把内部结果对象映射为对外 CutlineEvaluateResponse

from typing import Optional

from app.schemas.request_schema import CutlineSnapshot
from app.schemas.response_schema import (
    CutlineEvaluateResponse,
    ManualIntervention,
    SelectedMachine,
    WarningResult,
)
from app.schemas.result_schema import CandidateResult, StockoutWarningResult
from app.service.cutline_pipeline import CutlinePipeline


class CutlineService:
    """对外统一入口：evaluate(snapshot) -> CutlineEvaluateResponse。"""

    def __init__(self, pipeline: Optional[CutlinePipeline] = None):
        self._pipeline = pipeline or CutlinePipeline()

    def evaluate(self, snapshot: CutlineSnapshot) -> CutlineEvaluateResponse:
        result = self._pipeline.run(snapshot)

        warning_by_segment = {}
        warnings_out = []
        for warning in result.warnings:
            if not warning.warning_triggered:
                continue
            warning_result = self._to_warning_result(snapshot, warning)
            warnings_out.append(warning_result)
            warning_by_segment[self._segment_key(warning)] = warning_result

        interventions = []
        for candidate in result.candidates:
            warning_result = warning_by_segment.get(self._segment_key(candidate))
            if warning_result is None:
                continue
            interventions.append(
                self._to_manual_intervention(warning_result, candidate)
            )

        return CutlineEvaluateResponse(
            success=True,
            message="",
            warnings=warnings_out,
            plans=[],
            manual_interventions=interventions,
            return_suggestions=[],
        )

    def _segment_key(self, item):
        return (item.buffer_code, item.product_code, item.process_from, item.process_to)

    def _to_warning_result(
        self,
        snapshot: CutlineSnapshot,
        warning: StockoutWarningResult,
    ) -> WarningResult:
        return WarningResult(
            warning_time=snapshot.current_time,
            warning_type=warning.warning_type,
            buffer_code=warning.buffer_code,
            upstream_process_code=warning.process_from,
            downstream_process_code=warning.process_to,
            product_code=warning.product_code,
            inventory_quantity=warning.inventory_quantity,
            net_rate=warning.net_rate_per_hour,
            prediction_minutes=warning.depletion_minutes,
            cutline_lead_minutes=warning.cutline_lead_minutes,
        )

    def _to_manual_intervention(
        self,
        warning_result: WarningResult,
        candidate: CandidateResult,
    ) -> ManualIntervention:
        candidate_machines = [
            SelectedMachine(
                equipment_code=machine.equipment_code,
                current_product_code=machine.current_product_code,
                target_product_code=machine.target_product_code,
                wafer_size=machine.wafer_size,
                shape_code=machine.shape_code,
                process_code=machine.process_code,
                contribution_capacity=machine.contribution_capacity_per_hour,
            )
            for machine in candidate.candidates
        ]
        return ManualIntervention(
            warning=warning_result,
            reason=candidate.reason or candidate.candidate_status,
            candidate_machines=candidate_machines,
        )
