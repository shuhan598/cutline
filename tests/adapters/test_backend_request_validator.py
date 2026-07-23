import json
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest

from app.adapters.backend_request_loader import BackendRequestLoader
from app.adapters.backend_request_validator import (
    BackendRequestCompletenessValidator,
    BackendRequestValidationResult,
)


ROOT = Path(__file__).resolve().parents[2]
SAMPLE_PATH = ROOT / "examples" / "backend_ingestion_request_sample.json"
REAL_SHAPE_PATH = ROOT / "docs" / "algo-request.json"


def sample_payload() -> dict:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


def validate_payload(payload: dict) -> BackendRequestValidationResult:
    request = BackendRequestLoader().load_dict(payload)
    return BackendRequestCompletenessValidator().validate(request)


def issue_counts(result: BackendRequestValidationResult) -> Counter:
    return Counter(issue.code for issue in result.issues)


def test_closed_sample_is_complete():
    result = validate_payload(sample_payload())

    assert result.valid is True
    assert result.issues == []


@pytest.mark.parametrize(
    "dataset",
    [
        "machine_realtime",
        "machine_master",
        "machine_process_times",
        "workshops",
        "orders",
        "products",
        "process_routes",
        "buffer_realtime",
        "buffer_master",
    ],
)
def test_required_empty_dataset_is_reported(dataset: str):
    payload = sample_payload()
    payload[dataset] = []

    result = validate_payload(payload)

    assert result.valid is False
    assert any(
        issue.code == "empty_dataset"
        and issue.dataset == dataset
        and issue.field is None
        for issue in result.issues
    )


@pytest.mark.parametrize(
    ("dataset", "field"),
    [
        ("workshops", "workshop_name"),
        ("buffer_realtime", "main_id"),
    ],
)
def test_required_nullable_business_fields_report_null(dataset: str, field: str):
    payload = sample_payload()
    payload[dataset][0][field] = None

    result = validate_payload(payload)

    assert any(
        issue.code == "null_field"
        and issue.dataset == dataset
        and issue.field == field
        for issue in result.issues
    )

@pytest.mark.parametrize(
    ("dataset", "field", "target_dataset"),
    [
        ("machine_realtime", "machine_code", "machine_master"),
        ("orders", "product_code", "products"),
        ("orders", "workshop_code", "workshops"),
        ("machine_process_times", "machine_code", "machine_master"),
        ("machine_process_times", "product_code", "products"),
        ("buffer_realtime", "buffer_code", "buffer_master"),
    ],
)
def test_missing_references_are_reported(
    dataset: str,
    field: str,
    target_dataset: str,
):
    payload = sample_payload()
    payload[target_dataset] = []

    result = validate_payload(payload)

    assert any(
        issue.code == "missing_reference"
        and issue.dataset == dataset
        and issue.field == field
        for issue in result.issues
    )


def test_process_route_sequence_is_unique_within_workshop_and_loop():
    payload = sample_payload()
    payload["process_routes"][1]["sequence"] = 1

    result = validate_payload(payload)

    assert any(
        issue.code == "duplicate_sequence"
        and issue.dataset == "process_routes"
        and issue.field == "sequence"
        for issue in result.issues
    )


def test_non_edge_route_null_and_unknown_neighbors_are_reported():
    payload = sample_payload()
    middle = deepcopy(payload["process_routes"][0])
    middle.update(
        {
            "process_code": "P-MID",
            "process_name": "中间工序",
            "sequence": 2,
            "upstream_process_code": None,
            "upstream_process_name": None,
            "downstream_process_code": "P-UNKNOWN",
            "downstream_process_name": "未知",
        }
    )
    payload["process_routes"][1]["sequence"] = 3
    payload["process_routes"].insert(1, middle)

    result = validate_payload(payload)

    assert any(
        issue.code == "null_field"
        and issue.dataset == "process_routes"
        and issue.field == "upstream_process_code"
        for issue in result.issues
    )
    assert any(
        issue.code == "missing_reference"
        and issue.dataset == "process_routes"
        and issue.field == "downstream_process_code"
        for issue in result.issues
    )


def test_served_process_code_must_exist_in_same_loop():
    payload = sample_payload()
    payload["buffer_master"][0]["served_process_codes"][1] = "P-UNKNOWN"

    result = validate_payload(payload)

    assert any(
        issue.code == "missing_reference"
        and issue.dataset == "buffer_master"
        and issue.field == "served_process_codes[1]"
        for issue in result.issues
    )


def test_real_api_sample_loads_but_reports_incomplete_inputs():
    payload = json.loads(REAL_SHAPE_PATH.read_text(encoding="utf-8"))

    request = BackendRequestLoader().load_dict(payload)
    result = BackendRequestCompletenessValidator().validate(request)

    assert len(request.machine_realtime) == 439
    assert result.valid is False
    assert issue_counts(result) == {
        "empty_dataset": 6,
        "null_field": 2,
        "missing_reference": 440,
        "missing_agv_binding": 138,
    }


def test_backend_request_symbols_are_available_from_package_exports():
    from app.adapters import (
        BackendRequestCompletenessValidator as ExportedValidator,
    )
    from app.adapters import BackendRequestLoader as ExportedLoader
    from app.schemas import BackendAlgorithmRequest as ExportedRequest

    assert ExportedLoader is BackendRequestLoader
    assert ExportedValidator is BackendRequestCompletenessValidator
    assert ExportedRequest.__name__ == "BackendAlgorithmRequest"
