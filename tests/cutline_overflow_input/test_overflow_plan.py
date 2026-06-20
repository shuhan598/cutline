from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.candidate_machine.overflow_candidate_finder import OverflowCandidateFinder
from app.core.cutline_plan.plan_builder import CutlinePlanBuilder
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.warning.overflow_warning import OverflowWarningEvaluator


OVERFLOW_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_overflow_input.json"


def build():
    snapshot = MockAdapter().load(OVERFLOW_INPUT_PATH)
    strategy = RealtimeFirstRateStrategy()
    net_rates = NetRateCalculator(strategy).calculate(snapshot)
    warnings = OverflowWarningEvaluator().evaluate(snapshot, net_rates)
    candidates = OverflowCandidateFinder(strategy).find(snapshot, warnings, net_rates)
    return CutlinePlanBuilder().build_overflow(snapshot, warnings, candidates, net_rates)


def test_overflow_plan_moves_zr_t1_to_hg182r_and_resolves_risk():
    plans, interventions = build()
    assert len(plans) == 1
    plan = plans[0]
    assert plan.warning_type == "overflow"
    assert plan.product_code == "HG182T"
    assert [m.equipment_code for m in plan.selected_machines] == ["zr_t1"]
    assert plan.selected_machines[0].target_product_code == "HG182R"
    assert interventions == []
