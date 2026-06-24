# 候选机台查找组件：吃 snapshot + list[StockoutWarningResult]，吐 list[CandidateResult]

from app.core.candidate_machine.product_compatibility import ProductCompatibilityChecker
from app.core.candidate_machine.workshop_scope import WorkshopScopeChecker
from app.core.net_rate.rate_strategy import RateStrategy
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import (
    CandidateMachine,
    CandidateResult,
    StockoutWarningResult,
)


class StockoutCandidateFinder:
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
        compatibility_checker = ProductCompatibilityChecker(snapshot)
        workshop_scope_checker = WorkshopScopeChecker(snapshot)
        warning_workshop_code, warning_workshop_name = (
            workshop_scope_checker.resolve_warning_workshop(warning)
        )
        candidates = []

        for machine in snapshot.machine_statuses:
            if machine.status != "running":
                continue
            if machine.process_code != warning.process_from:
                continue
            if machine.product_code == warning.product_code:
                continue
            if not workshop_scope_checker.is_same_workshop(machine, warning):
                continue

            current_model = product_model_map.get(machine.product_code)
            if not compatibility_checker.is_compatible(
                machine,
                current_model,
                target_model,
            ):
                continue

            current_output = self._rate_strategy.output_rate(machine)
            current_capacity = self._actual_capacity(
                snapshot, machine.equipment_code, machine.product_code
            )
            if current_capacity and current_capacity > 0:
                utilization_rate = current_output / current_capacity
                idle_rate = 1.0 - utilization_rate
            else:
                utilization_rate = None
                idle_rate = None

            machine_workshop_code, machine_workshop_name = (
                workshop_scope_checker.resolve_machine_workshop(machine)
            )
            candidates.append(
                CandidateMachine(
                    equipment_code=machine.equipment_code,
                    equipment_name=machine.equipment_name,
                    workshop_code=machine_workshop_code,
                    workshop_name=machine_workshop_name,
                    process_code=machine.process_code,
                    current_product_code=machine.product_code,
                    target_product_code=warning.product_code,
                    wafer_size=current_model.wafer_size if current_model else None,
                    shape_code=current_model.shape_code if current_model else None,
                    current_output_rate_per_hour=current_output,
                    contribution_capacity_per_hour=self._actual_capacity(
                        snapshot, machine.equipment_code, warning.product_code
                    ),
                    utilization_rate=utilization_rate,
                    idle_rate=idle_rate,
                    reason="same_process_size_shape_running_machine",
                )
            )

        if candidates:
            return CandidateResult(
                buffer_code=warning.buffer_code,
                cycle_code=warning.cycle_code,
                cycle_name=warning.cycle_name,
                workshop_code=warning_workshop_code,
                workshop_name=warning_workshop_name,
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
            cycle_code=warning.cycle_code,
            cycle_name=warning.cycle_name,
            workshop_code=warning_workshop_code,
            workshop_name=warning_workshop_name,
            product_code=warning.product_code,
            process_from=warning.process_from,
            process_to=warning.process_to,
            candidate_found=False,
            candidate_status="manual_intervention_required",
            reason="no_compatible_running_upstream_machine",
            candidates=[],
        )

    def _actual_capacity(self, snapshot: CutlineSnapshot, equipment_code, product_code):
        for record in snapshot.capacity_records:
            if (
                record.equipment_code == equipment_code
                and record.product_code == product_code
            ):
                return record.actual_capacity_per_hour
        return None
