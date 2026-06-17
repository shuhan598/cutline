import json
from pathlib import Path

from app.core.candidate_machine.candidate_machine_finder import find_all_candidates
from app.core.net_rate.net_rate_calculator import calculate_all_net_rates
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    calculate_all_depletion_times,
)
from app.core.warning.stockout_warning import evaluate_all_stockout_warnings


COMPLEX_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_complex_input.json"


def load_complex_input():
    with COMPLEX_INPUT_PATH.open(encoding="utf-8") as file:
        return json.load(file)


def build_warning_results(data):
    net_rate_results = calculate_all_net_rates(data)
    depletion_results = calculate_all_depletion_times(data, net_rate_results)
    return evaluate_all_stockout_warnings(data, depletion_results)


def build_candidate_results(data):
    return find_all_candidates(data, build_warning_results(data))


def result_by_product(results, product_code):
    for result in results:
        if result["product_code"] == product_code:
            return result

    raise AssertionError(f"Expected result for {product_code} was not found")


def candidate_codes(candidate_result):
    return {candidate["equipment_code"] for candidate in candidate_result["candidates"]}


def test_find_all_candidates_returns_results_in_global_depletion_urgency_order():
    data = load_complex_input()

    candidate_results = build_candidate_results(data)

    assert [result["product_code"] for result in candidate_results] == [
        "HG210R",
        "HG182N",
        "HG182T",
    ]
    assert all("priority_rank" not in result for result in candidate_results)
    assert all(
        "priority_rank" not in candidate
        for result in candidate_results
        for candidate in result["candidates"]
    )


def test_hg210r_finds_compatible_pk_candidate_and_excludes_invalid_machines():
    data = load_complex_input()

    hg210r = result_by_product(build_candidate_results(data), "HG210R")
    codes = candidate_codes(hg210r)

    assert hg210r["candidate_found"] is True
    assert hg210r["candidate_status"] == "candidate_found"
    assert "pk_hg210t_candidate" in codes
    assert "pk_hg210r_target" not in codes
    assert "pk_hg210t_stopped" not in codes
    assert "pk_hg182r_size_mismatch" not in codes


def test_hg182n_requires_manual_intervention_when_no_compatible_machine_exists():
    data = load_complex_input()

    hg182n = result_by_product(build_candidate_results(data), "HG182N")

    assert hg182n["candidate_found"] is False
    assert hg182n["candidate_status"] == "manual_intervention_required"
    assert hg182n["reason"] == "no_compatible_running_upstream_machine"
    assert hg182n["candidates"] == []


def test_hg182t_finds_compatible_zr_candidate_and_excludes_invalid_machines():
    data = load_complex_input()

    hg182t = result_by_product(build_candidate_results(data), "HG182T")
    codes = candidate_codes(hg182t)

    assert hg182t["candidate_found"] is True
    assert hg182t["candidate_status"] == "candidate_found"
    assert len(hg182t["candidates"]) >= 2
    assert "zr_hg182r_candidate" in codes
    assert "zr_hg182r_candidate_2" in codes
    assert "zr_hg182t_target" not in codes
    assert "zr_hg182r_stopped" not in codes
    assert "zr_hg210r_size_mismatch" not in codes
    assert "zr_hg182n_target" not in codes
