from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.schemas.response_schema import CutlineEvaluateResponse
from app.service.cutline_service import CutlineService


COMPLEX_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_complex_input.json"


def evaluate_complex():
    snapshot = MockAdapter().load(COMPLEX_INPUT_PATH)
    return CutlineService().evaluate(snapshot)


def test_service_returns_cutline_evaluate_response():
    response = evaluate_complex()

    assert isinstance(response, CutlineEvaluateResponse)
    assert response.success is True
    assert response.plans == []
    assert response.return_suggestions == []


def test_service_maps_three_triggered_stockout_warnings():
    response = evaluate_complex()

    assert len(response.warnings) == 3
    assert {warning.product_code for warning in response.warnings} == {
        "HG210R",
        "HG182N",
        "HG182T",
    }
    hg210r = next(w for w in response.warnings if w.product_code == "HG210R")
    assert hg210r.warning_type == "stockout"
    assert hg210r.upstream_process_code == "PK"
    assert hg210r.downstream_process_code == "OX"
    assert hg210r.net_rate == 6000
    assert hg210r.prediction_minutes == 10


def test_service_surfaces_candidates_as_manual_interventions_in_urgency_order():
    response = evaluate_complex()

    assert [
        intervention.warning.product_code
        for intervention in response.manual_interventions
    ] == ["HG210R", "HG182N", "HG182T"]

    hg182t = next(
        intervention
        for intervention in response.manual_interventions
        if intervention.warning.product_code == "HG182T"
    )
    codes = {machine.equipment_code for machine in hg182t.candidate_machines}
    assert {"zr_hg182r_candidate", "zr_hg182r_candidate_2"}.issubset(codes)
