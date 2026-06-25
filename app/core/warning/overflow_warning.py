from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import OverflowTimeResult, OverflowWarningResult


class OverflowWarningEvaluator:
    """Evaluate overflow warnings from precomputed overflow times."""

    def evaluate(
        self,
        snapshot: CutlineSnapshot,
        overflow_times: list[OverflowTimeResult],
    ) -> list[OverflowWarningResult]:
        results = []
        for overflow_time in overflow_times:
            if (
                overflow_time.overflow_minutes is not None
                and overflow_time.overflow_minutes <= overflow_time.cutline_lead_minutes
            ):
                triggered = True
                reason = "overflow_time_within_lead_time"
            else:
                triggered = False
                reason = "overflow_time_beyond_lead_time"

            results.append(
                OverflowWarningResult(
                    buffer_code=overflow_time.buffer_code,
                    cycle_code=overflow_time.cycle_code,
                    cycle_name=overflow_time.cycle_name,
                    workshop_code=overflow_time.workshop_code,
                    workshop_name=overflow_time.workshop_name,
                    product_code=overflow_time.product_code,
                    process_from=overflow_time.process_from,
                    process_to=overflow_time.process_to,
                    warning_type="overflow",
                    warning_triggered=triggered,
                    reason=reason,
                    segment_inventory=overflow_time.segment_inventory,
                    segment_capacity=overflow_time.segment_capacity,
                    net_rate_per_hour=overflow_time.net_rate_per_hour,
                    overflow_minutes=overflow_time.overflow_minutes,
                    cutline_lead_minutes=overflow_time.cutline_lead_minutes,
                )
            )
        return results
