# 断料预警评估组件：吃 snapshot + list[DepletionResult]，吐 list[StockoutWarningResult]

from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import DepletionResult, StockoutWarningResult
from app.utils.numeric import safe_float


class StockoutWarningEvaluator:
    """耗尽时间 ≤ 切线提前量则触发断料预警。"""

    def evaluate(
        self,
        snapshot: CutlineSnapshot,
        depletions: list[DepletionResult],
    ) -> list[StockoutWarningResult]:
        cutline_lead_minutes = safe_float(snapshot.config.cutline_lead_minutes)
        return [
            self._for_segment(depletion, cutline_lead_minutes)
            for depletion in depletions
        ]

    def _for_segment(
        self,
        depletion: DepletionResult,
        cutline_lead_minutes: float,
    ) -> StockoutWarningResult:
        warning_triggered = False
        if depletion.depletion_status != "decreasing":
            reason = "inventory_not_decreasing"
        elif depletion.depletion_minutes is None:
            reason = "depletion_time_not_available"
        elif depletion.depletion_minutes <= cutline_lead_minutes:
            warning_triggered = True
            reason = "depletion_time_within_lead_time"
        else:
            reason = "depletion_time_beyond_lead_time"

        return StockoutWarningResult(
            buffer_code=depletion.buffer_code,
            cycle_code=depletion.cycle_code,
            cycle_name=depletion.cycle_name,
            workshop_code=depletion.workshop_code,
            workshop_name=depletion.workshop_name,
            product_code=depletion.product_code,
            process_from=depletion.process_from,
            process_to=depletion.process_to,
            warning_type="stockout",
            warning_triggered=warning_triggered,
            reason=reason,
            inventory_quantity=depletion.inventory_quantity,
            net_rate_per_hour=depletion.net_rate_per_hour,
            depletion_minutes=depletion.depletion_minutes,
            depletion_status=depletion.depletion_status,
            cutline_lead_minutes=cutline_lead_minutes,
        )
