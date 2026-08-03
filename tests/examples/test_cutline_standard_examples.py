import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.backend_request_loader import BackendRequestLoader
from app.adapters.backend_request_validator import (
    BackendRequestCompletenessValidator,
)
from app.adapters.snapshot_adapter import SnapshotAdapter
from app.main import create_app
from app.schemas.response_schema import CutlineEvaluateResponse
from app.utils.time_utils import normalize_local_time
from examples.generate_cutline_standard_examples import (
    localize_standard_payload,
)


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"

FIRST_ROUND_INPUT = EXAMPLES / "cutline_standard_input_first_round.json"
NEXT_ROUND_INPUT = EXAMPLES / "cutline_standard_input_next_round.json"
SUCCESS_OUTPUTS = (
    EXAMPLES / "cutline_standard_output_no_warning.json",
    EXAMPLES / "cutline_standard_output_stockout_plan.json",
    EXAMPLES / "cutline_standard_output_pending_confirmed.json",
    EXAMPLES / "cutline_standard_output_return_recommendation.json",
    EXAMPLES / "cutline_standard_output_manual_intervention.json",
)
ERROR_OUTPUTS = (
    EXAMPLES / "cutline_standard_error_backend_data_invalid.json",
    EXAMPLES / "cutline_standard_error_snapshot_conversion.json",
)
STANDARD_JSON_FILES = (
    FIRST_ROUND_INPUT,
    NEXT_ROUND_INPUT,
    *SUCCESS_OUTPUTS,
    *ERROR_OUTPUTS,
)


def _load_json(path: Path):
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def _scenario(name: str):
    return localize_standard_payload(
        _load_json(EXAMPLES / "scenarios" / f"{name}.json")
    )


@pytest.mark.parametrize("path", STANDARD_JSON_FILES, ids=lambda path: path.name)
def test_standard_example_is_valid_json(path: Path):
    _load_json(path)


@pytest.mark.parametrize("path", (FIRST_ROUND_INPUT, NEXT_ROUND_INPUT))
def test_standard_input_passes_every_pre_pipeline_stage(path: Path):
    request = BackendRequestLoader().load_cutline_dict(_load_json(path))

    validation = BackendRequestCompletenessValidator().validate(request)
    snapshot = SnapshotAdapter().to_algorithm_snapshot(request)

    assert validation.valid is True, validation.issues
    assert snapshot.current_time == request.snapshot_meta.snapshot_time


@pytest.mark.parametrize("path", (FIRST_ROUND_INPUT, NEXT_ROUND_INPUT))
def test_standard_input_runs_through_formal_api(path: Path):
    response = TestClient(
        create_app(),
        raise_server_exceptions=False,
    ).post("/cutline/evaluate", json=_load_json(path))

    assert response.status_code == 200, response.text
    CutlineEvaluateResponse.model_validate(response.json())


def test_first_round_explicitly_starts_without_cross_round_state():
    payload = _load_json(FIRST_ROUND_INPUT)

    assert payload["pending_cutline_plans"] == []
    assert payload["active_cutline_events"] == []
    assert payload["return_suggested_event_ids"] == []
    assert payload["mixed_cutline_event_ids"] == []


@pytest.mark.parametrize("path", (FIRST_ROUND_INPUT, NEXT_ROUND_INPUT))
def test_standard_input_uses_chinese_business_values(path: Path):
    payload = _load_json(path)

    assert payload["snapshot_meta"]["trigger_type"] == "手动触发"
    assert {
        route["cache_type"] for route in payload["process_routes"]
    } == {"工序缓存"}
    assert {
        buffer["buffer_type"] for buffer in payload["buffer_master"]
    } == {"工序"}
    process_names = {
        route["process_name"] for route in payload["process_routes"]
    }
    assert "多晶硅沉积" in process_names
    assert "RCA清洗" in process_names
    assert process_names.isdisjoint({"POLY", "RCA"})
    assert all(
        "Buffer" not in buffer["buffer_name"]
        for buffer in payload["buffer_master"]
    )
    assert all(
        "POLY机" not in machine["machine_name"]
        and "RCA机" not in machine["machine_name"]
        for machine in payload["machine_master"]
    )


@pytest.mark.parametrize("path", (FIRST_ROUND_INPUT, NEXT_ROUND_INPUT))
def test_standard_input_machine_realtime_omits_removed_quantity_keys(
    path: Path,
):
    payload = _load_json(path)

    for runtime in payload["machine_realtime"]:
        assert {"completed_quantity", "period_quantity"}.isdisjoint(runtime)
        assert {"input_quantity", "output_quantity"} <= runtime.keys()


def test_all_example_request_json_uses_current_machine_realtime_contract():
    request_paths = []
    for path in EXAMPLES.rglob("*.json"):
        payload = _load_json(path)
        if not isinstance(payload, dict) or "machine_realtime" not in payload:
            continue
        request_paths.append(path)
        for runtime in payload["machine_realtime"]:
            assert {"completed_quantity", "period_quantity"}.isdisjoint(
                runtime
            ), path
            assert {"input_quantity", "output_quantity"} <= runtime.keys()

    assert request_paths


def test_next_round_replays_pending_and_keeps_all_state_keys_explicit():
    payload = _load_json(NEXT_ROUND_INPUT)

    assert payload["pending_cutline_plans"]
    assert payload["active_cutline_events"] == []
    assert payload["return_suggested_event_ids"] == []
    assert payload["mixed_cutline_event_ids"] == []
    assert payload["pending_cutline_plans"][0]["status"] == "PENDING"
    created_at = normalize_local_time(
        datetime.fromisoformat(
            payload["pending_cutline_plans"][0]["created_at"]
        )
    )
    assert any(
        normalize_local_time(datetime.fromisoformat(item["createtime"]))
        > created_at
        for item in payload["agv_relations"]
    )


@pytest.mark.parametrize("path", SUCCESS_OUTPUTS, ids=lambda path: path.name)
def test_standard_success_output_matches_public_response_schema(path: Path):
    CutlineEvaluateResponse.model_validate(_load_json(path))


def test_standard_stockout_output_contains_plan_and_pending_state():
    output = _load_json(
        EXAMPLES / "cutline_standard_output_stockout_plan.json"
    )

    assert output["stockout_warnings"]
    assert output["cutline_decisions"][0]["plan"]["selected_machines"]
    assert output["persistence_state"]["pending_cutline_plans"]


def test_standard_confirmation_output_contains_state_transitions():
    output = _load_json(
        EXAMPLES / "cutline_standard_output_pending_confirmed.json"
    )

    assert output["new_active_cutline_events"]
    assert output["mixing_trace_records"]
    assert output["persistence_state"]["completed_pending_plan_ids"]
    assert output["persistence_state"]["new_mixing_trace_records"]


def test_standard_return_output_contains_idempotency_state():
    output = _load_json(
        EXAMPLES / "cutline_standard_output_return_recommendation.json"
    )

    event_id = output["return_recommendations"][0]["event_id"]
    assert output["closed_active_cutline_event_ids"] == [event_id]
    assert output["persistence_state"]["return_suggested_event_ids"] == [
        event_id
    ]


def test_standard_manual_intervention_is_a_success_response():
    output = _load_json(
        EXAMPLES / "cutline_standard_output_manual_intervention.json"
    )

    assert output["cutline_decisions"][0]["manual_intervention"] == {
        "reason": "no_candidate_machine"
    }


@pytest.mark.parametrize(
    ("output_path", "input_factory"),
    (
        (
            EXAMPLES / "cutline_standard_output_no_warning.json",
            lambda: _scenario("v3_no_warning"),
        ),
        (
            EXAMPLES / "cutline_standard_output_stockout_plan.json",
            lambda: _load_json(FIRST_ROUND_INPUT),
        ),
        (
            EXAMPLES / "cutline_standard_output_pending_confirmed.json",
            lambda: _load_json(NEXT_ROUND_INPUT),
        ),
        (
            EXAMPLES / "cutline_standard_output_return_recommendation.json",
            lambda: {
                **_scenario("v3_return_recommended"),
                "mixed_cutline_event_ids": [],
            },
        ),
        (
            EXAMPLES / "cutline_standard_output_manual_intervention.json",
            lambda: _scenario("v3_stockout_manual"),
        ),
    ),
    ids=lambda value: value.name if isinstance(value, Path) else None,
)
def test_standard_success_output_is_the_current_formal_api_response(
    output_path: Path,
    input_factory,
):
    response = TestClient(create_app(), raise_server_exceptions=False).post(
        "/cutline/evaluate",
        json=input_factory(),
    )

    assert response.status_code == 200, response.text
    assert response.json() == _load_json(output_path)


@pytest.mark.parametrize(
    ("path", "code"),
    (
        (ERROR_OUTPUTS[0], "BACKEND_DATA_INVALID"),
        (ERROR_OUTPUTS[1], "SNAPSHOT_CONVERSION_FAILED"),
    ),
)
def test_standard_422_error_uses_formal_error_envelope(path: Path, code: str):
    output = _load_json(path)

    assert output["detail"]["code"] == code
    assert isinstance(output["detail"]["message"], str)
    assert isinstance(output["detail"]["issues"], list)


def test_standard_backend_data_invalid_example_is_the_formal_api_response():
    payload = _load_json(FIRST_ROUND_INPUT)
    payload["orders"][0]["total_quantity"] = "not-a-number"
    response = TestClient(create_app(), raise_server_exceptions=False).post(
        "/cutline/evaluate",
        json=payload,
    )

    assert response.status_code == 422
    assert response.json() == _load_json(ERROR_OUTPUTS[0])


def test_standard_snapshot_conversion_example_is_the_formal_api_response():
    payload = _load_json(FIRST_ROUND_INPUT)
    machine = payload["machine_master"][0]
    payload["machine_lines"] = [
        {
            "machine_code": machine["machine_code"],
            "machine_name": machine["machine_name"],
            "line_code": "S2-STANDARD-LINE",
            "line_name": "S2标准示例产线",
            "wafer_spec": "N",
        }
    ]
    payload["lines"] = []
    response = TestClient(create_app(), raise_server_exceptions=False).post(
        "/cutline/evaluate",
        json=payload,
    )

    assert response.status_code == 422
    assert response.json() == _load_json(ERROR_OUTPUTS[1])
