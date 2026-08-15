import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.backend_request_schema import (
    BackendAgvRelation,
    BackendAlgorithmRequest,
    BackendBufferMaster,
    BackendBufferRealtime,
    BackendLine,
    BackendMachineLine,
    BackendMachineMaster,
    BackendMachineProcessTime,
    BackendMachineRealtime,
    BackendOrder,
    BackendProcessRoute,
    BackendProduct,
    BackendSnapshotMeta,
    BackendWorkshop,
)


SAMPLE_PATH = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "backend_ingestion_request_sample.json"
)

PUBLIC_MODELS = [
    BackendSnapshotMeta,
    BackendMachineRealtime,
    BackendMachineMaster,
    BackendMachineProcessTime,
    BackendWorkshop,
    BackendLine,
    BackendMachineLine,
    BackendOrder,
    BackendProduct,
    BackendProcessRoute,
    BackendBufferRealtime,
    BackendBufferMaster,
    BackendAgvRelation,
    BackendAlgorithmRequest,
]


def sample_payload() -> dict:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


def test_complete_request_parses_datetimes_and_numeric_types():
    request = BackendAlgorithmRequest.model_validate(sample_payload())

    assert isinstance(request.snapshot_meta.snapshot_time, datetime)
    assert isinstance(request.snapshot_meta.catalog_loaded_at, datetime)
    assert request.machine_realtime[0].tangent_time is None
    assert request.machine_realtime[0].input_quantity == 12.0
    assert request.machine_realtime[0].output_quantity == 10.5
    assert request.machine_process_times[0].proc_seconds == 90.0


def test_backend_machine_realtime_only_exposes_sourced_quantity_fields():
    fields = BackendMachineRealtime.model_fields

    assert {"input_quantity", "output_quantity"} <= fields.keys()
    assert {"completed_quantity", "period_quantity"}.isdisjoint(fields)


def test_all_public_models_forbid_unknown_fields():
    assert all(
        model.model_config.get("extra") == "forbid" for model in PUBLIC_MODELS
    )


def test_unknown_top_level_field_is_rejected():
    payload = sample_payload()
    payload["unexpected"] = True

    with pytest.raises(ValidationError) as error:
        BackendAlgorithmRequest.model_validate(payload)

    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_unknown_nested_field_is_rejected():
    payload = sample_payload()
    payload["machine_realtime"][0]["equipment_code"] = "legacy"

    with pytest.raises(ValidationError) as error:
        BackendAlgorithmRequest.model_validate(payload)

    assert error.value.errors()[0]["loc"] == (
        "machine_realtime",
        0,
        "equipment_code",
    )


def test_missing_top_level_dataset_is_rejected_but_empty_dataset_is_structural():
    missing = sample_payload()
    del missing["orders"]

    with pytest.raises(ValidationError) as error:
        BackendAlgorithmRequest.model_validate(missing)

    assert error.value.errors()[0]["loc"] == ("orders",)

    empty = sample_payload()
    empty["orders"] = []
    assert BackendAlgorithmRequest.model_validate(empty).orders == []


def test_optional_line_collections_default_to_independent_empty_lists():
    first_payload = sample_payload()
    first_payload.pop("lines", None)
    first_payload.pop("machine_lines", None)
    second_payload = sample_payload()
    second_payload.pop("lines", None)
    second_payload.pop("machine_lines", None)

    first = BackendAlgorithmRequest.model_validate(first_payload)
    second = BackendAlgorithmRequest.model_validate(second_payload)

    assert first.lines == []
    assert first.machine_lines == []
    assert first.lines is not second.lines
    assert first.machine_lines is not second.machine_lines
    assert BackendAlgorithmRequest.model_fields["lines"].default_factory is list
    assert (
        BackendAlgorithmRequest.model_fields["machine_lines"].default_factory
        is list
    )


def test_persistence_collections_parse_and_default_independently():
    first_payload = sample_payload()
    first_payload["active_cutline_events"] = [
        {
            "event_id": "EVENT-001",
            "plan_id": "PLAN-001",
            "warning_id": "WARNING-001",
            "machine_code": "MC-001",
            "source_order_code": "ORD-001",
            "target_order_code": "ORD-002",
            "workshop_code": "S1",
            "target_buffer_code": "BUF-001",
            "upstream_process_code": "PROC-01",
            "downstream_process_code": "PROC-02",
            "target_wafer_size": "182",
            "target_wafer_spec": "N",
            "cutline_start_time": "2026-07-14T08:00:00+08:00",
            "negative_start_time": None,
            "status": "return_recommended",
        }
    ]
    first_payload["return_suggested_event_ids"] = ["EVENT-001"]
    first_payload["mixed_cutline_event_ids"] = ["EVENT-OLDER"]

    first = BackendAlgorithmRequest.model_validate(first_payload)
    second = BackendAlgorithmRequest.model_validate(sample_payload())

    assert first.active_cutline_events[0].warning_id == "WARNING-001"
    assert first.active_cutline_events[0].status == "return_recommended"
    assert first.return_suggested_event_ids == ["EVENT-001"]
    assert first.mixed_cutline_event_ids == ["EVENT-OLDER"]
    assert second.active_cutline_events == []
    assert second.return_suggested_event_ids == []
    assert second.mixed_cutline_event_ids == []
    assert second.active_cutline_events is not first.active_cutline_events


def test_backend_active_event_rejects_blank_warning_id():
    payload = sample_payload()
    payload["active_cutline_events"] = [
        {
            "event_id": "EVENT-001",
            "warning_id": "   ",
            "machine_code": "MC-001",
            "source_order_code": "ORD-001",
            "target_order_code": "ORD-002",
            "workshop_code": "S1",
            "target_buffer_code": "BUF-001",
            "upstream_process_code": "PROC-01",
            "downstream_process_code": "PROC-02",
            "target_wafer_size": "182",
            "target_wafer_spec": "N",
            "cutline_start_time": "2026-07-14T08:00:00+08:00",
            "negative_start_time": None,
        }
    ]

    with pytest.raises(ValidationError, match="warning_id"):
        BackendAlgorithmRequest.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("return_suggested_event_ids", ["EVENT-1", "EVENT-1"]),
        ("mixed_cutline_event_ids", ["   "]),
    ],
)
def test_backend_rejects_invalid_persistence_watermarks(field, value):
    payload = sample_payload()
    payload[field] = value

    with pytest.raises(ValidationError, match=field):
        BackendAlgorithmRequest.model_validate(payload)


@pytest.mark.parametrize(
    ("dataset", "field"),
    [
        ("workshops", "workshop_name"),
        ("buffer_realtime", "main_id"),
    ],
)
def test_compatibility_nullable_fields_require_presence(dataset: str, field: str):
    explicit_null = sample_payload()
    explicit_null[dataset][0][field] = None
    BackendAlgorithmRequest.model_validate(explicit_null)

    missing = sample_payload()
    del missing[dataset][0][field]
    with pytest.raises(ValidationError) as error:
        BackendAlgorithmRequest.model_validate(missing)

    assert error.value.errors()[0]["type"] == "missing"


def test_tangent_time_requires_presence_and_accepts_null():
    payload = sample_payload()
    BackendAlgorithmRequest.model_validate(payload)

    del payload["machine_realtime"][0]["tangent_time"]
    with pytest.raises(ValidationError) as error:
        BackendAlgorithmRequest.model_validate(payload)

    assert error.value.errors()[0]["loc"] == (
        "machine_realtime",
        0,
        "tangent_time",
    )


def test_route_edge_fields_require_presence_and_accept_null():
    payload = sample_payload()
    request = BackendAlgorithmRequest.model_validate(payload)

    assert request.process_routes[0].upstream_process_code is None
    assert request.process_routes[-1].downstream_process_code is None

    del payload["process_routes"][0]["upstream_process_name"]
    with pytest.raises(ValidationError) as error:
        BackendAlgorithmRequest.model_validate(payload)

    assert error.value.errors()[0]["type"] == "missing"


def test_backend_process_route_allows_omitted_compatibility_loop_fields():
    payload = deepcopy(sample_payload())
    route = payload["process_routes"][0]
    del route["loop_code"]
    del route["loop_name"]

    request = BackendAlgorithmRequest.model_validate(payload)

    assert request.process_routes[0].loop_code is None
    assert request.process_routes[0].loop_name is None


@pytest.mark.parametrize(
    ("loop_code", "loop_name"),
    [
        (None, None),
        ("LEGACY-WRONG-LOOP", "legacy incorrect loop"),
    ],
)
def test_backend_process_route_compatibility_loop_fields_allow_null_and_legacy_values(
    loop_code: str | None,
    loop_name: str | None,
):
    payload = deepcopy(sample_payload())
    route = payload["process_routes"][0]
    route["loop_code"] = loop_code
    route["loop_name"] = loop_name

    request = BackendAlgorithmRequest.model_validate(payload)

    assert request.process_routes[0].loop_code == loop_code
    assert request.process_routes[0].loop_name == loop_name


@pytest.mark.parametrize("field", ["loop_code", "loop_name"])
def test_backend_buffer_loop_fields_remain_required(field: str):
    payload = deepcopy(sample_payload())
    del payload["buffer_master"][0][field]

    with pytest.raises(ValidationError) as error:
        BackendAlgorithmRequest.model_validate(payload)

    assert error.value.errors()[0]["loc"] == ("buffer_master", 0, field)
    assert error.value.errors()[0]["type"] == "missing"


@pytest.mark.parametrize(
    ("dataset", "field", "invalid_value"),
    [
        ("machine_realtime", "input_quantity", -1),
        ("machine_realtime", "output_quantity", -0.1),
        ("machine_process_times", "proc_seconds", 0),
        ("machine_process_times", "actual_capacity", 0),
        ("orders", "total_quantity", -1),
        ("orders", "produced_quantity", -1),
        ("orders", "remaining_quantity", -1),
        ("buffer_realtime", "current_quantity", -1),
        ("buffer_realtime", "current_utilization_rate", -0.1),
        ("buffer_master", "max_capacity", 0),
        ("buffer_master", "safety_low", -1),
    ],
)
def test_numeric_boundaries_are_enforced(
    dataset: str,
    field: str,
    invalid_value: float,
):
    payload = sample_payload()
    payload[dataset][0][field] = invalid_value

    with pytest.raises(ValidationError):
        BackendAlgorithmRequest.model_validate(payload)


@pytest.mark.parametrize("field", ["served_process_codes", "served_process_names"])
def test_served_process_lists_cannot_be_empty(field: str):
    payload = sample_payload()
    payload["buffer_master"][0][field] = []

    with pytest.raises(ValidationError):
        BackendAlgorithmRequest.model_validate(payload)


def test_proc_seconds_stays_in_seconds():
    request = BackendAlgorithmRequest.model_validate(sample_payload())

    assert request.machine_process_times[0].proc_seconds == 90.0


@pytest.mark.parametrize(
    "field",
    ["completed_quantity", "period_quantity", "out_time"],
)
def test_removed_or_transitional_machine_fields_are_not_in_schema(field: str):
    payload = sample_payload()
    payload["machine_realtime"][0][field] = 0

    with pytest.raises(ValidationError) as error:
        BackendAlgorithmRequest.model_validate(payload)

    assert error.value.errors()[0]["loc"] == ("machine_realtime", 0, field)
    assert error.value.errors()[0]["type"] == "extra_forbidden"
