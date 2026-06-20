from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.warning.overflow_warning import OverflowWarningEvaluator


OVERFLOW_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_overflow_input.json"


def build_overflow_warnings():
    snapshot = MockAdapter().load(OVERFLOW_INPUT_PATH)
    net_rates = NetRateCalculator(RealtimeFirstRateStrategy()).calculate(snapshot)
    return OverflowWarningEvaluator().evaluate(snapshot, net_rates), snapshot


def by_product(results):
    return {r.product_code: r for r in results}


def test_only_negative_net_rate_segments_produce_overflow_results():
    results, _ = build_overflow_warnings()
    products = {r.product_code for r in results}
    assert products == {"HG182T"}


def test_hg182t_overflow_triggers_at_thirty_minutes():
    result = by_product(build_overflow_warnings()[0])["HG182T"]
    assert result.warning_type == "overflow"
    assert result.warning_triggered is True
    assert result.reason == "overflow_time_within_lead_time"
    assert result.segment_inventory == 18000
    assert result.segment_capacity == 20000
    assert result.net_rate_per_hour == -4000
    assert result.overflow_minutes == 30
