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


def test_complex_cutline_algorithm_flow_runs_end_to_end():
    data = load_complex_input()

    net_rate_results = calculate_all_net_rates(data)
    depletion_results = calculate_all_depletion_times(data, net_rate_results)
    warning_results = evaluate_all_stockout_warnings(data, depletion_results)
    candidate_results = find_all_candidates(data, warning_results)

    assert len(net_rate_results) == 4
    assert len(depletion_results) == 4
    assert len(warning_results) == 4
    assert [result["product_code"] for result in candidate_results] == [
        "HG210R",
        "HG182N",
        "HG182T",
    ]
    assert [result["candidate_found"] for result in candidate_results] == [
        True,
        False,
        True,
    ]

    hg182t = next(
        result for result in candidate_results if result["product_code"] == "HG182T"
    )
    hg182t_candidate_codes = {
        candidate["equipment_code"] for candidate in hg182t["candidates"]
    }

    assert {
        "zr_hg182r_candidate",
        "zr_hg182r_candidate_2",
    }.issubset(hg182t_candidate_codes)
