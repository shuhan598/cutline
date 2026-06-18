from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy


COMPLEX_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_complex_input.json"


def load_complex_snapshot():
    return MockAdapter().load(COMPLEX_INPUT_PATH)


def calculate(snapshot):
    return NetRateCalculator(RealtimeFirstRateStrategy()).calculate(snapshot)


def by_segment(results):
    return {
        (r.buffer_code, r.product_code, r.process_from, r.process_to): r
        for r in results
    }


def test_calculate_all_net_rates_handles_multiple_buffers_and_products():
    segments = by_segment(calculate(load_complex_snapshot()))

    assert len(segments) == 4
    assert {
        ("BUF_PK_OX", "HG210R", "PK", "OX"),
        ("BUF_ZR_PK", "HG182N", "ZR", "PK"),
        ("BUF_ZR_PK", "HG182T", "ZR", "PK"),
        ("BUF_ZR_PK", "HG182R", "ZR", "PK"),
    } == set(segments)


def test_calculate_all_net_rates_matches_complex_input_design():
    segments = by_segment(calculate(load_complex_snapshot()))

    assert segments[("BUF_PK_OX", "HG210R", "PK", "OX")].net_rate_per_hour == 6000
    assert segments[("BUF_ZR_PK", "HG182N", "ZR", "PK")].net_rate_per_hour == 4000
    assert segments[("BUF_ZR_PK", "HG182T", "ZR", "PK")].net_rate_per_hour == 3600
    assert segments[("BUF_ZR_PK", "HG182R", "ZR", "PK")].net_rate_per_hour == 2500
