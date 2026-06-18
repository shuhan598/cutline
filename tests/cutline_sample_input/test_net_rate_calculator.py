from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy


SAMPLE_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_sample_input.json"


def load_sample_snapshot():
    return MockAdapter().load(SAMPLE_INPUT_PATH)


def calculate(snapshot):
    return NetRateCalculator(RealtimeFirstRateStrategy()).calculate(snapshot)


def by_segment(results):
    return {
        (r.buffer_code, r.product_code, r.process_from, r.process_to): r
        for r in results
    }


def test_calculates_hg182t_stockout_net_rate():
    result = by_segment(calculate(load_sample_snapshot()))[
        ("BUF_ZR_PK", "HG182T", "ZR", "PK")
    ]

    assert result.upstream_output_per_hour == 16000
    assert result.downstream_input_per_hour == 19200
    assert result.net_rate_per_hour == 3200
    assert set(result.upstream_equipment_codes) == {"zr01", "zr02"}
    assert set(result.downstream_equipment_codes) == {"pk01", "pk02"}


def test_calculates_hg182r_net_rate_without_excluding_zr03():
    result = by_segment(calculate(load_sample_snapshot()))[
        ("BUF_ZR_PK", "HG182R", "ZR", "PK")
    ]

    assert result.upstream_output_per_hour == 8000
    assert result.downstream_input_per_hour == 9600
    assert result.net_rate_per_hour == 1600
    assert set(result.upstream_equipment_codes) == {"zr03"}
    assert set(result.downstream_equipment_codes) == {"pk03"}


def test_calculate_all_net_rates_uses_buffer_inventories():
    segments = by_segment(calculate(load_sample_snapshot()))

    assert segments[("BUF_ZR_PK", "HG182T", "ZR", "PK")].net_rate_per_hour == 3200
    assert segments[("BUF_ZR_PK", "HG182R", "ZR", "PK")].net_rate_per_hour == 1600
