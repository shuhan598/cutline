import json
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


@pytest.mark.parametrize(
    ("dataset", "field", "invalid_value"),
    [
        ("machine_realtime", "input_quantity", -1),
        ("machine_realtime", "output_quantity", -0.1),
        ("machine_realtime", "completed_quantity", -1),
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


@pytest.mark.parametrize("field", ["period_quantity", "out_time"])
def test_transitional_machine_fields_are_not_in_the_formal_schema(field: str):
    payload = sample_payload()
    payload["machine_realtime"][0][field] = 0

    with pytest.raises(ValidationError) as error:
        BackendAlgorithmRequest.model_validate(payload)

    assert error.value.errors()[0]["loc"] == ("machine_realtime", 0, field)
    assert error.value.errors()[0]["type"] == "extra_forbidden"
