# 切线方案构建：断料逐台选取（含借出影响校验）+ 后续溢满切走（Task 6 追加）

from typing import List, Optional, Tuple

from app.schemas.result_schema import (
    CandidateResult,
    DepletionResult,
    ManualInterventionResult,
    NetRateResult,
    PlanResult,
    StockoutWarningResult,
)


class CutlinePlanBuilder:
    """从候选池逐台选取，产出切线方案或人工介入。"""

    def build_stockout(
        self,
        warnings: List[StockoutWarningResult],
        candidate_results: List[CandidateResult],
        net_rates: List[NetRateResult],
        depletions: List[DepletionResult],
        silk_screen_process_codes: Optional[set] = None,
    ) -> Tuple[List[PlanResult], List[ManualInterventionResult]]:
        silk = silk_screen_process_codes or set()
        warning_map = {self._key(w): w for w in warnings}
        net_map = {self._key(n): n for n in net_rates}
        dep_map = {self._key(d): d for d in depletions}

        plans: List[PlanResult] = []
        interventions: List[ManualInterventionResult] = []

        for cr in candidate_results:
            warning = warning_map.get(self._key(cr))
            if warning is None:
                continue
            gap = warning.net_rate_per_hour

            if not cr.candidate_found or not cr.candidates:
                interventions.append(
                    self._intervention(cr, warning, gap, cr.candidates)
                )
                continue

            pool = sorted(cr.candidates, key=self._idle_sort_key, reverse=True)
            selected = []
            for machine in pool:
                if gap <= 0:
                    break
                contribution = machine.contribution_capacity_per_hour
                if not contribution or contribution <= 0:
                    continue
                if self._borrow_harms_origin(machine, warning, net_map, dep_map):
                    continue
                selected.append(machine)
                gap -= contribution

            if gap <= 0 and selected:
                requires_clear = any(m.process_code in silk for m in selected)
                plans.append(
                    PlanResult(
                        buffer_code=warning.buffer_code,
                        product_code=warning.product_code,
                        process_from=warning.process_from,
                        process_to=warning.process_to,
                        warning_type="stockout",
                        selected_machines=selected,
                        total_contribution_capacity=sum(
                            m.contribution_capacity_per_hour for m in selected
                        ),
                        remaining_capacity_gap=gap,
                        requires_silk_screen_clear=requires_clear,
                    )
                )
            else:
                interventions.append(
                    self._intervention(cr, warning, gap, cr.candidates)
                )

        return plans, interventions

    def _borrow_harms_origin(self, machine, warning, net_map, dep_map) -> bool:
        origin_key = (
            warning.buffer_code,
            machine.current_product_code,
            warning.process_from,
            warning.process_to,
        )
        origin_net = net_map.get(origin_key)
        if origin_net is None:
            return False
        new_upstream = origin_net.upstream_output_per_hour - machine.current_output_rate_per_hour
        new_net = origin_net.downstream_input_per_hour - new_upstream
        if new_net <= 0:
            return False
        origin_dep = dep_map.get(origin_key)
        inventory = origin_dep.inventory_quantity if origin_dep else 0.0
        new_depletion_minutes = inventory / new_net * 60
        return new_depletion_minutes <= warning.cutline_lead_minutes

    def _intervention(self, cr, warning, gap, candidates) -> ManualInterventionResult:
        reason = (
            cr.reason
            if cr.reason
            else "capacity_gap_not_closed_by_candidate_pool"
        )
        return ManualInterventionResult(
            buffer_code=warning.buffer_code,
            product_code=warning.product_code,
            process_from=warning.process_from,
            process_to=warning.process_to,
            warning_type="stockout",
            required_capacity=max(gap, 0.0),
            reason=reason,
            candidates=candidates,
        )

    def _idle_sort_key(self, machine) -> float:
        return machine.idle_rate if machine.idle_rate is not None else -1.0

    def _key(self, item):
        return (item.buffer_code, item.product_code, item.process_from, item.process_to)
