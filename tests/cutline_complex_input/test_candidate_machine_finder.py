from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.candidate_machine.candidate_machine_finder import CandidateMachineFinder
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)
from app.core.warning.stockout_warning import StockoutWarningEvaluator


COMPLEX_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_complex_input.json"


def load_complex_snapshot():
    return MockAdapter().load(COMPLEX_INPUT_PATH)


def build_candidates(snapshot):
    strategy = RealtimeFirstRateStrategy()
    net_rates = NetRateCalculator(strategy).calculate(snapshot)
    depletions = DepletionTimeCalculator().calculate(snapshot, net_rates)
    warnings = StockoutWarningEvaluator().evaluate(snapshot, depletions)
    return CandidateMachineFinder(strategy).find(snapshot, warnings)


def by_product(results, product_code):
    for result in results:
        if result.product_code == product_code:
            return result
    raise AssertionError(f"Expected result for {product_code} was not found")


def codes(candidate_result):
    return {candidate.equipment_code for candidate in candidate_result.candidates}


def test_returns_results_in_global_depletion_urgency_order():
    results = build_candidates(load_complex_snapshot())

    assert [result.product_code for result in results] == [
        "HG210R",
        "HG182N",
        "HG182T",
    ]
    assert all("priority_rank" not in result.model_dump() for result in results)
    assert all(
        "priority_rank" not in candidate.model_dump()
        for result in results
        for candidate in result.candidates
    )


def test_hg210r_finds_compatible_pk_candidate_and_excludes_invalid_machines():
    hg210r = by_product(build_candidates(load_complex_snapshot()), "HG210R")

    assert hg210r.candidate_found is True
    assert hg210r.candidate_status == "candidate_found"
    assert "pk_hg210t_candidate" in codes(hg210r)
    assert "pk_hg210r_target" not in codes(hg210r)
    assert "pk_hg210t_stopped" not in codes(hg210r)
    assert "pk_hg182r_size_mismatch" not in codes(hg210r)


def test_hg182n_requires_manual_intervention_when_no_compatible_machine_exists():
    hg182n = by_product(build_candidates(load_complex_snapshot()), "HG182N")

    assert hg182n.candidate_found is False
    assert hg182n.candidate_status == "manual_intervention_required"
    assert hg182n.reason == "no_compatible_running_upstream_machine"
    assert hg182n.candidates == []


def test_hg182t_finds_compatible_zr_candidate_and_excludes_invalid_machines():
    hg182t = by_product(build_candidates(load_complex_snapshot()), "HG182T")

    assert hg182t.candidate_found is True
    assert hg182t.candidate_status == "candidate_found"
    assert len(hg182t.candidates) >= 2
    assert "zr_hg182r_candidate" in codes(hg182t)
    assert "zr_hg182r_candidate_2" in codes(hg182t)
    assert "zr_hg182t_target" not in codes(hg182t)
    assert "zr_hg182r_stopped" not in codes(hg182t)
    assert "zr_hg210r_size_mismatch" not in codes(hg182t)
    assert "zr_hg182n_target" not in codes(hg182t)
