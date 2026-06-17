import json
from pathlib import Path

from app.core.net_rate.net_rate_calculator import calculate_all_net_rates, calculate_net_rate


SAMPLE_INPUT_PATH = Path(__file__).resolve().parents[1] / "examples" / "cutline_sample_input.json"


def load_sample_input():
    with SAMPLE_INPUT_PATH.open(encoding="utf-8") as file:
        return json.load(file)


def test_calculates_hg182t_stockout_net_rate():
    data = load_sample_input()

    result = calculate_net_rate(
        data,
        buffer_code="BUF_ZR_PK",
        product_code="HG182T",
        process_from="ZR",
        process_to="PK",
    )

    assert result["upstream_output_per_hour"] == 16000
    assert result["downstream_input_per_hour"] == 19200
    assert result["net_rate_per_hour"] == 3200
    assert set(result["upstream_equipment_codes"]) == {"zr01", "zr02"}
    assert set(result["downstream_equipment_codes"]) == {"pk01", "pk02"}


def test_calculates_hg182r_net_rate_without_excluding_zr03():
    data = load_sample_input()

    result = calculate_net_rate(
        data,
        buffer_code="BUF_ZR_PK",
        product_code="HG182R",
        process_from="ZR",
        process_to="PK",
    )

    assert result["upstream_output_per_hour"] == 8000
    assert result["downstream_input_per_hour"] == 9600
    assert result["net_rate_per_hour"] == 1600
    assert set(result["upstream_equipment_codes"]) == {"zr03"}
    assert set(result["downstream_equipment_codes"]) == {"pk03"}


def test_calculate_all_net_rates_uses_buffer_inventories():
    data = load_sample_input()

    results = calculate_all_net_rates(data)
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
    assert hg182t["net_rate_per_hour"] == 3200

    hg182r = by_segment[("BUF_ZR_PK", "HG182R", "ZR", "PK")]
    assert hg182r["net_rate_per_hour"] == 1600
