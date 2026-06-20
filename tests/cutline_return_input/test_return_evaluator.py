from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)
from app.core.return_judge.return_evaluator import ReturnEvaluator


RETURN_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_return_input.json"


def build():
    snapshot = MockAdapter().load(RETURN_INPUT_PATH)
    net_rates = NetRateCalculator(RealtimeFirstRateStrategy()).calculate(snapshot)
    depletions = DepletionTimeCalculator().calculate(snapshot, net_rates)
    return ReturnEvaluator().evaluate(snapshot, net_rates, depletions)


def by_equipment(results):
    return {r.equipment_code: r for r in results}


def test_returns_one_result_per_tracked_event():
    results = build()
    assert len(results) == 2


def test_zr03_triggers_return_when_three_conditions_met():
    zr03 = by_equipment(build())["zr03"]
    assert zr03.net_rate_per_hour == -6400
    assert zr03.inventory_quantity == 5000
    assert zr03.negative_duration_minutes == 25
    assert zr03.safety_inventory_quantity == 3200
    assert zr03.triggered is True


def test_zr_r_clears_negative_start_time_when_net_rate_non_negative():
    zr_r = by_equipment(build())["zr_r"]
    assert zr_r.net_rate_per_hour == 0
    assert zr_r.negative_start_time is None
    assert zr_r.triggered is False
