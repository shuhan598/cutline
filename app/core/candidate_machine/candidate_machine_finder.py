# 候选机台查找组件：吃 snapshot + list[StockoutWarningResult]，吐 list[CandidateResult]

from app.core.net_rate.rate_strategy import RateStrategy
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import (
    CandidateMachine,
    CandidateResult,
    StockoutWarningResult,
)


class CandidateMachineFinder:
    """为触发的断料预警，按全局耗尽紧迫度顺序查找同工序同尺寸同形状的在产机台。"""

    def __init__(self, rate_strategy: RateStrategy):
        self._rate_strategy = rate_strategy

    def find(
        self,
        snapshot: CutlineSnapshot,
        warnings: list[StockoutWarningResult],
    ) -> list[CandidateResult]:
        triggered = [
            warning
            for warning in warnings
            if warning.warning_triggered and warning.warning_type == "stockout"
        ]
        triggered.sort(key=self._depletion_sort_key)

        product_model_map = {
            product_model.product_code: product_model
            for product_model in snapshot.product_models
        }

        return [
            self._for_warning(snapshot, warning, product_model_map)
            for warning in triggered
        ]

    def _depletion_sort_key(self, warning: StockoutWarningResult) -> float:
        if warning.depletion_minutes is None:
            return float("inf")
        return warning.depletion_minutes

    def _for_warning(
        self,
        snapshot: CutlineSnapshot,
        warning: StockoutWarningResult,
        product_model_map,
    ) -> CandidateResult:
        target_model = product_model_map.get(warning.product_code)
        candidates = []

        for machine in snapshot.machine_statuses:
            if machine.status != "running":
                continue
            if machine.process_code != warning.process_from:
                continue
            if machine.product_code == warning.product_code:
                continue

            current_model = product_model_map.get(machine.product_code)
            if not self._same_size_and_shape(current_model, target_model):
                continue

            candidates.append(
                CandidateMachine(
                    equipment_code=machine.equipment_code,
                    equipment_name=machine.equipment_name,
                    process_code=machine.process_code,
                    current_product_code=machine.product_code,
                    target_product_code=warning.product_code,
                    wafer_size=current_model.wafer_size if current_model else None,
                    shape_code=current_model.shape_code if current_model else None,
                    current_output_rate_per_hour=self._rate_strategy.output_rate(machine),
                    contribution_capacity_per_hour=self._actual_capacity(
                        snapshot, machine.equipment_code, warning.product_code
                    ),
                    reason="same_process_size_shape_running_machine",
                )
            )

        if candidates:
            return CandidateResult(
                buffer_code=warning.buffer_code,
                product_code=warning.product_code,
                process_from=warning.process_from,
                process_to=warning.process_to,
                candidate_found=True,
                candidate_status="candidate_found",
                reason=None,
                candidates=candidates,
            )

        return CandidateResult(
            buffer_code=warning.buffer_code,
            product_code=warning.product_code,
            process_from=warning.process_from,
            process_to=warning.process_to,
            candidate_found=False,
            candidate_status="manual_intervention_required",
            reason="no_compatible_running_upstream_machine",
            candidates=[],
        )

    def _same_size_and_shape(self, current_model, target_model) -> bool:
        if current_model is None or target_model is None:
            return False
        return (
            current_model.wafer_size == target_model.wafer_size
            and current_model.shape_code == target_model.shape_code
        )

    def _actual_capacity(self, snapshot: CutlineSnapshot, equipment_code, product_code):
        for record in snapshot.capacity_records:
            if (
                record.equipment_code == equipment_code
                and record.product_code == product_code
            ):
                return record.actual_capacity_per_hour
        return None
