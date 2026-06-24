# 段级溢满预警：净速率<0 时按段总容量与段库存预测溢满时间

from typing import List

from app.core.workshop.workshop_resolver import WorkshopResolver
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import NetRateResult, OverflowWarningResult
from app.utils.numeric import safe_float


class OverflowWarningEvaluator:
    """净速率为负（积累）的区间，按物理池段容量预测溢满。"""

    def evaluate(
        self,
        snapshot: CutlineSnapshot,
        net_rates: List[NetRateResult],
    ) -> List[OverflowWarningResult]:
        lead = safe_float(snapshot.config.cutline_lead_minutes)
        workshop_resolver = WorkshopResolver(snapshot)
        capacity_map = {
            segment.buffer_code: safe_float(segment.max_capacity)
            for segment in snapshot.buffer_segments
        }
        segment_inventory = self._segment_inventory(snapshot, workshop_resolver)

        results = []
        for net_rate in net_rates:
            if net_rate.net_rate_per_hour >= 0:
                continue
            capacity = capacity_map.get(net_rate.buffer_code, 0.0)
            inventory = segment_inventory.get(
                (
                    workshop_resolver.normalize_code(net_rate.workshop_code),
                    net_rate.buffer_code,
                ),
                0.0,
            )
            consume = abs(net_rate.net_rate_per_hour)
            overflow_minutes = (capacity - inventory) / consume * 60 if consume > 0 else None

            if overflow_minutes is not None and overflow_minutes <= lead:
                triggered = True
                reason = "overflow_time_within_lead_time"
            else:
                triggered = False
                reason = "overflow_time_beyond_lead_time"

            results.append(
                OverflowWarningResult(
                    buffer_code=net_rate.buffer_code,
                    cycle_code=net_rate.cycle_code,
                    cycle_name=net_rate.cycle_name,
                    workshop_code=net_rate.workshop_code,
                    workshop_name=net_rate.workshop_name,
                    product_code=net_rate.product_code,
                    process_from=net_rate.process_from,
                    process_to=net_rate.process_to,
                    warning_type="overflow",
                    warning_triggered=triggered,
                    reason=reason,
                    segment_inventory=inventory,
                    segment_capacity=capacity,
                    net_rate_per_hour=net_rate.net_rate_per_hour,
                    overflow_minutes=overflow_minutes,
                    cutline_lead_minutes=lead,
                )
            )
        return results

    def _segment_inventory(
        self,
        snapshot: CutlineSnapshot,
        workshop_resolver: WorkshopResolver,
    ) -> dict:
        totals: dict = {}
        for inventory in snapshot.buffer_inventories:
            workshop_code, _ = workshop_resolver.resolve_inventory_workshop(inventory)
            normalized_workshop = workshop_resolver.normalize_code(workshop_code)
            if not normalized_workshop:
                continue
            key = (normalized_workshop, inventory.buffer_code)
            totals[key] = totals.get(key, 0.0) + safe_float(
                inventory.inventory_quantity
            )
        return totals
