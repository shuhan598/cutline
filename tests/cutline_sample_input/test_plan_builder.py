from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.candidate_machine.candidate_machine_finder import CandidateMachineFinder
from app.core.cutline_plan.plan_builder import CutlinePlanBuilder
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)
from app.core.warning.stockout_warning import StockoutWarningEvaluator
from app.schemas.result_schema import ManualInterventionResult, PlanResult


SAMPLE_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_sample_input.json"


def build():
    snapshot = MockAdapter().load(SAMPLE_INPUT_PATH)
    strategy = RealtimeFirstRateStrategy()
    net_rates = NetRateCalculator(strategy).calculate(snapshot)
    depletions = DepletionTimeCalculator().calculate(snapshot, net_rates)
    warnings = StockoutWarningEvaluator().evaluate(snapshot, depletions)
    candidates = CandidateMachineFinder(strategy).find(snapshot, warnings)
    plans, interventions = CutlinePlanBuilder().build_stockout(
        warnings, candidates, net_rates, depletions
    )
    return plans, interventions


def test_hg182t_plan_selects_zr03_and_closes_gap():
    plans, interventions = build()
    assert len(plans) == 1
    plan = plans[0]
    assert isinstance(plan, PlanResult)
    assert plan.product_code == "HG182T"
    assert plan.warning_type == "stockout"
    assert [m.equipment_code for m in plan.selected_machines] == ["zr03"]
    assert plan.total_contribution_capacity == 8000
    assert plan.remaining_capacity_gap == -4800  # 缺口 3200 - 贡献 8000
    assert interventions == []
