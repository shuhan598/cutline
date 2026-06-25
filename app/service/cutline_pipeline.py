# 算法管道：按序串联净速率→耗尽→断料/溢满预警→候选→逐台选取→丝网→切回

from dataclasses import dataclass, field
from typing import List, Optional

from app.core.candidate_machine.overflow_candidate_finder import OverflowCandidateFinder
from app.core.candidate_machine.stockout_candidate_finder import StockoutCandidateFinder
from app.core.cutline_plan.plan_builder import CutlinePlanBuilder
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RateStrategy, RealtimeFirstRateStrategy
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)
from app.core.prediction_time.overflow_time.overflow_time_calculator import (
    OverflowTimeCalculator,
)
from app.core.return_judge.return_evaluator import ReturnEvaluator
from app.core.silk_screen.silk_screen_handler import SilkScreenHandler
from app.core.warning.overflow_warning import OverflowWarningEvaluator
from app.core.warning.stockout_warning import StockoutWarningEvaluator
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import (
    CandidateResult,
    DepletionResult,
    ManualInterventionResult,
    NetRateResult,
    OverflowWarningResult,
    PlanResult,
    ReturnResult,
    SilkScreenOrderResult,
    StockoutWarningResult,
)


@dataclass
class PipelineResult:
    net_rates: List[NetRateResult]
    depletions: List[DepletionResult]
    warnings: List[StockoutWarningResult]
    candidates: List[CandidateResult]
    overflow_warnings: List[OverflowWarningResult] = field(default_factory=list)
    plans: List[PlanResult] = field(default_factory=list)
    manual_interventions: List[ManualInterventionResult] = field(default_factory=list)
    silk_orders: List[SilkScreenOrderResult] = field(default_factory=list)
    return_results: List[ReturnResult] = field(default_factory=list)


class CutlinePipeline:
    """轻量编排：构建一次组件，run 时按序流转结果。"""

    def __init__(self, rate_strategy: Optional[RateStrategy] = None):
        strategy = rate_strategy or RealtimeFirstRateStrategy()
        self._net_rate = NetRateCalculator(strategy)
        self._depletion = DepletionTimeCalculator()
        self._stockout = StockoutWarningEvaluator()
        self._candidate = StockoutCandidateFinder(strategy)
        self._overflow_time = OverflowTimeCalculator()
        self._overflow = OverflowWarningEvaluator()
        self._overflow_candidate = OverflowCandidateFinder(strategy)
        self._plan_builder = CutlinePlanBuilder()
        self._silk = SilkScreenHandler()
        self._return = ReturnEvaluator()

    def run(self, snapshot: CutlineSnapshot) -> PipelineResult:
        net_rates = self._net_rate.calculate(snapshot)
        depletions = self._depletion.calculate(snapshot, net_rates)

        warnings = self._stockout.evaluate(snapshot, depletions)
        candidates = self._candidate.find(snapshot, warnings)

        overflow_time_results = self._overflow_time.calculate(snapshot, net_rates)
        overflow_warnings = self._overflow.evaluate(snapshot, overflow_time_results)
        overflow_candidates = self._overflow_candidate.find(
            snapshot, overflow_warnings, net_rates
        )

        silk_codes = self._silk.identify_silk_screen_processes(snapshot)
        stockout_plans, stockout_interventions = self._plan_builder.build_stockout(
            warnings, candidates, net_rates, depletions, silk_codes
        )
        overflow_plans, overflow_interventions = self._plan_builder.build_overflow(
            snapshot, overflow_warnings, overflow_candidates, net_rates
        )

        silk_orders = self._silk.evaluate_order_triggers(snapshot)
        return_results = self._return.evaluate(snapshot, net_rates, depletions)

        return PipelineResult(
            net_rates=net_rates,
            depletions=depletions,
            warnings=warnings,
            candidates=candidates,
            overflow_warnings=overflow_warnings,
            plans=stockout_plans + overflow_plans,
            manual_interventions=stockout_interventions + overflow_interventions,
            silk_orders=silk_orders,
            return_results=return_results,
        )
