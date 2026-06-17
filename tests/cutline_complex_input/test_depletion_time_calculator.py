import json
from pathlib import Path

from app.core.net_rate.net_rate_calculator import calculate_all_net_rates
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    calculate_all_depletion_times,
)


COMPLEX_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_complex_input.json"


def load_complex_input():
    with COMPLEX_INPUT_PATH.open(encoding="utf-8") as file:
        return json.load(file)


def build_depletion_results(data):
    return calculate_all_depletion_times(data, calculate_all_net_rates(data))


def results_by_segment(results):
    return {
        (
            result["buffer_code"],
            result["product_code"],
            result["process_from"],
            result["process_to"],
        ): result
        for result in results
    }


def test_calculate_all_depletion_times_matches_complex_input_design():
    data = load_complex_input()

    by_segment = results_by_segment(build_depletion_results(data))

    assert by_segment[("BUF_PK_OX", "HG210R", "PK", "OX")]["depletion_minutes"] == 10
    assert by_segment[("BUF_ZR_PK", "HG182N", "ZR", "PK")]["depletion_minutes"] == 15
    assert by_segment[("BUF_ZR_PK", "HG182T", "ZR", "PK")]["depletion_minutes"] == 20
    assert by_segment[("BUF_ZR_PK", "HG182R", "ZR", "PK")]["depletion_minutes"] == 120


def test_complex_depletion_results_are_all_decreasing_inventory_cases():
    data = load_complex_input()

    results = build_depletion_results(data)

    assert {result["depletion_status"] for result in results} == {"decreasing"}
