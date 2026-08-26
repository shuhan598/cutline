from datetime import datetime

from tests.fixtures.v3_full_route_factory import (
    build_return_round_2_payload,
)
from tests.integration.helpers import evaluate


def test_v3_mixing_success_uses_realtime_capacity_residual_agv_and_process_time():
    response = evaluate(build_return_round_2_payload())

    record = response.mixing_trace_records[0]
    assert record.machine_code == "EA004"
    assert record.mix_start_time == datetime.fromisoformat(
        "2026-07-17T10:10:00+08:00"
    )
    assert record.mixed_basket_start_index == 1
    assert record.mixed_basket_end_index == 10
    assert record.estimated_total_mixed_pieces == 1200
    assert [item.estimated_pieces for item in record.compositions] == [600, 600]
    assert record.notification_status == "scheduled"
    assert [item.event_id for item in response.new_active_cutline_events] == [
        record.cutline_event_id
    ]
    assert response.persistence_state.mixed_cutline_event_ids == [
        record.cutline_event_id
    ]
    assert response.persistence_state.new_mixing_trace_records == [record]


def test_v3_active_mixing_failure_enters_errors_once_without_watermark():
    payload = build_return_round_2_payload()
    payload["machine_process_times"] = []
    response = evaluate(payload)

    assert len(response.new_active_cutline_events) == 1
    assert response.mixing_trace_records == []
    assert "mixing_trace_failures" not in response.__class__.model_fields
    failures = [item for item in response.errors if item.stage == "mixing_trace"]
    assert len(failures) == 1
    failure = failures[0]
    assert failure.machine_code == "EA004"
    assert failure.reason == "process_duration_not_found"
    assert failure.error_code == "3111"
    assert failure.message == "混料-EA004：机台和源产品的工艺时长缺失"
    assert response.persistence_state.mixed_cutline_event_ids == []
    assert response.persistence_state.new_mixing_trace_records == []
    assert len(response.errors) == 1
