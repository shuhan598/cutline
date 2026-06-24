from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.candidate_machine.stockout_candidate_finder import StockoutCandidateFinder
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)
from app.core.warning.stockout_warning import StockoutWarningEvaluator


SAMPLE_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_sample_input.json"


def build_candidates():
    snapshot = MockAdapter().load(SAMPLE_INPUT_PATH)
    strategy = RealtimeFirstRateStrategy()
    net_rates = NetRateCalculator(strategy).calculate(snapshot)
    depletions = DepletionTimeCalculator().calculate(snapshot, net_rates)
    warnings = StockoutWarningEvaluator().evaluate(snapshot, depletions)
    return StockoutCandidateFinder(strategy).find(snapshot, warnings)


def test_candidate_zr03_idle_rate_is_zero_at_full_utilization():
    results = build_candidates()
    hg182t = next(r for r in results if r.product_code == "HG182T")
    zr03 = next(c for c in hg182t.candidates if c.equipment_code == "zr03")
    # zr03 产出 8000 / 静态产能 8000 = 利用率 1.0，空闲度 0.0
    assert zr03.utilization_rate == 1.0
    assert zr03.idle_rate == 0.0
