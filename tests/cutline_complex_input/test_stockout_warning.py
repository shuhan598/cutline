import json
from pathlib import Path

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


def results_by_product(results):
    return {result["product_code"]: result for result in results}


def test_complex_stockout_warnings_match_expected_trigger_states():
    data = load_complex_input()

    by_product = results_by_product(build_warning_results(data))

    assert by_product["HG210R"]["warning_triggered"] is True
    assert by_product["HG182N"]["warning_triggered"] is True
    assert by_product["HG182T"]["warning_triggered"] is True
    assert by_product["HG182R"]["warning_triggered"] is False


def test_complex_stockout_warning_reasons_follow_depletion_time_threshold():
    data = load_complex_input()

    by_product = results_by_product(build_warning_results(data))

    assert by_product["HG210R"]["reason"] == "depletion_time_within_lead_time"
    assert by_product["HG182N"]["reason"] == "depletion_time_within_lead_time"
    assert by_product["HG182T"]["reason"] == "depletion_time_within_lead_time"
    assert by_product["HG182R"]["reason"] == "depletion_time_beyond_lead_time"
