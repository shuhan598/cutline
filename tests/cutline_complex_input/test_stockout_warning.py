from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)
from app.core.warning.stockout_warning import StockoutWarningEvaluator


COMPLEX_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_complex_input.json"


def load_complex_snapshot():
    return MockAdapter().load(COMPLEX_INPUT_PATH)


def build_warnings(snapshot):
    net_rates = NetRateCalculator(RealtimeFirstRateStrategy()).calculate(snapshot)
    depletions = DepletionTimeCalculator().calculate(snapshot, net_rates)
    return StockoutWarningEvaluator().evaluate(snapshot, depletions)


def by_product(warnings):
    return {warning.product_code: warning for warning in warnings}


def test_complex_stockout_warnings_match_expected_trigger_states():
    warnings = by_product(build_warnings(load_complex_snapshot()))

    assert warnings["HG210R"].warning_triggered is True
    assert warnings["HG182N"].warning_triggered is True
    assert warnings["HG182T"].warning_triggered is True
    assert warnings["HG182R"].warning_triggered is False


def test_complex_stockout_warning_reasons_follow_depletion_time_threshold():
    warnings = by_product(build_warnings(load_complex_snapshot()))

    assert warnings["HG210R"].reason == "depletion_time_within_lead_time"
    assert warnings["HG182N"].reason == "depletion_time_within_lead_time"
    assert warnings["HG182T"].reason == "depletion_time_within_lead_time"
    assert warnings["HG182R"].reason == "depletion_time_beyond_lead_time"
