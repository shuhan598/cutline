from copy import deepcopy

from app.schemas.response_schema import CutlineAlgorithmResponse
from tests.fixtures.v3_full_route_factory import (
    TARGET_BUFFER_CODE,
    build_return_round_1_payload,
    build_return_round_2_payload,
)
from tests.integration.helpers import evaluate, inventory, runtime
from tests.integration.helpers import response_buffer_codes


def _persisted_event(event) -> dict:
    return event.model_dump(mode="json")


def _confirmed_event() -> tuple[CutlineAlgorithmResponse, dict]:
    response = evaluate(build_return_round_2_payload())
    assert len(response.new_active_cutline_events) == 1
    return response, _persisted_event(response.new_active_cutline_events[0])


def _return_payload(event: dict, at_time: str) -> dict:
    payload = build_return_round_2_payload()
    payload["snapshot_meta"]["snapshot_time"] = at_time
    payload["pending_cutline_plans"] = []
    payload["active_cutline_events"] = [deepcopy(event)]
    return payload


def test_v3_return_event_lifecycle_closes_after_strict_window_and_stays_closed():
    first = evaluate(build_return_round_1_payload())
    assert first.new_active_cutline_events == []
    assert first.return_recommendations == []
    assert first.closed_active_cutline_event_ids == []

    confirmed, event = _confirmed_event()
    assert event["cutline_start_time"] == "2026-07-17T08:03:00+08:00"
    assert event["negative_start_time"] == (
        "2026-07-17T08:05:00+08:00"
    )
    assert confirmed.return_recommendations == []
    assert confirmed.updated_active_cutline_events == []
    assert confirmed.closed_active_cutline_event_ids == []

    equal_payload = _return_payload(event, "2026-07-17T08:25:00+08:00")
    inventory(equal_payload, TARGET_BUFFER_CODE, "182N至上产品")[
        "current_quantity"
    ] = 1000
    third = evaluate(equal_payload)
    assert third.return_recommendations == []
    assert third.closed_active_cutline_event_ids == []
    assert third.updated_active_cutline_events == []

    later_payload = _return_payload(event, "2026-07-17T08:26:00+08:00")
    inventory(later_payload, TARGET_BUFFER_CODE, "182N至上产品")[
        "current_quantity"
    ] = 1000
    fourth = evaluate(later_payload)
    assert [item.event_id for item in fourth.return_recommendations] == [
        event["event_id"]
    ]
    assert fourth.closed_active_cutline_event_ids == [event["event_id"]]
    assert fourth.updated_active_cutline_events == []
    assert fourth.return_recommendations[0].model_dump().keys() == {
        "event_id",
        "machine_code",
        "source_order_code",
        "target_order_code",
        "return_recommended_time",
    }

    fifth_payload = _return_payload(event, "2026-07-17T08:31:00+08:00")
    fifth_payload["active_cutline_events"] = []
    fifth = evaluate(fifth_payload)
    assert fifth.return_recommendations == []
    assert fifth.closed_active_cutline_event_ids == []
    assert fifth.updated_active_cutline_events == []


def test_v3_return_nonnegative_rate_clears_timer_with_explicit_null():
    _, event = _confirmed_event()
    payload = _return_payload(event, "2026-07-17T08:06:00+08:00")
    runtime(payload, "EA003")["output_quantity"] = 0
    runtime(payload, "EA004")["output_quantity"] = 0

    response = evaluate(payload)

    assert response.return_recommendations == []
    assert response.closed_active_cutline_event_ids == []
    assert response.updated_active_cutline_events[0].model_dump(mode="json") == {
        "event_id": event["event_id"],
        "negative_start_time": None,
    }
    assert "negative_start_time" in response.model_dump(mode="json")[
        "updated_active_cutline_events"
    ][0]


def test_v3_return_missing_target_interval_reports_error_without_closing_event():
    _, event = _confirmed_event()
    payload = _return_payload(event, "2026-07-17T08:06:00+08:00")
    payload["buffer_realtime"] = [
        item
        for item in payload["buffer_realtime"]
        if item["buffer_code"] != TARGET_BUFFER_CODE
    ]

    response = evaluate(payload)

    assert response.return_recommendations == []
    assert response.closed_active_cutline_event_ids == []
    assert response.updated_active_cutline_events == []
    assert any(
        item.stage == "return_evaluation"
        and item.reason == "target_interval_not_found"
        for item in response.errors
    )


def test_v3_return_response_preserves_event_numeric_buffer_codes():
    first, event = _confirmed_event()
    payload = _return_payload(event, "2026-07-17T08:06:00+08:00")
    input_codes = {item["buffer_code"] for item in payload["buffer_master"]}

    new_event_codes = response_buffer_codes(first.new_active_cutline_events)
    update_codes = response_buffer_codes(
        evaluate(payload).updated_active_cutline_events
    )

    assert new_event_codes == [TARGET_BUFFER_CODE]
    assert all(code in input_codes and code.isdigit() for code in new_event_codes)
    assert update_codes == []
