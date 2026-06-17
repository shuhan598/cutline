import json
from pathlib import Path

from app.core.net_rate.net_rate_calculator import calculate_all_net_rates


COMPLEX_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_complex_input.json"


def load_complex_input():
    with COMPLEX_INPUT_PATH.open(encoding="utf-8") as file:
        return json.load(file)


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


def test_calculate_all_net_rates_handles_multiple_buffers_and_products():
    data = load_complex_input()

    results = calculate_all_net_rates(data)
    by_segment = results_by_segment(results)

    assert len(results) == 4
    assert {
        ("BUF_PK_OX", "HG210R", "PK", "OX"),
        ("BUF_ZR_PK", "HG182N", "ZR", "PK"),
        ("BUF_ZR_PK", "HG182T", "ZR", "PK"),
        ("BUF_ZR_PK", "HG182R", "ZR", "PK"),
    } == set(by_segment)


def test_calculate_all_net_rates_matches_complex_input_design():
    data = load_complex_input()

    by_segment = results_by_segment(calculate_all_net_rates(data))

    assert by_segment[("BUF_PK_OX", "HG210R", "PK", "OX")]["net_rate_per_hour"] == 6000
    assert by_segment[("BUF_ZR_PK", "HG182N", "ZR", "PK")]["net_rate_per_hour"] == 4000
    assert by_segment[("BUF_ZR_PK", "HG182T", "ZR", "PK")]["net_rate_per_hour"] == 3600
    assert by_segment[("BUF_ZR_PK", "HG182R", "ZR", "PK")]["net_rate_per_hour"] == 2500
