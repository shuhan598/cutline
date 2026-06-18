from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)


COMPLEX_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_complex_input.json"


def load_complex_snapshot():
    return MockAdapter().load(COMPLEX_INPUT_PATH)


def build_depletions(snapshot):
    net_rates = NetRateCalculator(RealtimeFirstRateStrategy()).calculate(snapshot)
    return DepletionTimeCalculator().calculate(snapshot, net_rates)


def by_segment(results):
    return {
        (r.buffer_code, r.product_code, r.process_from, r.process_to): r
        for r in results
    }


def test_depletion_times_match_complex_input_design():
    segments = by_segment(build_depletions(load_complex_snapshot()))

    assert segments[("BUF_PK_OX", "HG210R", "PK", "OX")].depletion_minutes == 10
    assert segments[("BUF_ZR_PK", "HG182N", "ZR", "PK")].depletion_minutes == 15
    assert segments[("BUF_ZR_PK", "HG182T", "ZR", "PK")].depletion_minutes == 20
    assert segments[("BUF_ZR_PK", "HG182R", "ZR", "PK")].depletion_minutes == 120


def test_complex_depletion_results_are_all_decreasing_inventory_cases():
    results = build_depletions(load_complex_snapshot())

    assert {r.depletion_status for r in results} == {"decreasing"}
