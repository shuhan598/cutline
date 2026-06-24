# 切线方案构建：断料逐台选取（含借出影响校验）+ 后续溢满切走（Task 6 追加）

from typing import List, Optional, Tuple

from app.core.workshop.workshop_resolver import WorkshopResolver
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import (
    CandidateResult,
    DepletionResult,
    ManualInterventionResult,
    NetRateResult,
    OverflowWarningResult,
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
                        cycle_code=warning.cycle_code,
                        cycle_name=warning.cycle_name,
                        workshop_code=warning.workshop_code,
                        workshop_name=warning.workshop_name,
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

    def build_overflow(
        self,
        snapshot: CutlineSnapshot,
        warnings: List[OverflowWarningResult],
        candidate_results: List[CandidateResult],
        net_rates: List[NetRateResult],
    ) -> Tuple[List[PlanResult], List[ManualInterventionResult]]:
        warning_map = {self._key(w): w for w in warnings if w.warning_triggered}
        net_map = {self._key(n): n for n in net_rates}
        capacity_map = {
            segment.buffer_code: segment.max_capacity
            for segment in snapshot.buffer_segments
        }
        workshop_resolver = WorkshopResolver(snapshot)
        segment_inventory = self._segment_inventory(snapshot, workshop_resolver)

        plans: List[PlanResult] = []
        interventions: List[ManualInterventionResult] = []

        for cr in candidate_results:
            warning = warning_map.get(self._key(cr))
            if warning is None:
                continue

            source_net = net_map.get(self._key(cr))
            remaining = abs(source_net.net_rate_per_hour) if source_net else 0.0

            if not cr.candidate_found or not cr.candidates:
                interventions.append(
                    self._overflow_intervention(warning, remaining, cr.candidates)
                )
                continue

            pool = sorted(cr.candidates, key=self._utilization_sort_key, reverse=True)
            selected = []
            current_source_upstream = (
                source_net.upstream_output_per_hour if source_net else 0.0
            )
            source_downstream = source_net.downstream_input_per_hour if source_net else 0.0

            for machine in pool:
                target_net = net_map.get(
                    (
                        self._normalize_code(warning.workshop_code),
                        warning.buffer_code,
                        machine.target_product_code,
                        warning.process_from,
                        warning.process_to,
                    )
                )
                contribution = machine.contribution_capacity_per_hour or 0.0
                if self._switch_in_overflows_target(
                    warning,
                    target_net,
                    contribution,
                    capacity_map,
                    segment_inventory,
                    workshop_resolver,
                ):
                    continue
                selected.append(machine)
                current_source_upstream -= machine.current_output_rate_per_hour
                if source_downstream - current_source_upstream >= 0:
                    break

            new_source_net = source_downstream - current_source_upstream
            if selected and new_source_net >= 0:
                plans.append(
                    PlanResult(
                        buffer_code=warning.buffer_code,
                        cycle_code=warning.cycle_code,
                        cycle_name=warning.cycle_name,
                        workshop_code=warning.workshop_code,
                        workshop_name=warning.workshop_name,
                        product_code=warning.product_code,
                        process_from=warning.process_from,
                        process_to=warning.process_to,
                        warning_type="overflow",
                        selected_machines=selected,
                        total_contribution_capacity=sum(
                            m.contribution_capacity_per_hour or 0.0 for m in selected
                        ),
                        remaining_capacity_gap=new_source_net,
                    )
                )
            else:
                interventions.append(
                    self._overflow_intervention(warning, max(new_source_net, 0.0), cr.candidates)
                )

        return plans, interventions

    def _switch_in_overflows_target(
        self,
        warning,
        target_net,
        contribution,
        capacity_map,
        segment_inventory,
        workshop_resolver,
    ) -> bool:
        if target_net is None:
            return True
        new_target_net = target_net.net_rate_per_hour - contribution
        if new_target_net >= 0:
            return False
        capacity = capacity_map.get(warning.buffer_code, 0.0)
        inventory = segment_inventory.get(
            (
                workshop_resolver.normalize_code(warning.workshop_code),
                warning.buffer_code,
            ),
            0.0,
        )
        overflow_minutes = (capacity - inventory) / abs(new_target_net) * 60
        return overflow_minutes <= warning.cutline_lead_minutes

    def _segment_inventory(
        self,
        snapshot: CutlineSnapshot,
        workshop_resolver: WorkshopResolver,
    ) -> dict:
        totals = {}
        for inventory in snapshot.buffer_inventories:
            workshop_code, _ = workshop_resolver.resolve_inventory_workshop(inventory)
            normalized_workshop = workshop_resolver.normalize_code(workshop_code)
            if not normalized_workshop:
                continue
            key = (normalized_workshop, inventory.buffer_code)
            totals[key] = totals.get(key, 0.0) + inventory.inventory_quantity
        return totals

    def _overflow_intervention(self, warning, remaining, candidates) -> ManualInterventionResult:
        return ManualInterventionResult(
            buffer_code=warning.buffer_code,
            cycle_code=warning.cycle_code,
            cycle_name=warning.cycle_name,
            workshop_code=warning.workshop_code,
            workshop_name=warning.workshop_name,
            product_code=warning.product_code,
            process_from=warning.process_from,
            process_to=warning.process_to,
            warning_type="overflow",
            required_capacity=remaining,
            reason="overflow_risk_not_resolved_by_candidate_pool",
            candidates=candidates,
        )

    def _utilization_sort_key(self, machine) -> float:
        return machine.utilization_rate if machine.utilization_rate is not None else -1.0

    def _borrow_harms_origin(self, machine, warning, net_map, dep_map) -> bool:
        origin_key = (
            self._normalize_code(warning.workshop_code),
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
            cycle_code=warning.cycle_code,
            cycle_name=warning.cycle_name,
            workshop_code=warning.workshop_code,
            workshop_name=warning.workshop_name,
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
        return (
            self._normalize_code(getattr(item, "workshop_code", None)),
            item.buffer_code,
            item.product_code,
            item.process_from,
            item.process_to,
        )

    def _normalize_code(self, value: Optional[str]) -> str:
        if value is None:
            return ""
        return value.strip().upper()
