import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.adapters.backend_request_loader import (
    BackendRequestLoadError,
    BackendRequestLoader,
)
from app.schemas.backend_request_schema import BackendAlgorithmRequest


SAMPLE_PATH = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "backend_ingestion_request_sample.json"
)


def sample_payload() -> dict:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


def test_load_dict_returns_model_without_mutating_nested_payload():
    payload = sample_payload()
    payload["machine_realtime"][0]["period_quantity"] = 10
    payload["machine_realtime"][0]["out_time"] = "2026-07-14T08:30:00+08:00"
    original = deepcopy(payload)

    request = BackendRequestLoader().load_dict(payload)

    assert isinstance(request, BackendAlgorithmRequest)
    assert payload == original
    assert "period_quantity" not in request.machine_realtime[0].model_fields_set
    assert "out_time" not in request.machine_realtime[0].model_fields_set


def test_transitional_cleanup_only_applies_to_machine_realtime_records():
    payload = sample_payload()
    payload["machine_realtime"][0]["period_quantity"] = 10
    payload["machine_master"][0]["period_quantity"] = 10

    with pytest.raises(ValidationError) as error:
        BackendRequestLoader().load_dict(payload)

    assert error.value.errors()[0]["loc"] == (
        "machine_master",
        0,
        "period_quantity",
    )


def test_other_unknown_machine_realtime_fields_are_still_rejected():
    payload = sample_payload()
    payload["machine_realtime"][0]["legacy_field"] = "value"

    with pytest.raises(ValidationError) as error:
        BackendRequestLoader().load_dict(payload)

    assert error.value.errors()[0]["loc"] == (
        "machine_realtime",
        0,
        "legacy_field",
    )


def test_load_json_file_reads_utf8_json(tmp_path: Path):
    path = tmp_path / "请求.json"
    path.write_text(
        json.dumps(sample_payload(), ensure_ascii=False),
        encoding="utf-8",
    )

    request = BackendRequestLoader().load_json_file(path)

    assert request.workshops[0].workshop_name == "S2车间"


def test_load_json_file_wraps_file_and_syntax_errors(tmp_path: Path):
    missing = tmp_path / "missing.json"

    with pytest.raises(BackendRequestLoadError, match="missing.json"):
        BackendRequestLoader().load_json_file(missing)

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not json", encoding="utf-8")

    with pytest.raises(BackendRequestLoadError, match="invalid.json"):
        BackendRequestLoader().load_json_file(invalid)


def test_load_json_file_propagates_schema_validation_errors(tmp_path: Path):
    payload = sample_payload()
    del payload["orders"]
    path = tmp_path / "schema-invalid.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError):
        BackendRequestLoader().load_json_file(path)


def test_non_object_json_root_is_schema_validation_error(tmp_path: Path):
    path = tmp_path / "array.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValidationError):
        BackendRequestLoader().load_json_file(path)
