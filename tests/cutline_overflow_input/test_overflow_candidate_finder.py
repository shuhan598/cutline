from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.candidate_machine.overflow_candidate_finder import OverflowCandidateFinder
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.warning.overflow_warning import OverflowWarningEvaluator


OVERFLOW_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_overflow_input.json"


def build():
    snapshot = MockAdapter().load(OVERFLOW_INPUT_PATH)
    strategy = RealtimeFirstRateStrategy()
    net_rates = NetRateCalculator(strategy).calculate(snapshot)
    warnings = OverflowWarningEvaluator().evaluate(snapshot, net_rates)
    return OverflowCandidateFinder(strategy).find(snapshot, warnings, net_rates)


def test_hg182t_overflow_candidate_is_zr_t1_with_target_hg182r():
    results = build()
    assert len(results) == 1
    result = results[0]
    assert result.product_code == "HG182T"
    assert result.candidate_found is True
    codes = {c.equipment_code for c in result.candidates}
    assert codes == {"zr_t1"}
    zr_t1 = result.candidates[0]
    assert zr_t1.current_product_code == "HG182T"
    assert zr_t1.target_product_code == "HG182R"
