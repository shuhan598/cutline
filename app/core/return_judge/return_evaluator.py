# 切回判断：遍历被跟踪切线事件，按净速率/持续时长/安全水位三条件判定，并回吐 negative_start_time

from typing import List, Optional

from app.core.workshop.workshop_resolver import WorkshopResolver
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import DepletionResult, NetRateResult, ReturnResult
from app.utils.numeric import safe_float


class ReturnEvaluator:
    """对每个被跟踪切线事件产出一条切回判断结果（含更新后的 negative_start_time）。"""

    def evaluate(
        self,
        snapshot: CutlineSnapshot,
        net_rates: List[NetRateResult],
        depletions: List[DepletionResult],
    ) -> List[ReturnResult]:
        lead = safe_float(snapshot.config.cutline_lead_minutes)
        window = safe_float(snapshot.config.stability_window_minutes)
        current = snapshot.current_time
        machine_map = {m.equipment_code: m for m in snapshot.machine_statuses}
        workshop_resolver = WorkshopResolver(snapshot)

        results = []
        for event in snapshot.active_cutline_events:
            machine = machine_map.get(event.equipment_code)
            process_from = machine.process_code if machine else None
            workshop_code = event.workshop_code
            workshop_name = event.workshop_name
            if not self._normalize_code(workshop_code) and machine is not None:
                workshop_code, workshop_name = workshop_resolver.resolve_machine_workshop(machine)
            net = self._find(
                net_rates,
                event.next_product_code,
                process_from,
                workshop_code,
            )
            inventory = self._inventory(
                depletions,
                event.next_product_code,
                process_from,
                workshop_code,
            )

            negative_start = event.negative_start_time
            duration = None
            safety = None
            triggered = False
            net_rate = net.net_rate_per_hour if net else None

            if net is not None and net.net_rate_per_hour < 0:
                if negative_start is None:
                    negative_start = current
                duration = (current - negative_start).total_seconds() / 60
                safety = lead / 60 * abs(net.net_rate_per_hour)
                triggered = (
                    duration > window
                    and inventory is not None
                    and inventory > safety
                )
            else:
                negative_start = None

            results.append(
                ReturnResult(
                    equipment_code=event.equipment_code,
                    workshop_code=workshop_code,
                    workshop_name=workshop_name,
                    product_code=event.next_product_code,
                    original_product_code=event.previous_product_code,
                    buffer_code=net.buffer_code if net else None,
                    process_from=process_from,
                    process_to=net.process_to if net else None,
                    net_rate_per_hour=net_rate,
                    inventory_quantity=inventory,
                    negative_start_time=negative_start,
                    negative_duration_minutes=duration,
                    safety_inventory_quantity=safety,
                    triggered=triggered,
                )
            )
        return results

    def _find(
        self,
        net_rates,
        product_code,
        process_from,
        workshop_code,
    ) -> Optional[NetRateResult]:
        normalized_workshop = self._normalize_code(workshop_code)
        if normalized_workshop:
            for net in net_rates:
                if (
                    net.product_code == product_code
                    and net.process_from == process_from
                    and self._normalize_code(net.workshop_code) == normalized_workshop
                ):
                    return net
            return None

        for net in net_rates:
            if net.product_code == product_code and net.process_from == process_from:
                return net
        return None

    def _inventory(self, depletions, product_code, process_from, workshop_code):
        normalized_workshop = self._normalize_code(workshop_code)
        if normalized_workshop:
            for depletion in depletions:
                if (
                    depletion.product_code == product_code
                    and depletion.process_from == process_from
                    and self._normalize_code(depletion.workshop_code) == normalized_workshop
                ):
                    return depletion.inventory_quantity
            return None

        for depletion in depletions:
            if depletion.product_code == product_code and depletion.process_from == process_from:
                return depletion.inventory_quantity
        return None

    def _normalize_code(self, value) -> str:
        if value is None:
            return ""
        return value.strip().upper()
