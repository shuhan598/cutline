# 算法管道：按序串联净速率→耗尽→预警→候选，持有同一 snapshot 上下文

from dataclasses import dataclass
from typing import List, Optional

from app.core.candidate_machine.candidate_machine_finder import CandidateMachineFinder
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RateStrategy, RealtimeFirstRateStrategy
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)
from app.core.warning.stockout_warning import StockoutWarningEvaluator
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import (
    CandidateResult,
    DepletionResult,
    NetRateResult,
    StockoutWarningResult,
)


@dataclass
class PipelineResult:
    net_rates: List[NetRateResult]
    depletions: List[DepletionResult]
    warnings: List[StockoutWarningResult]
    candidates: List[CandidateResult]


class CutlinePipeline:
    """轻量编排：构建一次组件，run 时按序流转结果。"""

    def __init__(self, rate_strategy: Optional[RateStrategy] = None):
        strategy = rate_strategy or RealtimeFirstRateStrategy()
        self._net_rate = NetRateCalculator(strategy)
        self._depletion = DepletionTimeCalculator()
        self._warning = StockoutWarningEvaluator()
        self._candidate = CandidateMachineFinder(strategy)

    def run(self, snapshot: CutlineSnapshot) -> PipelineResult:
        net_rates = self._net_rate.calculate(snapshot)
        depletions = self._depletion.calculate(snapshot, net_rates)
        warnings = self._warning.evaluate(snapshot, depletions)
        candidates = self._candidate.find(snapshot, warnings)
        return PipelineResult(net_rates, depletions, warnings, candidates)
