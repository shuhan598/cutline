# 算法管道：按序串联净速率→耗尽→断料/溢满预警→候选→逐台选取→丝网→切回

import re
from datetime import timedelta
from typing import cast

from app.core.candidate_machine.errors import CandidateMachineCalculationError
from app.core.candidate_machine.overflow_candidate_finder import OverflowCandidateFinder
from app.core.candidate_machine.stockout_candidate_finder import StockoutCandidateFinder
from app.core.cutline_plan.errors import MachineSelectionEvaluationError
from app.core.cutline_plan.machine_selection_evaluator import (
    MachineSelectionEvaluator,
)
from app.core.cutline_plan.plan_builder import CutlinePlanBuilder
from app.core.mixing_trace.mixing_trace_calculator import MixingTraceCalculator
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)
from app.core.prediction_time.overflow_time.overflow_time_calculator import (
    OverflowTimeCalculator,
)
from app.core.return_judge.return_evaluator import (
    ReturnEvaluationError,
    ReturnEvaluator,
)
from app.core.return_judge.active_cutline_event_tracker import (
    ActiveCutlineEventTracker,
)
from app.core.silk_screen.errors import SilkScreenTransitionCalculationError
from app.core.silk_screen.order_transition_planner import (
    SilkScreenOrderTransitionPlanner,
)
from app.core.warning.overflow_warning import OverflowWarningEvaluator
from app.core.warning.stockout_warning import StockoutWarningEvaluator
from app.schemas.common_schema import AlgorithmActiveCutlineEvent
from app.schemas.request_schema import AlgorithmSnapshot
from app.schemas.result_schema import (
    AlgorithmBufferOverflowTimeResult,
    AlgorithmCutlineDecisionResult,
    AlgorithmEvaluateResult,
    AlgorithmIntervalNetRateResult,
    AlgorithmMixingTraceFailure,
    AlgorithmMixingTraceRecord,
    AlgorithmOverflowWarningResult,
    AlgorithmPipelineError,
    AlgorithmReturnResult,
    AlgorithmSilkScreenTransitionResult,
    AlgorithmStockoutWarningResult,
)


class CutlinePipeline:
    """轻量编排：构建一次组件，通过 evaluate_algorithm 编排结果。"""

    def __init__(self):
        self._net_rate = NetRateCalculator()
        self._depletion = DepletionTimeCalculator()
        self._stockout = StockoutWarningEvaluator()
        self._candidate = StockoutCandidateFinder()
        self._overflow_time = OverflowTimeCalculator()
        self._overflow = OverflowWarningEvaluator()
        self._overflow_candidate = OverflowCandidateFinder()
        self._selection = MachineSelectionEvaluator()
        self._plan_builder = CutlinePlanBuilder()
        self._return = ReturnEvaluator()
        self._active_event_tracker = ActiveCutlineEventTracker()
        self._silk_transition = SilkScreenOrderTransitionPlanner()
        self._mixing_trace = MixingTraceCalculator()

    def evaluate_algorithm(
        self,
        snapshot: AlgorithmSnapshot,
    ) -> AlgorithmEvaluateResult:
        net_rate_results = cast(
            list[AlgorithmIntervalNetRateResult],
            self._net_rate.calculate(snapshot),
        )
        depletion_results = self._depletion.calculate_algorithm(net_rate_results)
        overflow_time_results = self._overflow_time.calculate_algorithm(
            snapshot,
            net_rate_results,
        )
        stockout_warnings = self._stockout.evaluate_algorithm(
            snapshot,
            depletion_results,
        )
        overflow_warnings = self._overflow.evaluate_algorithm(
            snapshot,
            overflow_time_results,
        )

        cutline_decisions: list[AlgorithmCutlineDecisionResult] = []
        errors: list[AlgorithmPipelineError] = []
        for warning in stockout_warnings:
            decision, error = self._build_stockout_decision(
                snapshot,
                warning,
                net_rate_results,
                overflow_time_results,
            )
            if decision is not None:
                cutline_decisions.append(decision)
            if error is not None:
                errors.append(error)

        for warning in overflow_warnings:
            decision, error = self._build_overflow_decision(
                snapshot,
                warning,
                net_rate_results,
                overflow_time_results,
            )
            if decision is not None:
                cutline_decisions.append(decision)
            if error is not None:
                errors.append(error)

        new_active_cutline_events, active_event_errors = (
            self._create_active_cutline_events(
                snapshot=snapshot,
                decisions=cutline_decisions,
            )
        )
        errors.extend(active_event_errors)

        return_results, return_errors = self._evaluate_return_events(
            snapshot=snapshot,
            interval_results=net_rate_results,
        )
        errors.extend(return_errors)
        updated_active_cutline_events = self._updated_active_cutline_events(
            input_events=snapshot.active_cutline_events,
            return_results=return_results,
        )

        try:
            silk_screen_results = self._silk_transition.evaluate(
                snapshot=snapshot,
            )
        except SilkScreenTransitionCalculationError as error:
            silk_screen_results = []
            errors.append(
                AlgorithmPipelineError(
                    stage="silk_screen_transition",
                    warning_type=None,
                    warning_key=None,
                    reason="silk_screen_transition_calculation_error",
                    message=str(error),
                )
            )

        mixing_trace_records, mixing_trace_failures = (
            self._calculate_mixing_traces(
                snapshot,
                cutline_decisions,
            )
        )

        return AlgorithmEvaluateResult(
            calculation_time=snapshot.current_time,
            net_rate_results=net_rate_results,
            depletion_results=depletion_results,
            overflow_time_results=overflow_time_results,
            stockout_warnings=stockout_warnings,
            overflow_warnings=overflow_warnings,
            cutline_decisions=cutline_decisions,
            return_results=return_results,
            new_active_cutline_events=new_active_cutline_events,
            updated_active_cutline_events=updated_active_cutline_events,
            silk_screen_results=silk_screen_results,
            mixing_trace_records=mixing_trace_records,
            mixing_trace_failures=mixing_trace_failures,
            errors=errors,
        )

    def _create_active_cutline_events(
        self,
        *,
        snapshot: AlgorithmSnapshot,
        decisions: list[AlgorithmCutlineDecisionResult],
    ) -> tuple[
        list[AlgorithmActiveCutlineEvent],
        list[AlgorithmPipelineError],
    ]:
        events: list[AlgorithmActiveCutlineEvent] = []
        errors: list[AlgorithmPipelineError] = []
        for decision in decisions:
            plan = decision.plan
            if plan is None:
                continue
            for selected_machine in plan.selected_machines:
                machine_code = selected_machine.machine_code
                try:
                    event = self._active_event_tracker.create_event(
                        event_id=f"CUT-{plan.plan_id}-{machine_code}",
                        plan_id=plan.plan_id,
                        machine_code=machine_code,
                        source_order_code=(
                            selected_machine.source_order_code
                        ),
                        target_order_code=(
                            selected_machine.target_order_code
                        ),
                        workshop_code=selected_machine.workshop_code,
                        source_buffer_code=(
                            selected_machine.source_buffer_code
                        ),
                        target_buffer_code=(
                            selected_machine.target_buffer_code
                        ),
                        upstream_process_code=(
                            plan.upstream_process_code
                        ),
                        downstream_process_code=(
                            plan.downstream_process_code
                        ),
                        source_wafer_size=selected_machine.wafer_size,
                        source_wafer_spec=(
                            selected_machine.source_wafer_spec
                        ),
                        target_wafer_size=selected_machine.wafer_size,
                        target_wafer_spec=(
                            selected_machine.target_wafer_spec
                        ),
                        cutline_start_time=(
                            plan.calculation_time
                            + timedelta(
                                minutes=(
                                    snapshot.config
                                    .cutline_execution_delay_minutes
                                )
                            )
                        ),
                        contribution_capacity=(
                            selected_machine.contribution_capacity
                            if selected_machine.contribution_capacity
                            is not None
                            else selected_machine.reduced_capacity
                        ),
                        warning_type=plan.warning_type,
                    )
                except (ValueError, TypeError, OverflowError) as error:
                    errors.append(
                        AlgorithmPipelineError(
                            stage="active_event_creation",
                            warning_type=plan.warning_type,
                            warning_key=(
                                f"{plan.plan_id}:{machine_code}"
                            ),
                            reason="active_event_creation_error",
                            message=str(error),
                        )
                    )
                    continue
                events.append(event)
        return events, errors

    def _updated_active_cutline_events(
        self,
        *,
        input_events: list[AlgorithmActiveCutlineEvent],
        return_results: list[AlgorithmReturnResult],
    ) -> list[AlgorithmActiveCutlineEvent]:
        result_by_event_id = {
            result.event_id: result for result in return_results
        }
        updated_events: list[AlgorithmActiveCutlineEvent] = []
        for event in input_events:
            result = result_by_event_id.get(event.event_id)
            if result is None:
                continue
            updated_event = (
                self._active_event_tracker.update_negative_start_time(
                    event=event,
                    negative_start_time=(
                        result.updated_negative_start_time
                    ),
                )
            )
            if result.updated_status == "return_recommended":
                updated_event = (
                    self._active_event_tracker.mark_return_recommended(
                        event=updated_event,
                    )
                )
            updated_events.append(updated_event)
        return updated_events

    def _evaluate_return_events(
        self,
        *,
        snapshot: AlgorithmSnapshot,
        interval_results: list[AlgorithmIntervalNetRateResult],
    ) -> tuple[list[AlgorithmReturnResult], list[AlgorithmPipelineError]]:
        results: list[AlgorithmReturnResult] = []
        errors: list[AlgorithmPipelineError] = []
        for event in snapshot.active_cutline_events:
            event_snapshot = snapshot.model_copy(
                update={"active_cutline_events": [event]}
            )
            try:
                results.extend(
                    self._return.evaluate_algorithm(
                        snapshot=event_snapshot,
                        interval_results=interval_results,
                    )
                )
            except ReturnEvaluationError as error:
                errors.append(
                    AlgorithmPipelineError(
                        stage="return_evaluation",
                        warning_type=None,
                        warning_key=event.event_id,
                        reason=error.reason,
                        message=str(error),
                    )
                )
        return results, errors

    def _calculate_mixing_traces(
        self,
        snapshot: AlgorithmSnapshot,
        decisions: list[AlgorithmCutlineDecisionResult],
    ) -> tuple[
        list[AlgorithmMixingTraceRecord],
        list[AlgorithmMixingTraceFailure],
    ]:
        records: list[AlgorithmMixingTraceRecord] = []
        failures: list[AlgorithmMixingTraceFailure] = []
        for decision in decisions:
            batch = self._mixing_trace.calculate_for_decision(
                snapshot=snapshot,
                decision=decision,
            )
            records.extend(batch.records)
            failures.extend(batch.failures)

        records.sort(
            key=lambda item: (
                item.mix_start_time,
                item.machine_code,
                item.cutline_event_id,
            )
        )
        failures.sort(
            key=lambda item: (item.machine_code, item.cutline_event_id)
        )
        return records, failures

    def _build_stockout_decision(
        self,
        snapshot: AlgorithmSnapshot,
        warning: AlgorithmStockoutWarningResult,
        interval_results: list[AlgorithmIntervalNetRateResult],
        overflow_results: list[AlgorithmBufferOverflowTimeResult],
    ) -> tuple[AlgorithmCutlineDecisionResult | None, AlgorithmPipelineError | None]:
        warning_key = self._stockout_warning_key(warning)
        try:
            candidate_result = self._candidate.find_algorithm(
                snapshot,
                [warning],
            )[0]
        except CandidateMachineCalculationError as error:
            return None, self._decision_error(
                "stockout_candidate",
                "stockout",
                warning_key,
                error,
            )

        try:
            selection_result = self._selection.select_stockout_machines(
                snapshot=snapshot,
                warning=warning,
                candidate_result=candidate_result,
                interval_results=interval_results,
                overflow_results=overflow_results,
            )
        except MachineSelectionEvaluationError as error:
            return None, self._decision_error(
                "stockout_selection",
                "stockout",
                warning_key,
                error,
            )

        try:
            decision = self._plan_builder.build_stockout_decision(
                snapshot,
                warning,
                selection_result,
            )
        except MemoryError:
            raise
        except Exception as error:
            return None, self._decision_error(
                "stockout_plan",
                "stockout",
                warning_key,
                error,
            )
        return decision, None

    def _build_overflow_decision(
        self,
        snapshot: AlgorithmSnapshot,
        warning: AlgorithmOverflowWarningResult,
        interval_results: list[AlgorithmIntervalNetRateResult],
        overflow_results: list[AlgorithmBufferOverflowTimeResult],
    ) -> tuple[AlgorithmCutlineDecisionResult | None, AlgorithmPipelineError | None]:
        warning_key = self._overflow_warning_key(warning)
        try:
            candidate_result = self._overflow_candidate.find_algorithm(
                snapshot,
                [warning],
                interval_results,
            )[0]
        except CandidateMachineCalculationError as error:
            return None, self._decision_error(
                "overflow_candidate",
                "overflow",
                warning_key,
                error,
            )

        try:
            selection_result = self._selection.select_overflow_machines(
                snapshot=snapshot,
                warning=warning,
                candidate_result=candidate_result,
                interval_results=interval_results,
                overflow_results=overflow_results,
            )
        except MachineSelectionEvaluationError as error:
            return None, self._decision_error(
                "overflow_selection",
                "overflow",
                warning_key,
                error,
            )

        try:
            decision = self._plan_builder.build_overflow_decision(
                snapshot,
                warning,
                selection_result,
            )
        except MemoryError:
            raise
        except Exception as error:
            return None, self._decision_error(
                "overflow_plan",
                "overflow",
                warning_key,
                error,
            )
        return decision, None

    @staticmethod
    def _stockout_warning_key(warning: AlgorithmStockoutWarningResult) -> str:
        return ":".join(
            (
                warning.buffer_code,
                warning.order_code,
                warning.wafer_size,
                warning.wafer_spec,
                warning.upstream_process_code,
                warning.downstream_process_code,
            )
        )

    @staticmethod
    def _overflow_warning_key(warning: AlgorithmOverflowWarningResult) -> str:
        return ":".join(
            (
                warning.buffer_code,
                warning.workshop_code,
                warning.upstream_process_code,
                warning.downstream_process_code,
            )
        )

    @staticmethod
    def _decision_error(
        stage: str,
        warning_type: str,
        warning_key: str,
        error: Exception,
    ) -> AlgorithmPipelineError:
        reason = re.sub(
            r"([a-z0-9])([A-Z])",
            r"\1_\2",
            type(error).__name__,
        ).lower()
        return AlgorithmPipelineError(
            stage=stage,
            warning_type=warning_type,
            warning_key=warning_key,
            reason=reason,
            message=str(error),
        )
