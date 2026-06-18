from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)


SAMPLE_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_sample_input.json"


def load_sample_snapshot():
    return MockAdapter().load(SAMPLE_INPUT_PATH)


def build_depletions(snapshot):
    net_rates = NetRateCalculator(RealtimeFirstRateStrategy()).calculate(snapshot)
    return DepletionTimeCalculator().calculate(snapshot, net_rates)


def by_segment(results):
    return {
        (r.buffer_code, r.product_code, r.process_from, r.process_to): r
        for r in results
    }


def test_inventory_quantity_matches_buffer_product_and_process_segment():
    segments = by_segment(build_depletions(load_sample_snapshot()))

    assert segments[("BUF_ZR_PK", "HG182T", "ZR", "PK")].inventory_quantity == 1600
    assert segments[("BUF_ZR_PK", "HG182R", "ZR", "PK")].inventory_quantity == 20000


def test_depletion_time_for_hg182t_stockout_segment():
    result = by_segment(build_depletions(load_sample_snapshot()))[
        ("BUF_ZR_PK", "HG182T", "ZR", "PK")
    ]

    assert result.inventory_quantity == 1600
    assert result.net_rate_per_hour == 3200
    assert result.depletion_minutes == 30
    assert result.depletion_status == "decreasing"


def test_depletion_time_for_hg182r_stockout_segment():
    result = by_segment(build_depletions(load_sample_snapshot()))[
        ("BUF_ZR_PK", "HG182R", "ZR", "PK")
    ]

    assert result.inventory_quantity == 20000
    assert result.net_rate_per_hour == 1600
    assert result.depletion_minutes == 750
    assert result.depletion_status == "decreasing"
