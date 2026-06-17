import json
from pathlib import Path

from app.core.net_rate.net_rate_calculator import calculate_all_net_rates
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    calculate_all_depletion_times,
    calculate_depletion_time,
    find_inventory_quantity,
)


SAMPLE_INPUT_PATH = Path(__file__).resolve().parents[1] / "examples" / "cutline_sample_input.json"


def load_sample_input():
    with SAMPLE_INPUT_PATH.open(encoding="utf-8") as file:
        return json.load(file)


def find_net_rate_result(net_rate_results, buffer_code, product_code, process_from, process_to):
    for result in net_rate_results:
        if (
            result["buffer_code"] == buffer_code
            and result["product_code"] == product_code
            and result["process_from"] == process_from
            and result["process_to"] == process_to
        ):
            return result

    raise AssertionError("Expected net rate result was not found")


def test_find_inventory_quantity_matches_buffer_product_and_process_segment():
    data = load_sample_input()

    hg182t_quantity = find_inventory_quantity(
        data,
        buffer_code="BUF_ZR_PK",
        product_code="HG182T",
        process_from="ZR",
        process_to="PK",
    )
    hg182r_quantity = find_inventory_quantity(
        data,
        buffer_code="BUF_ZR_PK",
        product_code="HG182R",
        process_from="ZR",
        process_to="PK",
    )

    assert hg182t_quantity == 1600
    assert hg182r_quantity == 20000


def test_calculate_depletion_time_for_hg182t_stockout_segment():
    data = load_sample_input()
    net_rate_results = calculate_all_net_rates(data)
    net_rate_result = find_net_rate_result(
        net_rate_results,
        buffer_code="BUF_ZR_PK",
        product_code="HG182T",
        process_from="ZR",
        process_to="PK",
    )

    result = calculate_depletion_time(data, net_rate_result)

    assert result["inventory_quantity"] == 1600
    assert result["net_rate_per_hour"] == 3200
    assert result["depletion_minutes"] == 30
    assert result["depletion_status"] == "decreasing"


def test_calculate_depletion_time_for_hg182r_stockout_segment():
    data = load_sample_input()
    net_rate_results = calculate_all_net_rates(data)
    net_rate_result = find_net_rate_result(
        net_rate_results,
        buffer_code="BUF_ZR_PK",
        product_code="HG182R",
        process_from="ZR",
        process_to="PK",
    )

    result = calculate_depletion_time(data, net_rate_result)

    assert result["inventory_quantity"] == 20000
    assert result["net_rate_per_hour"] == 1600
    assert result["depletion_minutes"] == 750
    assert result["depletion_status"] == "decreasing"


def test_calculate_all_depletion_times_includes_stockout_segments():
    data = load_sample_input()
    net_rate_results = calculate_all_net_rates(data)

    results = calculate_all_depletion_times(data, net_rate_results)
    by_segment = {
        (
            result["buffer_code"],
            result["product_code"],
            result["process_from"],
            result["process_to"],
        ): result
        for result in results
    }

    hg182t = by_segment[("BUF_ZR_PK", "HG182T", "ZR", "PK")]
    assert hg182t["depletion_minutes"] == 30

    hg182r = by_segment[("BUF_ZR_PK", "HG182R", "ZR", "PK")]
    assert hg182r["depletion_minutes"] == 750
