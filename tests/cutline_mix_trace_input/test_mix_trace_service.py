import json
from datetime import datetime
from pathlib import Path

from app.schemas.request_schema import MixTraceRequest
from app.service.mix_trace_service import MixTraceService


MIX_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_mix_trace_input.json"


def load_request() -> MixTraceRequest:
    with MIX_INPUT_PATH.open(encoding="utf-8") as file:
        return MixTraceRequest.model_validate(json.load(file))


def test_trace_success_returns_one_notification():
    response = MixTraceService().trace(load_request())
    assert response.success is True
    assert response.message == ""
    assert len(response.notifications) == 1
    notification = response.notifications[0]
    assert notification.source_equipment_code == "pk03"
    assert notification.mix_start_time == datetime(2026, 6, 20, 11, 12, 30)
    assert notification.status == "pending"


def test_trace_missing_capacity_returns_failure():
    request = load_request().model_copy(update={"capacity_records": []})
    response = MixTraceService().trace(request)
    assert response.success is False
    assert response.notifications == []
    assert "pk03" in response.message


def test_trace_status_arrived_after_mix_start():
    request = load_request().model_copy(update={"current_time": datetime(2026, 6, 20, 11, 30, 0)})
    response = MixTraceService().trace(request)
    assert response.success is True
    assert response.notifications[0].status == "arrived"
