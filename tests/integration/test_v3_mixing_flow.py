from datetime import datetime

from tests.fixtures.v3_full_route_factory import (
    build_mixing_failure_payload,
    build_stockout_auto_payload,
)
from tests.integration.helpers import evaluate


def test_v3_mixing_success_uses_realtime_capacity_residual_agv_and_process_time():
    response = evaluate(build_stockout_auto_payload())

    plan = response.cutline_decisions[0].plan
    assert plan is not None
    record = response.mixing_trace_records[0]
    assert record.machine_code == "EA004"
    assert record.mix_start_time == datetime.fromisoformat(
        "2026-07-17T10:07:00+08:00"
    )
    assert record.mixed_basket_start_index == 1
    assert record.mixed_basket_end_index == 10
    assert record.estimated_total_mixed_pieces == 1200
    assert [item.estimated_pieces for item in record.compositions] == [600, 600]
    assert record.notification_status == "scheduled"
    assert record.cutline_event_id == response.new_active_cutline_events[0].event_id


def test_v3_mixing_failure_does_not_remove_plan_event_and_enters_errors_once():
    response = evaluate(build_mixing_failure_payload())

    assert response.cutline_decisions[0].plan is not None
    assert [item.machine_code for item in response.new_active_cutline_events] == [
        "EA004",
        "EA023",
    ]
    assert [item.machine_code for item in response.mixing_trace_records] == [
        "EA023"
    ]
    assert "mixing_trace_failures" not in response.model_fields
    failures = [item for item in response.errors if item.stage == "mixing_trace"]
    assert len(failures) == 1
    failure = failures[0]
    assert failure.machine_code == "EA004"
    assert failure.reason == "process_duration_not_found"
    assert response.mixing_trace_records[0].cutline_event_id == (
        response.new_active_cutline_events[1].event_id
    )
    assert len(response.errors) == 1
