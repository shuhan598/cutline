# 溢满切走候选池：在产工序i、生产预警型号X、存在同尺寸同形状且有缺口的目标型号Y

from typing import List

from app.core.net_rate.rate_strategy import RateStrategy
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
        gap_map = {
            (n.buffer_code, n.product_code, n.process_from, n.process_to): n.net_rate_per_hour
            for n in net_rates
        }

        results = []
        for warning in triggered:
            target_y = self._first_target_with_gap(warning, model_map, gap_map)
            candidates = []
            if target_y is not None:
                for machine in snapshot.machine_statuses:
                    if machine.status != "running":
                        continue
                    if machine.process_code != warning.process_from:
                        continue
                    if machine.product_code != warning.product_code:
                        continue
                    y_model = model_map.get(target_y)
                    candidates.append(
                        CandidateMachine(
                            equipment_code=machine.equipment_code,
                            equipment_name=machine.equipment_name,
                            process_code=machine.process_code,
                            current_product_code=machine.product_code,
                            target_product_code=target_y,
                            wafer_size=y_model.wafer_size if y_model else None,
                            shape_code=y_model.shape_code if y_model else None,
                            current_output_rate_per_hour=self._rate_strategy.output_rate(machine),
                            contribution_capacity_per_hour=self._actual_capacity(
                                snapshot, machine.equipment_code, target_y
                            ),
                            reason="overflow_switch_away_to_target_with_gap",
                        )
                    )

            if candidates:
                results.append(
                    CandidateResult(
                        buffer_code=warning.buffer_code,
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

    def _first_target_with_gap(self, warning, model_map, gap_map):
        source_model = model_map.get(warning.product_code)
        if source_model is None:
            return None
        for product_code, model in model_map.items():
            if product_code == warning.product_code:
                continue
            if (model.wafer_size, model.shape_code) != (
                source_model.wafer_size,
                source_model.shape_code,
            ):
                continue
            net = gap_map.get(
                (warning.buffer_code, product_code, warning.process_from, warning.process_to)
            )
            if net is not None and net > 0:
                return product_code
        return None

    def _actual_capacity(self, snapshot: CutlineSnapshot, equipment_code, product_code):
        for record in snapshot.capacity_records:
            if record.equipment_code == equipment_code and record.product_code == product_code:
                return record.actual_capacity_per_hour
        return None
