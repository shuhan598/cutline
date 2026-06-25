import json
from datetime import datetime
from pathlib import Path

from app.core.mix_trace.mix_start_calculator import MixStartCalculator
from app.schemas.request_schema import MixTraceRequest


MIX_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_mix_trace_input.json"


def load_payload() -> dict:
    with MIX_INPUT_PATH.open(encoding="utf-8") as file:
        return json.load(file)


def load_request() -> MixTraceRequest:
    return MixTraceRequest.model_validate(load_payload())


def test_pk03_mix_start_time_and_composition():
    notification = MixStartCalculator().calculate(load_request())
    assert notification is not None
    assert notification.source_equipment_code == "pk03"
    assert notification.cut_time == datetime(2026, 6, 20, 10, 0, 0)
    assert notification.previous_product_code == "HG210R"
    assert notification.next_product_code == "HG182T"
    assert notification.mix_start_time == datetime(2026, 6, 20, 11, 12, 30)
    assert notification.mix_basket_count == 2
    assert notification.estimated_total_quantity == 240
    assert notification.product_compositions == [
        {"product_code": "HG210R", "sequence_no": 1, "estimated_quantity": 120},
        {"product_code": "HG182T", "sequence_no": 2, "estimated_quantity": 120},
    ]


def test_workshop_info_is_carried_from_cutline_event_without_changing_mix_start_time():
    payload = load_payload()
    payload["cutline_event"]["workshop_code"] = "S2"
    payload["cutline_event"]["workshop_name"] = "S2车间"
    request = MixTraceRequest.model_validate(payload)

    notification = MixStartCalculator().calculate(request)

    assert notification is not None
    assert notification.workshop_code == "S2"
    assert notification.workshop_name == "S2车间"
    assert notification.mix_start_time == datetime(2026, 6, 20, 11, 12, 30)


def test_workshop_info_defaults_to_none_when_cutline_event_omits_it():
    notification = MixStartCalculator().calculate(load_request())

    assert notification is not None
    assert notification.workshop_code is None
    assert notification.workshop_name is None


def test_status_pending_before_mix_start():
    notification = MixStartCalculator().calculate(load_request())
    assert notification.status == "pending"


def test_status_arrived_when_current_time_at_or_after_mix_start():
    request = load_request().model_copy(update={"current_time": datetime(2026, 6, 20, 11, 12, 30)})
    notification = MixStartCalculator().calculate(request)
    assert notification.status == "arrived"


def test_returns_none_when_capacity_record_missing():
    request = load_request().model_copy(update={"capacity_records": []})
    assert MixStartCalculator().calculate(request) is None


def test_returns_none_when_capacity_not_positive():
    request = load_request()
    zeroed = request.capacity_records[0].model_copy(update={"actual_capacity_per_hour": 0})
    request = request.model_copy(update={"capacity_records": [zeroed]})
    assert MixStartCalculator().calculate(request) is None
