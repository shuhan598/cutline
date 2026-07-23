import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.adapters.backend_request_loader import BackendRequestLoader
from app.adapters.snapshot_adapter import SnapshotAdapter
from app.schemas.request_schema import AlgorithmSnapshot, CutlineAlgorithmRequest
from app.schemas.response_schema import CutlineAlgorithmResponse
from app.service.cutline_service import CutlineService
from tests.fixtures.v3_full_route_factory import (
    PROCESS_CODES,
    V3_SCENARIO_BUILDERS,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
DEBUG_OUTPUTS = ROOT / "debug_outputs"

OLD_EXAMPLES = {
    "cutline_sample_input.json",
    "cutline_complex_input.json",
    "cutline_overflow_input.json",
    "cutline_return_input.json",
    "cutline_silk_screen_input.json",
    "cutline_mix_trace_input.json",
    "stockout_full_flow_t0_input.json",
    "stockout_full_flow_t1_return_input.json",
    "stockout_full_flow_mix_trace_input.json",
    "run_stockout_full_flow.py",
}

V3_RESPONSE_SCENARIOS = {
    "v3_no_warning_response.json": "v3_no_warning",
    "v3_stockout_auto_response.json": "v3_stockout_auto",
    "v3_stockout_manual_no_candidate_response.json": "v3_stockout_manual",
    "v3_stockout_manual_insufficient_response.json": (
        "v3_stockout_manual_insufficient"
    ),
    "v3_overflow_warning_response.json": "v3_overflow_warning",
    "v3_overflow_manual_response.json": "v3_overflow_manual",
    "v3_return_tracking_started_response.json": "v3_return_round_2",
    "v3_return_recommended_response.json": "v3_return_recommended",
    "v3_silk_not_ready_response.json": "v3_silk_not_ready",
    "v3_silk_prepare_response.json": "v3_silk_prepare",
    "v3_mixing_failure_response.json": "v3_mixing_failure",
}


def _load_json(name: str) -> dict:
    with (EXAMPLES / name).open(encoding="utf-8") as file:
        return json.load(file)


def _load_cutline_request(payload: dict) -> CutlineAlgorithmRequest:
    return BackendRequestLoader().load_cutline_dict(payload)


def test_request_example_is_current_and_converts_to_algorithm_snapshot():
    payload = _load_json("backend_request_sample.json")

    request = _load_cutline_request(payload)
    snapshot = SnapshotAdapter().to_algorithm_snapshot(request)

    assert isinstance(snapshot, AlgorithmSnapshot)
    assert len(snapshot.workshops) == 1
    assert len(snapshot.lines) == 4
    assert len(snapshot.machine_runtimes) == 24
    assert len(snapshot.buffer_masters) == 10
    assert [item.process_code for item in snapshot.process_routes] == list(
        PROCESS_CODES
    )
    assert "config" not in payload
    assert "active_cutline_events" in payload
    assert payload["snapshot_meta"]["workshop_id"] == "S2"


def test_stockout_plan_example_produces_complete_cutline_response():
    payload = _load_json("backend_request_stockout_plan_sample.json")
    request = _load_cutline_request(payload)

    response = CutlineService().evaluate_algorithm(request)

    assert len(response.stockout_warnings) == 1
    warning = response.stockout_warnings[0]
    assert warning.buffer_code == "310110302"
    assert warning.order_code == "ORD-S2-001"
    assert warning.net_consumption_rate == 400
    assert warning.depletion_minutes == 15

    assert response.overflow_warnings == []
    assert len(response.cutline_decisions) == 1
    decision = response.cutline_decisions[0]
    assert "manual_intervention" not in decision.model_dump()
    assert decision.plan is not None
    assert decision.plan.warning_type == "stockout"
    assert decision.plan.initial_capacity_gap == 400
    assert decision.plan.total_contribution_capacity == 600
    assert decision.plan.remaining_capacity_gap == 0
    assert [item.machine_code for item in decision.plan.selected_machines] == ["EA004"]

    assert len(response.new_active_cutline_events) == 1
    assert response.new_active_cutline_events[0].machine_code == "EA004"
    assert len(response.mixing_trace_records) == 1
    assert response.mixing_trace_records[0].machine_code == "EA004"
    assert "mixing_trace_failures" not in response.__class__.model_fields
    assert response.errors == []

def test_response_example_has_every_public_response_field():
    payload = _load_json("cutline_algorithm_response_sample.json")

    response = CutlineAlgorithmResponse.model_validate(payload)

    assert set(payload) == set(CutlineAlgorithmResponse.model_fields)
    assert response.calculation_time.isoformat().startswith("2026-07")


def test_current_run_script_executes_the_official_service_chain():
    completed = subprocess.run(
        [sys.executable, str(EXAMPLES / "run_cutline_algorithm.py")],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    response = CutlineAlgorithmResponse.model_validate_json(completed.stdout)
    assert response.calculation_time.isoformat().startswith("2026-07")


@pytest.mark.parametrize("response_name", V3_RESPONSE_SCENARIOS)
def test_v3_response_example_exists_and_matches_public_schema(response_name):
    path = DEBUG_OUTPUTS / response_name

    assert path.is_file()
    actual = CutlineAlgorithmResponse.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    scenario_name = V3_RESPONSE_SCENARIOS[response_name]
    request = _load_cutline_request(V3_SCENARIO_BUILDERS[scenario_name]())
    expected = CutlineService().evaluate_algorithm(request)

    assert set(actual.__class__.model_fields) == set(
        CutlineAlgorithmResponse.model_fields
    )
    assert actual.model_dump() == expected.model_dump()


@pytest.mark.parametrize(
    ("response_name", "reason"),
    [
        ("v3_stockout_manual_no_candidate_response.json", "no_candidate_machine"),
        ("v3_stockout_manual_insufficient_response.json", "insufficient_capacity"),
        ("v3_overflow_manual_response.json", "no_valid_target_order"),
    ],
)
def test_manual_examples_only_expose_warning_id_and_reason(response_name, reason):
    payload = json.loads(
        (DEBUG_OUTPUTS / response_name).read_text(encoding="utf-8")
    )

    assert len(payload["cutline_decisions"]) == 1
    decision = payload["cutline_decisions"][0]
    assert set(decision) == {"warning_id", "manual_intervention"}
    assert decision["manual_intervention"] == {"reason": reason}


def test_return_recommended_example_closes_event_without_public_diagnostics():
    payload = json.loads(
        (DEBUG_OUTPUTS / "v3_return_recommended_response.json").read_text(
            encoding="utf-8"
        )
    )

    assert len(payload["return_recommendations"]) == 1
    assert payload["closed_active_cutline_event_ids"] == [
        payload["return_recommendations"][0]["event_id"]
    ]
    assert payload["updated_active_cutline_events"] == []
    assert "return_results" not in payload
    assert "mixing_trace_failures" not in payload
    assert "negative_start_time" not in payload["return_recommendations"][0]


def test_return_tracking_example_serializes_backend_timer_field():
    payload = json.loads(
        (DEBUG_OUTPUTS / "v3_return_tracking_started_response.json").read_text(
            encoding="utf-8"
        )
    )

    assert len(payload["updated_active_cutline_events"]) == 1
    assert set(payload["updated_active_cutline_events"][0]) == {
        "event_id",
        "negative_start_time",
    }


@pytest.mark.parametrize("scenario_name", sorted(V3_SCENARIO_BUILDERS))
def test_generated_v3_scenario_matches_the_shared_factory(scenario_name):
    payload = _load_json(f"scenarios/{scenario_name}.json")

    assert payload == V3_SCENARIO_BUILDERS[scenario_name]()
    request = _load_cutline_request(payload)
    SnapshotAdapter().to_algorithm_snapshot(request)


def test_run_script_accepts_a_v3_scenario_path():
    scenario_path = EXAMPLES / "scenarios" / "v3_stockout_auto.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(EXAMPLES / "run_cutline_algorithm.py"),
            str(scenario_path),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    response = CutlineAlgorithmResponse.model_validate_json(completed.stdout)
    assert response.stockout_warnings[0].buffer_code == "310110302"
    assert response.cutline_decisions[0].plan is not None


@pytest.mark.parametrize(
    "name",
    [
        "backend_request_sample.json",
        "backend_request_stockout_plan_sample.json",
    ],
)
def test_official_request_examples_do_not_contain_legacy_fake_codes(name):
    serialized = json.dumps(_load_json(name), ensure_ascii=False)

    for legacy_code in (
        "BUF-ZR-PK",
        "ZR-02",
        "PK-01",
        "WS-S1",
        "P-ZR",
        "P-PK",
        "LINE-N",
    ):
        assert legacy_code not in serialized


def test_backend_ingestion_example_uses_v3_values_without_merging_schemas():
    payload = _load_json("backend_ingestion_request_sample.json")

    BackendRequestLoader().load_dict(payload)
    assert "active_cutline_events" not in payload
    assert all("order_name" not in item for item in payload["orders"])
    assert payload["workshops"] == [
        {"workshop_code": "S2", "workshop_name": "S2车间"}
    ]
    assert [item["process_code"] for item in payload["process_routes"]] == list(
        PROCESS_CODES
    )
    assert all(item["machine_code"].startswith("EA") for item in payload["machine_master"])
    assert all(item["buffer_code"].isdigit() for item in payload["buffer_master"])
    assert all(
        item["line_code"] == f"S2-{item['line_name']}"
        for item in payload["lines"]
    )


@pytest.mark.parametrize(
    ("request_name", "response_name"),
    [
        ("backend_request_sample.json", "cutline_response_result.json"),
        (
            "backend_request_stockout_plan_sample.json",
            "stockout_plan_sample_response.json",
        ),
    ],
)
def test_debug_output_is_regenerated_by_the_current_service(
    request_name,
    response_name,
):
    request = _load_cutline_request(_load_json(request_name))
    expected = CutlineService().evaluate_algorithm(request)
    actual = CutlineAlgorithmResponse.model_validate_json(
        (DEBUG_OUTPUTS / response_name).read_text(encoding="utf-8")
    )

    assert actual.model_dump() == expected.model_dump()


def test_untraceable_legacy_debug_outputs_are_not_formal_v3_examples():
    legacy_names = {
        "stockout_full_flow_t0_response.json",
        "stockout_full_flow_t1_response.json",
        "stockout_full_flow_mix_trace_response.json",
    }

    assert not {name for name in legacy_names if (DEBUG_OUTPUTS / name).exists()}


def test_readme_documents_v3_generation_and_scenario_execution():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "310110301" in readme
    assert "EA001" in readme
    assert "S2-SW1A" in readme
    assert "generate_v3_scenarios.py" in readme
    assert "examples/scenarios/v3_stockout_auto.json" in readme


def test_backend_response_document_uses_v3_codes_in_public_examples():
    document = (ROOT / "docs" / "backend-response-interface.md").read_text(
        encoding="utf-8"
    )

    assert "310110302" in document
    assert "EA004" in document
    assert "ORD-S2-001" in document
    for legacy_code in ("BUF-ZR-PK", "ZR-02", "WS-S1", "P-ZR", "P-PK"):
        assert legacy_code not in document


def test_legacy_example_files_are_removed():
    assert not {name for name in OLD_EXAMPLES if (EXAMPLES / name).exists()}
