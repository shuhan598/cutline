# Algorithm return evaluator.

from app.schemas.common_schema import AlgorithmActiveCutlineEvent
from app.schemas.request_schema import AlgorithmSnapshot
from app.schemas.result_schema import (
    AlgorithmIntervalNetRateResult,
    AlgorithmReturnResult,
)

class ReturnEvaluationError(ValueError):
    """Algorithm return evaluator."""

    def __init__(self, reason: str, event_id: str) -> None:
        self.reason = reason
        self.event_id = event_id
        super().__init__(f"{event_id}: {reason}")


class ReturnEvaluator:
    """Algorithm return evaluator."""

    def evaluate_algorithm(
        self,
        *,
        snapshot: AlgorithmSnapshot,
        interval_results: list[AlgorithmIntervalNetRateResult],
    ) -> list[AlgorithmReturnResult]:
        results: list[AlgorithmReturnResult] = []
        for event in snapshot.active_cutline_events:
            if event.status != "active":
                continue
            target_interval = self._algorithm_target_interval(
                event,
                interval_results,
            )
            results.append(
                self._evaluate_algorithm_event(
                    snapshot=snapshot,
                    event=event,
                    target_interval=target_interval,
                )
            )
        return results

    def _algorithm_target_interval(
        self,
        event: AlgorithmActiveCutlineEvent,
        interval_results: list[AlgorithmIntervalNetRateResult],
    ) -> AlgorithmIntervalNetRateResult:
        event_key = (
            event.workshop_code,
            event.target_buffer_code,
            event.target_order_code,
            event.target_wafer_size,
            event.target_wafer_spec,
            event.upstream_process_code,
            event.downstream_process_code,
        )
        matches = [
            interval
            for interval in interval_results
            if (
                interval.workshop_code,
                interval.buffer_code,
                interval.order_code,
                interval.wafer_size,
                interval.wafer_spec,
                interval.upstream_process_code,
                interval.downstream_process_code,
            )
            == event_key
        ]
        if not matches:
            raise ReturnEvaluationError(
                "target_interval_not_found",
                event.event_id,
            )
        if len(matches) > 1:
            raise ReturnEvaluationError(
                "target_interval_ambiguous",
                event.event_id,
            )
        return matches[0]

    def _evaluate_algorithm_event(
        self,
        *,
        snapshot: AlgorithmSnapshot,
        event: AlgorithmActiveCutlineEvent,
        target_interval: AlgorithmIntervalNetRateResult,
    ) -> AlgorithmReturnResult:
        current_time = snapshot.current_time
        previous_negative_start = event.negative_start_time
        condition_net_rate_met = target_interval.net_consumption_rate < 0
        if condition_net_rate_met:
            updated_negative_start = (
                previous_negative_start or current_time
            )
            negative_duration_minutes = (
                current_time - updated_negative_start
            ).total_seconds() / 60
        else:
            updated_negative_start = None
            negative_duration_minutes = 0.0

        cutline_duration_minutes = (
            current_time - event.cutline_start_time
        ).total_seconds() / 60
        stability_window_minutes = (
            snapshot.config.stability_window_minutes
        )
        stockout_warning_lead_minutes = (
            snapshot.config.stockout_warning_lead_minutes
        )
        safe_inventory_quantity = (
            stockout_warning_lead_minutes
            / 60
            * abs(target_interval.net_consumption_rate)
        )
        condition_stability_met = (
            negative_duration_minutes > stability_window_minutes
        )
        condition_inventory_met = (
            target_interval.current_quantity > safe_inventory_quantity
        )
        return_recommended = (
            condition_net_rate_met
            and condition_stability_met
            and condition_inventory_met
        )
        reason = self._algorithm_reason(
            condition_net_rate_met=condition_net_rate_met,
            condition_stability_met=condition_stability_met,
            condition_inventory_met=condition_inventory_met,
        )

        updated_status = (
            "return_recommended" if return_recommended else "active"
        )

        return AlgorithmReturnResult(
            event_id=event.event_id,
            machine_code=event.machine_code,
            source_order_code=event.source_order_code,
            target_order_code=event.target_order_code,
            workshop_code=event.workshop_code,
            source_buffer_code=event.source_buffer_code,
            target_buffer_code=event.target_buffer_code,
            upstream_process_code=event.upstream_process_code,
            downstream_process_code=event.downstream_process_code,
            target_wafer_size=event.target_wafer_size,
            target_wafer_spec=event.target_wafer_spec,
            current_time=current_time,
            cutline_start_time=event.cutline_start_time,
            previous_negative_start_time=previous_negative_start,
            updated_negative_start_time=updated_negative_start,
            cutline_duration_minutes=cutline_duration_minutes,
            negative_duration_minutes=negative_duration_minutes,
            net_consumption_rate=target_interval.net_consumption_rate,
            current_quantity=target_interval.current_quantity,
            stability_window_minutes=stability_window_minutes,
            stockout_warning_lead_minutes=(
                stockout_warning_lead_minutes
            ),
            safe_inventory_quantity=safe_inventory_quantity,
            condition_net_rate_met=condition_net_rate_met,
            condition_stability_met=condition_stability_met,
            condition_inventory_met=condition_inventory_met,
            return_recommended=return_recommended,
            previous_status=event.status,
            updated_status=updated_status,
            reason=reason,
        )

    def _algorithm_reason(
        self,
        *,
        condition_net_rate_met: bool,
        condition_stability_met: bool,
        condition_inventory_met: bool,
    ) -> str:
        if not condition_net_rate_met:
            return "net_rate_not_negative"
        if not condition_stability_met:
            return "stability_window_not_met"
        if not condition_inventory_met:
            return "inventory_not_above_safe_level"
        return "all_return_conditions_met"
