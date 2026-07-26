from copy import deepcopy
from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.request_schema import CutlineAlgorithmRequest


DATASET_FIELDS = (
    "machine_realtime",
    "machine_master",
    "machine_process_times",
    "workshops",
    "lines",
    "machine_lines",
    "orders",
    "products",
    "process_routes",
    "buffer_realtime",
    "buffer_master",
    "agv_relations",
)


def active_cutline_event_payload():
    return {
        "event_id": "CUT-PLAN-1-M1",
        "machine_code": "M1",
        "source_order_code": "ORD-A",
        "target_order_code": "ORD-B",
        "workshop_code": "S1",
        "target_buffer_code": "BUF-B",
        "upstream_process_code": "P1",
        "downstream_process_code": "P2",
        "target_wafer_size": "182",
        "target_wafer_spec": "R",
        "cutline_start_time": "2026-07-16T12:00:00Z",
        "negative_start_time": None,
    }


@pytest.fixture
def payload():
    return {
        "snapshot_meta": {
            "run_id": "run-1", "trigger_type": "manual", "workshop_id": "S1",
            "snapshot_time": "2026-07-13T16:21:55Z", "params_version": 3,
            "catalog_version": "foundation", "catalog_loaded_at": "2026-07-13T16:21:23Z",
            "degraded_flags": [],
        },
        "machine_realtime": [{
            "machine_code": "M1", "status": "运行", "tangent_time": None,
            "input_quantity": 0, "output_quantity": 1, "completed_quantity": 0,
            "period_quantity": 2, "out_time": "2026-07-13T08:00Z",
        }],
        "machine_master": [{"machine_code": "M1", "machine_name": "机台1", "process_code": "P1", "process_name": "工序1"}],
        "machine_process_times": [{"machine_code": "M1", "machine_name": "机台1", "product_code": "PR1", "product_name": "产品1", "proc_seconds": 1, "actual_capacity": 1}],
        "workshops": [{"workshop_code": "S1", "workshop_name": None}],
        "lines": [{"line_code": "L1", "line_name": "产线1", "wafer_spec": "182", "workshop_code": "S1", "workshop_name": "车间1"}],
        "machine_lines": [{"machine_code": "M1", "machine_name": "机台1", "line_code": "L1", "line_name": "产线1", "wafer_spec": "182"}],
        "orders": [{"order_code": "O1", "order_name": "source", "order_status": "open", "total_quantity": 10, "piece_source": "A", "estimated_yield": "99%", "product_code": "PR1", "product_name": "产品1", "workshop_code": "S1", "workshop_name": "车间1", "produced_quantity": 1, "remaining_quantity": 9}],
        "products": [{"product_code": "PR1", "product_name": "产品1", "wafer_size": "182", "source_grade": "A", "material_code": "MAT1", "material_name": "物料1"}],
        "process_routes": [{"process_code": "P1", "process_name": "工序1", "sequence": 1, "cache_type": "BUFFER", "workshop_code": "S1", "workshop_name": "车间1", "loop_code": "LOOP1", "loop_name": "循环1", "upstream_process_code": None, "upstream_process_name": None, "downstream_process_code": None, "downstream_process_name": None}],
        "buffer_realtime": [{"main_id": None, "buffer_code": "B1", "bound_source_name": "source", "current_quantity": 0, "current_utilization_rate": 0}],
        "buffer_master": [{"buffer_code": "B1", "buffer_name": "缓存1", "buffer_type": "LINE", "buffer_type_title": "线边库", "max_capacity": 1, "safety_low": 0, "served_process_codes": [], "served_process_names": [], "loop_code": "LOOP1", "loop_name": "循环1"}],
        "agv_relations": [{"machine_code": "M1", "machine_name": "机台1", "order_code": "O1", "order_name": "source", "wafer_spec": "N", "binding_time": "2026-07-13T16:20:00Z"}],
    }


def test_minimal_complete_request_parses_required_values(payload):
    request = CutlineAlgorithmRequest.model_validate(payload)
    assert request.machine_realtime[0].period_quantity == 2
    assert isinstance(request.machine_realtime[0].out_time, datetime)
    assert request.workshops[0].workshop_name is None
    assert request.buffer_realtime[0].main_id is None
    assert request.active_cutline_events == []


def test_request_active_cutline_event_defaults_are_independent(payload):
    first = CutlineAlgorithmRequest.model_validate(payload)
    second = CutlineAlgorithmRequest.model_validate(deepcopy(payload))

    assert first.active_cutline_events is not second.active_cutline_events
    assert CutlineAlgorithmRequest.model_fields[
        "active_cutline_events"
    ].default_factory is list


def test_request_accepts_existing_active_cutline_events(payload):
    payload["active_cutline_events"] = [active_cutline_event_payload()]

    request = CutlineAlgorithmRequest.model_validate(payload)

    event = request.active_cutline_events[0]
    assert event.event_id == "CUT-PLAN-1-M1"
    assert event.negative_start_time is None
    assert set(event.model_fields) == {
        "event_id",
        "machine_code",
        "source_order_code",
        "target_order_code",
        "workshop_code",
        "target_buffer_code",
        "upstream_process_code",
        "downstream_process_code",
        "target_wafer_size",
        "target_wafer_spec",
        "cutline_start_time",
        "negative_start_time",
    }
    assert "status" not in event.model_fields


@pytest.mark.parametrize(
    "removed_field",
    (
        "plan_id",
        "source_buffer_code",
        "source_wafer_size",
        "source_wafer_spec",
        "contribution_capacity",
        "warning_type",
        "status",
        "return_recommended_time",
    ),
)
def test_request_active_event_rejects_removed_backend_fields(
    payload,
    removed_field,
):
    event = active_cutline_event_payload()
    event[removed_field] = "obsolete"
    payload["active_cutline_events"] = [event]

    with pytest.raises(ValidationError) as error:
        CutlineAlgorithmRequest.model_validate(payload)

    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_request_active_event_requires_explicit_negative_start_time(payload):
    event = active_cutline_event_payload()
    del event["negative_start_time"]
    payload["active_cutline_events"] = [event]

    with pytest.raises(ValidationError) as error:
        CutlineAlgorithmRequest.model_validate(payload)

    assert error.value.errors()[0]["type"] == "missing"


def test_request_has_no_config_field(payload):
    assert "config" not in CutlineAlgorithmRequest.model_fields

    payload["config"] = {}
    with pytest.raises(ValidationError) as error:
        CutlineAlgorithmRequest.model_validate(payload)

    assert error.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize("missing_field", ("snapshot_meta", *DATASET_FIELDS))
def test_every_top_level_field_is_required(payload, missing_field):
    del payload[missing_field]
    with pytest.raises(ValidationError):
        CutlineAlgorithmRequest.model_validate(payload)


def test_nested_required_field_is_required(payload):
    del payload["machine_realtime"][0]["period_quantity"]
    with pytest.raises(ValidationError):
        CutlineAlgorithmRequest.model_validate(payload)


@pytest.mark.parametrize("location", ("top", "nested"))
def test_unknown_fields_are_rejected(payload, location):
    target = payload if location == "top" else payload["machine_realtime"][0]
    target["unexpected"] = True
    with pytest.raises(ValidationError):
        CutlineAlgorithmRequest.model_validate(payload)


@pytest.mark.parametrize(
    ("dataset", "field"),
    (("machine_realtime", "tangent_time"), ("workshops", "workshop_name"),
     ("buffer_realtime", "main_id"), ("process_routes", "upstream_process_code"),
     ("process_routes", "upstream_process_name"), ("process_routes", "downstream_process_code"),
     ("process_routes", "downstream_process_name")),
)
def test_nullable_required_fields_accept_null(payload, dataset, field):
    assert payload[dataset][0][field] is None
    CutlineAlgorithmRequest.model_validate(payload)
    del payload[dataset][0][field]
    with pytest.raises(ValidationError):
        CutlineAlgorithmRequest.model_validate(payload)


@pytest.mark.parametrize(
    ("dataset", "field", "value"),
    (("machine_realtime", "input_quantity", -1), ("machine_realtime", "output_quantity", -1),
     ("machine_realtime", "input_quantity", True), ("machine_realtime", "output_quantity", True),
     ("machine_realtime", "completed_quantity", -1), ("machine_realtime", "period_quantity", -1),
     ("machine_process_times", "actual_capacity", 0),
     ("orders", "total_quantity", -1), ("orders", "produced_quantity", -1),
     ("orders", "remaining_quantity", -1), ("buffer_realtime", "current_quantity", -1),
     ("buffer_realtime", "current_utilization_rate", -1), ("buffer_master", "max_capacity", 0),
     ("buffer_master", "safety_low", -1)),
)
def test_numeric_constraints_reject_invalid_values(payload, dataset, field, value):
    payload[dataset][0][field] = value
    with pytest.raises(ValidationError):
        CutlineAlgorithmRequest.model_validate(payload)


def test_machine_process_time_allows_zero_proc_seconds(payload):
    payload["machine_process_times"][0]["proc_seconds"] = 0

    request = CutlineAlgorithmRequest.model_validate(payload)

    assert request.machine_process_times[0].proc_seconds == 0


def test_explicit_empty_top_level_arrays_are_allowed(payload):
    for field in DATASET_FIELDS:
        payload[field] = []
    request = CutlineAlgorithmRequest.model_validate(payload)
    assert all(getattr(request, field) == [] for field in DATASET_FIELDS)


def test_machine_realtime_does_not_expose_order_code(payload):
    request = CutlineAlgorithmRequest.model_validate(payload)
    assert "order_code" not in request.machine_realtime[0].__class__.model_fields


def test_order_name_is_required_and_non_nullable_on_request_model(payload):
    request = CutlineAlgorithmRequest.model_validate(payload)
    assert request.orders[0].order_name == "source"

    del payload["orders"][0]["order_name"]
    with pytest.raises(ValidationError) as missing_error:
        CutlineAlgorithmRequest.model_validate(payload)
    assert missing_error.value.errors()[0]["loc"] == ("orders", 0, "order_name")
    assert missing_error.value.errors()[0]["type"] == "missing"

    payload["orders"][0]["order_name"] = None
    with pytest.raises(ValidationError) as null_error:
        CutlineAlgorithmRequest.model_validate(payload)
    assert null_error.value.errors()[0]["loc"] == ("orders", 0, "order_name")

def test_order_request_still_forbids_unknown_fields(payload):
    payload["orders"][0]["unexpected"] = True
    with pytest.raises(ValidationError) as error:
        CutlineAlgorithmRequest.model_validate(payload)

    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_product_rejects_shape_code(payload):
    payload["products"][0]["shape_code"] = "R"
    with pytest.raises(ValidationError):
        CutlineAlgorithmRequest.model_validate(payload)

