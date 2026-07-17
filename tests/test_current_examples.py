import json
import subprocess
import sys
from pathlib import Path

from app.adapters.snapshot_adapter import SnapshotAdapter
from app.schemas.request_schema import AlgorithmSnapshot, CutlineAlgorithmRequest
from app.schemas.response_schema import CutlineAlgorithmResponse
from app.service.cutline_service import CutlineService


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

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


def _load_json(name: str) -> dict:
    with (EXAMPLES / name).open(encoding="utf-8") as file:
        return json.load(file)


def test_request_example_is_current_and_converts_to_algorithm_snapshot():
    payload = _load_json("backend_request_sample.json")

    request = CutlineAlgorithmRequest.model_validate(payload)
    snapshot = SnapshotAdapter().to_algorithm_snapshot(request)

    assert isinstance(snapshot, AlgorithmSnapshot)
    assert len(snapshot.workshops) == 1
    assert len(snapshot.lines) == 1
    assert len(snapshot.machine_runtimes) == 1
    assert len(snapshot.machine_product_capacities) == 1
    assert "config" not in payload
    assert "active_cutline_events" in payload


def test_stockout_plan_example_produces_complete_cutline_response():
    payload = _load_json("backend_request_stockout_plan_sample.json")
    request = CutlineAlgorithmRequest.model_validate(payload)

    response = CutlineService().evaluate_algorithm(request)

    assert len(response.stockout_warnings) == 1
    warning = response.stockout_warnings[0]
    assert warning.order_code == "O-T"
    assert warning.net_consumption_rate == 400
    assert warning.depletion_minutes == 15

    assert response.overflow_warnings == []
    assert len(response.cutline_decisions) == 1
    decision = response.cutline_decisions[0]
    assert decision.manual_intervention is None
    assert decision.plan is not None
    assert decision.plan.warning_type == "stockout"
    assert decision.plan.initial_capacity_gap == 400
    assert decision.plan.total_contribution_capacity == 600
    assert decision.plan.remaining_capacity_gap == 0
    assert [item.machine_code for item in decision.plan.selected_machines] == ["ZR-02"]

    assert len(response.new_active_cutline_events) == 1
    assert response.new_active_cutline_events[0].machine_code == "ZR-02"
    assert len(response.mixing_trace_records) == 1
    assert response.mixing_trace_records[0].machine_code == "ZR-02"
    assert response.mixing_trace_failures == []
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


def test_legacy_example_files_are_removed():
    assert not {name for name in OLD_EXAMPLES if (EXAMPLES / name).exists()}
