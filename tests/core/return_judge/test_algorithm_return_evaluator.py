from datetime import datetime, timedelta

import pytest

from app.core import return_judge
from app.core.return_judge.active_cutline_event_tracker import (
    ActiveCutlineEventTracker,
)
from app.core.return_judge.return_evaluator import ReturnEvaluator
from app.schemas.result_schema import AlgorithmReturnResult
from tests.core.return_judge.helpers import (
    CURRENT_TIME,
    active_event,
    algorithm_snapshot,
    interval,
)


def _evaluate(*, event=None, intervals=None, current_time=CURRENT_TIME):
    events = [] if event is None else [event]
    return ReturnEvaluator().evaluate_algorithm(
        snapshot=algorithm_snapshot(
            current_time=current_time,
            active_cutline_events=events,
        ),
        interval_results=list(intervals or []),
    )


def _next_event(event, result):
    tracker = ActiveCutlineEventTracker()
    updated = tracker.update_negative_start_time(
        event=event,
        negative_start_time=result.updated_negative_start_time,
    )
    if result.updated_status == "return_recommended":
        updated = tracker.mark_return_recommended(event=updated)
    return updated


def test_no_active_events_returns_empty_list():
    assert _evaluate() == []


@pytest.mark.parametrize(
    "status",
    ["return_recommended", "returned", "cancelled"],
)
def test_only_active_status_is_evaluated(status):
    assert _evaluate(event=active_event(status=status)) == []


def test_active_event_uses_full_seven_field_interval_key():
    wrong_buffer = interval(
        buffer_code="BUF-OTHER",
        net_consumption_rate=200,
    )
    matched = interval(net_consumption_rate=-4800)

    result = _evaluate(
        event=active_event(),
        intervals=[wrong_buffer, matched],
    )[0]

    assert result.target_buffer_code == "BUF-TARGET"
    assert result.net_consumption_rate == -4800
    assert result.reason == "stability_window_not_met"


def test_missing_target_interval_raises_explicit_error():
    with pytest.raises(Exception) as exc_info:
        _evaluate(event=active_event(), intervals=[])

    assert exc_info.value.__class__.__name__ == "ReturnEvaluationError"
    assert exc_info.value.reason == "target_interval_not_found"


def test_return_evaluation_error_is_publicly_exported():
    assert return_judge.ReturnEvaluationError.__name__ == (
        "ReturnEvaluationError"
    )


def test_ambiguous_target_interval_raises_explicit_error():
    duplicate = interval()

    with pytest.raises(Exception) as exc_info:
        _evaluate(event=active_event(), intervals=[duplicate, duplicate])

    assert exc_info.value.__class__.__name__ == "ReturnEvaluationError"
    assert exc_info.value.reason == "target_interval_ambiguous"


def test_first_negative_rate_starts_timer_at_snapshot_time():
    event = active_event(negative_start_time=None)
    result = _evaluate(
        event=event,
        intervals=[interval(net_consumption_rate=-1000)],
    )[0]

    assert result.previous_negative_start_time is None
    assert result.updated_negative_start_time == CURRENT_TIME
    assert result.negative_duration_minutes == 0
    assert _next_event(event, result).negative_start_time == CURRENT_TIME
    assert result.return_recommended is False


def test_continuing_negative_rate_preserves_original_negative_start_time():
    negative_start = CURRENT_TIME - timedelta(minutes=25)
    result = _evaluate(
        event=active_event(
            cutline_start_time=CURRENT_TIME - timedelta(hours=2),
            negative_start_time=negative_start,
        ),
        intervals=[interval(net_consumption_rate=-1000)],
    )[0]

    assert result.updated_negative_start_time == negative_start
    assert result.negative_duration_minutes == 25
    assert result.cutline_duration_minutes == 120


@pytest.mark.parametrize("net_consumption_rate", [0, 200])
def test_nonnegative_rate_clears_negative_start_time(net_consumption_rate):
    original_start = CURRENT_TIME - timedelta(minutes=25)
    event = active_event(negative_start_time=original_start)
    result = _evaluate(
        event=event,
        intervals=[
            interval(net_consumption_rate=net_consumption_rate)
        ],
    )[0]

    assert result.previous_negative_start_time == original_start
    assert result.updated_negative_start_time is None
    assert _next_event(event, result).negative_start_time is None
    assert result.negative_duration_minutes == 0
    assert result.reason == "net_rate_not_negative"


@pytest.mark.parametrize(
    ("duration_minutes", "condition_met"),
    [(19, False), (20, False), (25, True)],
)
def test_stability_condition_uses_strictly_greater_than_window(
    duration_minutes,
    condition_met,
):
    result = _evaluate(
        event=active_event(
            negative_start_time=CURRENT_TIME
            - timedelta(minutes=duration_minutes)
        ),
        intervals=[interval(net_consumption_rate=-4800)],
    )[0]

    assert result.negative_duration_minutes == duration_minutes
    assert result.condition_stability_met is condition_met


@pytest.mark.parametrize(
    ("current_quantity", "condition_met", "recommended"),
    [(2400, False, False), (2401, True, True)],
)
def test_safe_inventory_formula_and_strict_inventory_threshold(
    current_quantity,
    condition_met,
    recommended,
):
    result = _evaluate(
        event=active_event(
            negative_start_time=CURRENT_TIME - timedelta(minutes=25)
        ),
        intervals=[
            interval(
                net_consumption_rate=-4800,
                current_quantity=current_quantity,
            )
        ],
    )[0]

    assert result.safe_inventory_quantity == 2400
    assert result.condition_inventory_met is condition_met
    assert result.return_recommended is recommended
    assert result.updated_status == (
        "return_recommended" if recommended else "active"
    )


def test_safe_inventory_and_result_use_stockout_warning_lead_parameter():
    event = active_event(
        negative_start_time=CURRENT_TIME - timedelta(minutes=25)
    )
    result = ReturnEvaluator().evaluate_algorithm(
        snapshot=algorithm_snapshot(
            active_cutline_events=[event],
            stockout_warning_lead_minutes=15,
        ),
        interval_results=[
            interval(net_consumption_rate=-4800, current_quantity=1201)
        ],
    )[0]

    assert result.stockout_warning_lead_minutes == 15
    assert result.safe_inventory_quantity == 1200
    assert result.return_recommended is True


def test_overflow_and_silk_parameters_do_not_change_return_safe_inventory():
    event = active_event(
        negative_start_time=CURRENT_TIME - timedelta(minutes=25)
    )

    def evaluate(overflow_lead, silk_clear):
        return ReturnEvaluator().evaluate_algorithm(
            snapshot=algorithm_snapshot(
                active_cutline_events=[event],
                stockout_warning_lead_minutes=30,
                overflow_warning_lead_minutes=overflow_lead,
                silk_screen_clear_minutes=silk_clear,
            ),
            interval_results=[interval(net_consumption_rate=-4800)],
        )[0]

    first = evaluate(5, 10)
    second = evaluate(120, 180)

    assert first.safe_inventory_quantity == 2400
    assert second.safe_inventory_quantity == 2400
    assert first.return_recommended == second.return_recommended


def test_algorithm_return_result_exposes_stockout_warning_lead_field():
    assert "stockout_warning_lead_minutes" in AlgorithmReturnResult.model_fields


@pytest.mark.parametrize(
    ("net_rate", "duration", "quantity", "expected_reason"),
    [
        (0, 25, 5000, "net_rate_not_negative"),
        (-4800, 20, 5000, "stability_window_not_met"),
        (-4800, 25, 2400, "inventory_not_above_safe_level"),
        (-4800, 25, 2401, "all_return_conditions_met"),
    ],
)
def test_return_recommendation_requires_all_three_conditions(
    net_rate,
    duration,
    quantity,
    expected_reason,
):
    result = _evaluate(
        event=active_event(
            negative_start_time=CURRENT_TIME - timedelta(minutes=duration)
        ),
        intervals=[
            interval(
                net_consumption_rate=net_rate,
                current_quantity=quantity,
            )
        ],
    )[0]

    expected = expected_reason == "all_return_conditions_met"
    assert result.return_recommended is expected
    assert result.reason == expected_reason


def test_evaluation_does_not_mutate_snapshot_event_or_interval():
    event = active_event()
    target_interval = interval()
    snapshot = algorithm_snapshot(active_cutline_events=[event])
    before = (
        snapshot.model_dump(),
        event.model_dump(),
        target_interval.model_dump(),
    )

    result = ReturnEvaluator().evaluate_algorithm(
        snapshot=snapshot,
        interval_results=[target_interval],
    )[0]

    assert snapshot.model_dump() == before[0]
    assert event.model_dump() == before[1]
    assert target_interval.model_dump() == before[2]


def test_return_result_does_not_embed_duplicate_updated_event_state():
    assert "updated_event" not in AlgorithmReturnResult.model_fields


def test_negative_timer_resets_and_restarts_across_six_rounds():
    evaluator = ReturnEvaluator()
    event = active_event(
        cutline_start_time=datetime(2026, 7, 15, 9, 0),
        negative_start_time=None,
    )

    def run(at_time, net_rate, current_event, quantity=5000):
        return evaluator.evaluate_algorithm(
            snapshot=algorithm_snapshot(
                current_time=at_time,
                active_cutline_events=[current_event],
            ),
            interval_results=[
                interval(
                    net_consumption_rate=net_rate,
                    current_quantity=quantity,
                )
            ],
        )[0]

    first = run(datetime(2026, 7, 15, 10, 0), -1000, event)
    assert first.updated_negative_start_time == datetime(2026, 7, 15, 10, 0)
    assert first.negative_duration_minutes == 0

    second_event = _next_event(event, first)
    second = run(
        datetime(2026, 7, 15, 10, 10),
        -800,
        second_event,
    )
    assert second.updated_negative_start_time == datetime(2026, 7, 15, 10, 0)
    assert second.negative_duration_minutes == 10

    third_event = _next_event(second_event, second)
    third = run(
        datetime(2026, 7, 15, 10, 15),
        200,
        third_event,
    )
    assert third.updated_negative_start_time is None
    assert third.negative_duration_minutes == 0

    fourth_event = _next_event(third_event, third)
    fourth = run(
        datetime(2026, 7, 15, 10, 20),
        -500,
        fourth_event,
    )
    assert fourth.updated_negative_start_time == datetime(2026, 7, 15, 10, 20)
    assert fourth.negative_duration_minutes == 0

    fifth_event = _next_event(fourth_event, fourth)
    fifth = run(
        datetime(2026, 7, 15, 10, 40),
        -700,
        fifth_event,
    )
    assert fifth.negative_duration_minutes == 20
    assert fifth.condition_stability_met is False

    sixth_event = _next_event(fifth_event, fifth)
    sixth = run(
        datetime(2026, 7, 15, 10, 45),
        -700,
        sixth_event,
        quantity=1000,
    )
    assert sixth.negative_duration_minutes == 25
    assert sixth.condition_stability_met is True
    assert sixth.return_recommended is True
    assert sixth.updated_status == "return_recommended"
