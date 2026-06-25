# 溢满切走候选池：在产工序i、生产预警型号X、存在同尺寸同形状且有缺口的目标型号Y

from typing import List

from app.core.candidate_machine.product_compatibility import ProductCompatibilityChecker
from app.core.candidate_machine.workshop_scope import WorkshopScopeChecker
from app.core.net_rate.rate_strategy import RateStrategy
from app.core.workshop.workshop_resolver import WorkshopResolver
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import (
    CandidateMachine,
    CandidateResult,
    NetRateResult,
    OverflowWarningResult,
)


class OverflowCandidateFinder:
    """为触发的溢满预警查找可切走的在产机台及其目标型号Y。"""

    def __init__(self, rate_strategy: RateStrategy):
        self._rate_strategy = rate_strategy

    def find(
        self,
        snapshot: CutlineSnapshot,
        warnings: List[OverflowWarningResult],
        net_rates: List[NetRateResult],
    ) -> List[CandidateResult]:
        triggered = [w for w in warnings if w.warning_triggered]
        model_map = {m.product_code: m for m in snapshot.product_models}
        workshop_resolver = WorkshopResolver(snapshot)
        gap_map = {
            (
                workshop_resolver.normalize_code(n.workshop_code),
                n.buffer_code,
                n.product_code,
                n.process_from,
                n.process_to,
            ): n.net_rate_per_hour
            for n in net_rates
        }
        compatibility_checker = ProductCompatibilityChecker(snapshot)
        workshop_scope_checker = WorkshopScopeChecker(snapshot)

        results = []
        for warning in triggered:
            warning_workshop_code, warning_workshop_name = (
                workshop_scope_checker.resolve_warning_workshop(warning)
            )
            candidates = []
            for machine in snapshot.machine_statuses:
                if machine.status != "running":
                    continue
                if machine.process_code != warning.process_from:
                    continue
                if machine.product_code != warning.product_code:
                    continue
                if not workshop_scope_checker.is_same_workshop(machine, warning):
                    continue

                target_y = self._first_target_with_gap(
                    warning,
                    model_map,
                    gap_map,
                    compatibility_checker,
                    machine,
                    workshop_resolver.normalize_code(warning_workshop_code),
                )
                if target_y is None:
                    continue

                y_model = model_map.get(target_y)
                current_output = self._rate_strategy.output_rate(machine)
                current_capacity = self._actual_capacity(
                    snapshot, machine.equipment_code, machine.product_code
                )
                if current_capacity and current_capacity > 0:
                    utilization_rate = current_output / current_capacity
                else:
                    utilization_rate = None
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
                        target_product_code=target_y,
                        wafer_size=y_model.wafer_size if y_model else None,
                        shape_code=y_model.shape_code if y_model else None,
                        current_output_rate_per_hour=current_output,
                        contribution_capacity_per_hour=self._actual_capacity(
                            snapshot, machine.equipment_code, target_y
                        ),
                        utilization_rate=utilization_rate,
                        reason="overflow_switch_away_to_target_with_gap",
                    )
                )

            if candidates:
                results.append(
                    CandidateResult(
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
                )
            else:
                results.append(
                    CandidateResult(
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
                        reason="no_target_model_with_capacity_gap",
                        candidates=[],
                    )
                )
        return results

    def _first_target_with_gap(
        self,
        warning,
        model_map,
        gap_map,
        compatibility_checker,
        machine,
        warning_workshop_code,
    ):
        source_model = model_map.get(warning.product_code)
        if source_model is None:
            return None
        for product_code, model in model_map.items():
            if product_code == warning.product_code:
                continue
            if not compatibility_checker.is_compatible(
                machine,
                source_model,
                model,
            ):
                continue
            net = gap_map.get(
                (
                    warning_workshop_code,
                    warning.buffer_code,
                    product_code,
                    warning.process_from,
                    warning.process_to,
                )
            )
            if net is not None and net > 0:
                return product_code
        return None

    def _actual_capacity(self, snapshot: CutlineSnapshot, equipment_code, product_code):
        for record in snapshot.capacity_records:
            if record.equipment_code == equipment_code and record.product_code == product_code:
                return record.actual_capacity_per_hour
        return None
