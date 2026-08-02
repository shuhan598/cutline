from copy import deepcopy
from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.backend_request_schema import BackendAlgorithmRequest
from app.schemas.pending_cutline_schema import PendingCutlinePlan
from app.schemas.request_schema import CutlineAlgorithmRequest
from app.schemas.response_schema import ActiveCutlineEventPersistenceResponse
from app.schemas.result_schema import AlgorithmPersistenceState
from tests.core.cutline_confirmation.helpers import (
    MONITORED_ORDER,
    NOW,
    SOURCE_ORDER,
    make_active_event,
    make_stockout_plan,
)


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

REQUIRED_DATASET_FIELDS = tuple(
    field
    for field in DATASET_FIELDS
    if field not in {"lines", "machine_lines"}
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


def pending_cutline_plan_payload():
    return {
        "plan_id": "PLAN-1",
        "warning_id": "WARN-1",
        "warning_type": "stockout",
        "warning_time": "2026-07-16T11:59:00Z",
        "created_at": "2026-07-16T12:00:00Z",
        "expire_at": "2026-07-16T12:30:00Z",
        "status": "PENDING",
        "workshop_code": "S1",
        "buffer_code": "BUF-A",
        "upstream_process_code": "P1",
        "downstream_process_code": "P2",
        "monitored_order_code": "ORD-B",
        "before_machine_count": 0,
        "before_machine_codes": [],
        "expected_machine_count": 1,
        "expected_delta_direction": "increase",
    }


def backend_payload_from_request(payload):
    backend_payload = deepcopy(payload)
    backend_payload.pop("active_cutline_events", None)
    for runtime in backend_payload["machine_realtime"]:
        runtime.pop("period_quantity")
        runtime.pop("out_time")
    backend_payload["agv_relations"] = [
        {
            "equipmentid": relation["machine_code"],
            "equipmentname": relation["machine_name"],
            "linename": relation["product_name"],
            "lastlinename": relation["previous_product_name"],
            "waferspec": relation["wafer_spec"],
            "createtime": relation["binding_time"],
        }
        for relation in backend_payload["agv_relations"]
    ]
    backend_payload["buffer_master"][0]["served_process_codes"] = ["P1"]
    backend_payload["buffer_master"][0]["served_process_names"] = ["process-1"]
    return backend_payload


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
            "machine_code": "P166-M1", "status": "运行", "tangent_time": None,
            "input_quantity": 0, "output_quantity": 1, "completed_quantity": 0,
            "period_quantity": 2, "out_time": "2026-07-13T08:00Z",
        }],
        "machine_master": [{"machine_code": "M1", "p166_jt_group": "P166-M1", "machine_name": "机台1", "process_code": "P1", "process_name": "工序1"}],
        "machine_process_times": [{"machine_code": "M1", "machine_name": "机台1", "product_code": "PR1", "product_name": "产品1", "proc_seconds": 1, "actual_capacity": 1}],
        "workshops": [{"workshop_code": "S1", "workshop_name": None}],
        "lines": [{"line_code": "L1", "line_name": "产线1", "wafer_spec": "182", "workshop_code": "S1", "workshop_name": "车间1"}],
        "machine_lines": [{"machine_code": "M1", "machine_name": "机台1", "line_code": "L1", "line_name": "产线1", "wafer_spec": "182"}],
        "orders": [{"order_code": "O1", "order_status": "open", "total_quantity": 10, "piece_source": "A", "estimated_yield": "99%", "product_code": "PR1", "product_name": "产品1", "workshop_code": "S1", "workshop_name": "车间1", "produced_quantity": 1, "remaining_quantity": 9}],
        "products": [{"product_code": "PR1", "product_name": "产品1", "wafer_size": "182", "source_grade": "A", "material_code": "MAT1", "material_name": "物料1"}],
        "process_routes": [{"process_code": "P1", "process_name": "工序1", "sequence": 1, "cache_type": "BUFFER", "workshop_code": "S1", "workshop_name": "车间1", "loop_code": "LOOP1", "loop_name": "循环1", "upstream_process_code": None, "upstream_process_name": None, "downstream_process_code": None, "downstream_process_name": None}],
        "buffer_realtime": [{"main_id": None, "buffer_code": "B1", "bound_source_name": "产品1", "current_quantity": 0, "current_utilization_rate": 0}],
        "buffer_master": [{"buffer_code": "B1", "buffer_name": "缓存1", "buffer_type": "LINE", "buffer_type_title": "线边库", "max_capacity": 1, "safety_low": 0, "served_process_codes": [], "served_process_names": [], "loop_code": "LOOP1", "loop_name": "循环1"}],
        "agv_relations": [{"machine_code": "M1", "machine_name": "机台1", "product_name": "产品1", "previous_product_name": None, "wafer_spec": "N", "binding_time": "2026-07-13T16:20:00Z"}],
    }


def test_minimal_complete_request_parses_required_values(payload):
    request = CutlineAlgorithmRequest.model_validate(payload)
    assert request.machine_realtime[0].period_quantity == 2
    assert isinstance(request.machine_realtime[0].out_time, datetime)
    assert request.workshops[0].workshop_name is None
    assert request.buffer_realtime[0].main_id is None
    assert request.active_cutline_events == []
    assert request.pending_cutline_plans == []


def test_request_state_collection_defaults_are_independent(payload):
    first = CutlineAlgorithmRequest.model_validate(payload)
    second = CutlineAlgorithmRequest.model_validate(deepcopy(payload))

    assert first.active_cutline_events is not second.active_cutline_events
    assert first.pending_cutline_plans is not second.pending_cutline_plans
    assert CutlineAlgorithmRequest.model_fields[
        "active_cutline_events"
    ].default_factory is list
    assert CutlineAlgorithmRequest.model_fields[
        "pending_cutline_plans"
    ].default_factory is list
    assert first.return_suggested_event_ids is not second.return_suggested_event_ids
    assert first.mixed_cutline_event_ids is not second.mixed_cutline_event_ids


def test_request_persists_active_event_lifecycle_status_and_event_id_summaries(
    payload,
):
    event = active_cutline_event_payload()
    event["status"] = "return_recommended"
    payload.update(
        {
            "active_cutline_events": [event],
            "return_suggested_event_ids": [event["event_id"]],
            "mixed_cutline_event_ids": ["CUT-PLAN-1-M2"],
        }
    )

    request = CutlineAlgorithmRequest.model_validate(payload)

    assert request.active_cutline_events[0].status == "return_recommended"
    assert request.return_suggested_event_ids == ["CUT-PLAN-1-M1"]
    assert request.mixed_cutline_event_ids == ["CUT-PLAN-1-M2"]


def test_request_accepts_persistence_state_watermarks_and_active_event_round_trip(
    payload,
):
    active = ActiveCutlineEventPersistenceResponse(
        **active_cutline_event_payload(),
        plan_id="PLAN-1",
        status="return_recommended",
    )
    state = AlgorithmPersistenceState(
        active_cutline_events=[active.model_dump()],
        return_suggested_event_ids=[active.event_id],
        mixed_cutline_event_ids=[active.event_id],
    )
    payload.update(
        {
            "active_cutline_events": [active.model_dump()],
            "return_suggested_event_ids": state.return_suggested_event_ids,
            "mixed_cutline_event_ids": state.mixed_cutline_event_ids,
        }
    )

    request = CutlineAlgorithmRequest.model_validate(payload)

    assert request.active_cutline_events[0].plan_id == "PLAN-1"
    assert request.active_cutline_events[0].status == "return_recommended"


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("return_suggested_event_ids", ["CUT-1", "CUT-1"]),
        ("mixed_cutline_event_ids", ["CUT-1", "CUT-1"]),
        ("return_suggested_event_ids", ["   "]),
        ("mixed_cutline_event_ids", [""]),
    ],
)
def test_request_rejects_duplicate_or_blank_persisted_event_ids(
    payload, field_name, value
):
    payload[field_name] = value

    with pytest.raises(ValidationError, match=field_name):
        CutlineAlgorithmRequest.model_validate(payload)


def test_request_parses_typed_pending_cutline_plans(payload):
    payload["pending_cutline_plans"] = [pending_cutline_plan_payload()]

    request = CutlineAlgorithmRequest.model_validate(payload)

    assert isinstance(request.pending_cutline_plans[0], PendingCutlinePlan)
    assert request.pending_cutline_plans[0].plan_id == "PLAN-1"


def test_backend_request_parses_typed_pending_cutline_plans(payload):
    backend_payload = backend_payload_from_request(payload)
    backend_payload["pending_cutline_plans"] = [pending_cutline_plan_payload()]

    request = BackendAlgorithmRequest.model_validate(backend_payload)

    assert isinstance(request.pending_cutline_plans[0], PendingCutlinePlan)
    assert request.pending_cutline_plans[0].plan_id == "PLAN-1"


@pytest.mark.parametrize("schema_kind", ["cutline", "backend"])
def test_confirmed_pending_requires_matching_active_event(payload, schema_kind):
    plan = make_stockout_plan(confirmed_machine_codes=("M1",))
    payload["pending_cutline_plans"] = [plan.model_dump(mode="json")]
    if schema_kind == "backend":
        request_payload = backend_payload_from_request(payload)
        request_model = BackendAlgorithmRequest
    else:
        request_payload = payload
        request_model = CutlineAlgorithmRequest

    with pytest.raises(ValidationError) as exc_info:
        request_model.model_validate(request_payload)

    message = str(exc_info.value)
    assert plan.plan_id in message
    assert plan.warning_id in message
    assert "M1" in message
    assert "active_cutline_events" in message

    active = make_active_event(
        plan_id=plan.plan_id,
        warning_id=plan.warning_id,
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=NOW,
    )
    request_payload["active_cutline_events"] = [
        active.model_dump(mode="json")
    ]

    parsed = request_model.model_validate(request_payload)

    assert parsed.pending_cutline_plans[0].confirmed_machine_codes == ["M1"]
    assert parsed.active_cutline_events[0].warning_id == plan.warning_id


def test_backend_request_pending_plan_defaults_are_independent(payload):
    first = BackendAlgorithmRequest.model_validate(
        backend_payload_from_request(payload)
    )
    second = BackendAlgorithmRequest.model_validate(
        backend_payload_from_request(payload)
    )

    assert first.pending_cutline_plans == []
    assert first.pending_cutline_plans is not second.pending_cutline_plans
    assert BackendAlgorithmRequest.model_fields[
        "pending_cutline_plans"
    ].default_factory is list


def test_request_accepts_existing_active_cutline_events(payload):
    payload["active_cutline_events"] = [active_cutline_event_payload()]

    request = CutlineAlgorithmRequest.model_validate(payload)

    event = request.active_cutline_events[0]
    assert event.event_id == "CUT-PLAN-1-M1"
    assert event.negative_start_time is None
    assert set(type(event).model_fields) == {
        "event_id",
        "plan_id",
        "warning_id",
        "machine_code",
        "source_order_code",
        "target_order_code",
        "workshop_code",
        "source_buffer_code",
        "target_buffer_code",
        "upstream_process_code",
        "downstream_process_code",
        "source_wafer_size",
        "source_wafer_spec",
        "target_wafer_size",
        "target_wafer_spec",
        "cutline_start_time",
        "negative_start_time",
        "status",
        "contribution_capacity",
        "warning_type",
        "process_code",
        "warning_buffer_code",
        "warning_upstream_process_code",
        "warning_downstream_process_code",
        "is_recommended_candidate",
    }
    assert event.status == "active"
    assert all(
        getattr(event, field_name) is None
        for field_name in (
            "plan_id",
            "source_buffer_code",
            "source_wafer_size",
            "source_wafer_spec",
            "contribution_capacity",
            "warning_type",
            "process_code",
            "warning_buffer_code",
            "warning_upstream_process_code",
            "warning_downstream_process_code",
            "is_recommended_candidate",
        )
    )


def test_request_active_event_accepts_optional_hidden_backend_metadata(payload):
    event = active_cutline_event_payload()
    event.update(
        {
            "plan_id": "PLAN-1",
            "source_buffer_code": "BUF-A",
            "source_wafer_size": "182",
            "source_wafer_spec": "N",
            "contribution_capacity": 120.0,
            "warning_type": "stockout",
            "process_code": "P1",
            "warning_buffer_code": "BUF-WARNING",
            "warning_upstream_process_code": "P0",
            "warning_downstream_process_code": "P1",
            "is_recommended_candidate": True,
        }
    )
    payload["active_cutline_events"] = [event]

    parsed = CutlineAlgorithmRequest.model_validate(payload).active_cutline_events[0]

    assert parsed.plan_id == "PLAN-1"
    assert parsed.contribution_capacity == 120.0
    assert parsed.warning_type == "stockout"
    assert parsed.is_recommended_candidate is True


def test_request_active_event_rejects_whitespace_only_optional_plan_id(payload):
    event = active_cutline_event_payload()
    event["plan_id"] = "   "
    payload["active_cutline_events"] = [event]

    with pytest.raises(ValidationError) as error:
        CutlineAlgorithmRequest.model_validate(payload)

    assert "plan_id" in str(error.value)
    assert "blank" in str(error.value)


@pytest.mark.parametrize("removed_field", ("return_recommended_time",))
def test_request_active_event_still_rejects_internal_lifecycle_fields(
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


@pytest.mark.parametrize(
    "missing_field",
    ("snapshot_meta", *REQUIRED_DATASET_FIELDS),
)
def test_every_top_level_field_is_required(payload, missing_field):
    del payload[missing_field]
    with pytest.raises(ValidationError):
        CutlineAlgorithmRequest.model_validate(payload)


def test_optional_line_collections_default_to_independent_empty_lists(payload):
    payload.pop("lines")
    payload.pop("machine_lines")

    first = CutlineAlgorithmRequest.model_validate(payload)
    second = CutlineAlgorithmRequest.model_validate(deepcopy(payload))

    assert first.lines == []
    assert first.machine_lines == []
    assert first.lines is not second.lines
    assert first.machine_lines is not second.machine_lines
    assert (
        CutlineAlgorithmRequest.model_fields["lines"].default_factory is list
    )
    assert (
        CutlineAlgorithmRequest.model_fields[
            "machine_lines"
        ].default_factory
        is list
    )


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


def test_order_request_rejects_removed_order_name(payload):
    payload["orders"][0]["order_name"] = "旧订单名称"

    with pytest.raises(ValidationError) as error:
        CutlineAlgorithmRequest.model_validate(payload)

    assert error.value.errors()[0]["loc"] == ("orders", 0, "order_name")
    assert error.value.errors()[0]["type"] == "extra_forbidden"

def test_order_request_still_forbids_unknown_fields(payload):
    payload["orders"][0]["unexpected"] = True
    with pytest.raises(ValidationError) as error:
        CutlineAlgorithmRequest.model_validate(payload)

    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_product_rejects_shape_code(payload):
    payload["products"][0]["shape_code"] = "R"
    with pytest.raises(ValidationError):
        CutlineAlgorithmRequest.model_validate(payload)

