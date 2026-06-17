import json
from pathlib import Path

from app.core.net_rate.net_rate_calculator import calculate_all_net_rates
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    calculate_all_depletion_times,
)
from app.core.warning.stockout_warning import (
    evaluate_all_stockout_warnings,
    evaluate_stockout_warning,
    get_cutline_lead_minutes,
)


SAMPLE_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_sample_input.json"


def load_sample_input():
    with SAMPLE_INPUT_PATH.open(encoding="utf-8") as file:
        return json.load(file)


def build_depletion_results(data):
    net_rate_results = calculate_all_net_rates(data)
    return calculate_all_depletion_times(data, net_rate_results)


def find_warning_result(warning_results, buffer_code, product_code, process_from, process_to):
    for result in warning_results:
        if (
            result["buffer_code"] == buffer_code
            and result["product_code"] == product_code
            and result["process_from"] == process_from
            and result["process_to"] == process_to
        ):
            return result

    raise AssertionError("Expected warning result was not found")


def test_get_cutline_lead_minutes_reads_config():
    data = load_sample_input()

    assert get_cutline_lead_minutes(data) == 30


def test_evaluate_all_stockout_warnings_returns_one_result_per_depletion_result():
    data = load_sample_input()
    depletion_results = build_depletion_results(data)

    warning_results = evaluate_all_stockout_warnings(data, depletion_results)

    assert len(warning_results) == len(depletion_results)


def test_hg182t_triggers_stockout_warning_within_lead_time():
    data = load_sample_input()
    depletion_results = build_depletion_results(data)

    warning_results = evaluate_all_stockout_warnings(data, depletion_results)
    hg182t = find_warning_result(warning_results, "BUF_ZR_PK", "HG182T", "ZR", "PK")

    assert hg182t["warning_triggered"] is True
    assert hg182t["reason"] == "depletion_time_within_lead_time"
    assert hg182t["depletion_minutes"] == 30
    assert hg182t["cutline_lead_minutes"] == 30


def test_hg182r_does_not_trigger_stockout_warning_beyond_lead_time():
    data = load_sample_input()
    depletion_results = build_depletion_results(data)

    warning_results = evaluate_all_stockout_warnings(data, depletion_results)
    hg182r = find_warning_result(warning_results, "BUF_ZR_PK", "HG182R", "ZR", "PK")

    assert hg182r["warning_triggered"] is False
    assert hg182r["reason"] == "depletion_time_beyond_lead_time"
    assert hg182r["depletion_minutes"] == 750
    assert hg182r["cutline_lead_minutes"] == 30


def test_evaluate_stockout_warning_returns_all_fields_for_single_result():
    data = load_sample_input()
    depletion_result = build_depletion_results(data)[0]

    result = evaluate_stockout_warning(data, depletion_result)

    assert set(result) == {
        "buffer_code",
        "product_code",
        "process_from",
        "process_to",
        "warning_type",
        "warning_triggered",
        "reason",
        "inventory_quantity",
        "net_rate_per_hour",
        "depletion_minutes",
        "depletion_status",
        "cutline_lead_minutes",
    }
    assert result["warning_type"] == "stockout"
