# 耗尽时间计算组件：吃 snapshot + list[NetRateResult]，吐 list[DepletionResult]

from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import DepletionResult, NetRateResult
from app.utils.numeric import safe_float


class DepletionTimeCalculator:
    """按净速率与区间库存推算耗尽时间（分钟）。"""

    def calculate(
        self,
        snapshot: CutlineSnapshot,
        net_rates: list[NetRateResult],
    ) -> list[DepletionResult]:
        return [self._for_segment(snapshot, net_rate) for net_rate in net_rates]

    def _for_segment(
        self,
        snapshot: CutlineSnapshot,
        net_rate: NetRateResult,
    ) -> DepletionResult:
        inventory_quantity = self._inventory_quantity(
            snapshot,
            net_rate.buffer_code,
            net_rate.product_code,
            net_rate.process_from,
            net_rate.process_to,
        )
        net_rate_per_hour = safe_float(net_rate.net_rate_per_hour)

        depletion_minutes = None
        if net_rate_per_hour > 0:
            depletion_minutes = inventory_quantity / net_rate_per_hour * 60
            depletion_status = "decreasing"
        elif net_rate_per_hour == 0:
            depletion_status = "stable"
        else:
            depletion_status = "increasing"

        return DepletionResult(
            buffer_code=net_rate.buffer_code,
            product_code=net_rate.product_code,
            process_from=net_rate.process_from,
            process_to=net_rate.process_to,
            inventory_quantity=inventory_quantity,
            net_rate_per_hour=net_rate_per_hour,
            depletion_minutes=depletion_minutes,
            depletion_status=depletion_status,
        )

    def _inventory_quantity(
        self,
        snapshot: CutlineSnapshot,
        buffer_code,
        product_code,
        process_from,
        process_to,
    ) -> float:
        total = 0.0
        for inventory in snapshot.buffer_inventories:
            if (
                inventory.buffer_code == buffer_code
                and inventory.product_code == product_code
                and inventory.process_from == process_from
                and inventory.process_to == process_to
            ):
                total += safe_float(inventory.inventory_quantity)
        return total
