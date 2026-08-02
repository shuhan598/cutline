# 算法管道：净速率→Pending确认/活动事件→切回→本轮预警/方案→丝网/混料

import re
from datetime import datetime
from typing import cast

from app.core.candidate_machine.errors import CandidateMachineCalculationError
from app.core.candidate_machine.overflow_candidate_finder import OverflowCandidateFinder
from app.core.candidate_machine.stockout_candidate_finder import StockoutCandidateFinder
from app.core.cutline_confirmation.pending_cutline_detector import (
    PendingCutlineDetectionError,
    PendingCutlineDetector,
)
from app.core.cutline_confirmation.pending_cutline_plan_factory import (
    PendingCutlinePlanFactory,
)
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
from app.schemas.pending_cutline_schema import (
    PendingCutlinePlan,
    PendingCutlinePlanStatus,
)
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
    AlgorithmStockoutCutlinePlan,
    AlgorithmStockoutWarningResult,
    ConfirmedCutlineTransition,
    PendingCutlinePlanEvaluation,
)
from app.service.persistence_state_builder import PersistenceStateBuilder
from app.utils.time_utils import normalize_local_time


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
        self._pending_detector = PendingCutlineDetector()
        self._pending_plan_factory = PendingCutlinePlanFactory()
        self._return = ReturnEvaluator()
        self._active_event_tracker = ActiveCutlineEventTracker()
        self._silk_transition = SilkScreenOrderTransitionPlanner()
        self._mixing_trace = MixingTraceCalculator()
        self._persistence_state_builder = PersistenceStateBuilder()

    def evaluate_algorithm(
        self,
        snapshot: AlgorithmSnapshot,
    ) -> AlgorithmEvaluateResult:
        net_rate_results = cast(
            list[AlgorithmIntervalNetRateResult],
            self._net_rate.calculate(snapshot),
        )
        errors: list[AlgorithmPipelineError] = []

        confirmed_transitions: list[ConfirmedCutlineTransition] = []
        plan_evaluations: list[PendingCutlinePlanEvaluation] = []
        if snapshot.pending_cutline_plans:
            try:
                confirmation_batch = self._pending_detector.detect(
                    snapshot=snapshot,
                    interval_results=net_rate_results,
                )
                confirmed_transitions = confirmation_batch.transitions
                plan_evaluations = confirmation_batch.plan_evaluations
            except PendingCutlineDetectionError as error:
                errors.append(
                    AlgorithmPipelineError(
                        stage="pending_cutline_confirmation",
                        warning_type=None,
                        warning_key=None,
                        reason="pending_cutline_detection_error",
                        message=str(error),
                    )
                )

        created_events, creation_errors = (
            self._create_confirmed_active_cutline_events(
                snapshot=snapshot,
                transitions=confirmed_transitions,
            )
        )
        errors.extend(creation_errors)
        (
            merged_events,
            accepted_existing_events,
            new_active_cutline_events,
            merge_errors,
        ) = self._merge_active_cutline_events(
            existing_events=snapshot.active_cutline_events,
            new_events=created_events,
        )
        errors.extend(merge_errors)
        merged_events = self._normalize_return_watermark(
            events=merged_events,
            return_suggested_event_ids=(
                snapshot.return_suggested_event_ids
            ),
        )
        accepted_existing_events = self._normalize_return_watermark(
            events=accepted_existing_events,
            return_suggested_event_ids=(
                snapshot.return_suggested_event_ids
            ),
        )
        new_active_cutline_events = self._normalize_return_watermark(
            events=new_active_cutline_events,
            return_suggested_event_ids=(
                snapshot.return_suggested_event_ids
            ),
        )
        plan_evaluations = self._reconcile_plan_evaluations(
            snapshot=snapshot,
            evaluations=plan_evaluations,
            accepted_new_events=new_active_cutline_events,
        )

        return_snapshot = snapshot.model_copy(
            update={"active_cutline_events": merged_events},
            deep=True,
        )
        return_results, return_errors = self._evaluate_return_events(
            snapshot=return_snapshot,
            interval_results=net_rate_results,
        )
        errors.extend(return_errors)
        new_active_cutline_events = self._apply_return_state(
            events=new_active_cutline_events,
            return_results=return_results,
            preserve_without_result=True,
        )
        updated_active_cutline_events = self._apply_return_state(
            events=accepted_existing_events,
            return_results=return_results,
            preserve_without_result=False,
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

        active_states = self._apply_return_state(
            events=merged_events,
            return_results=return_results,
            preserve_without_result=True,
        )
        tracked_keys = self._tracked_business_keys(
            snapshot=snapshot,
            active_events=active_states,
        )
        cutline_decisions = self._filter_equivalent_automatic_decisions(
            decisions=cutline_decisions,
            tracked_keys=tracked_keys,
        )
        new_pending_plans: list[PendingCutlinePlan] = []
        for decision in cutline_decisions:
            if decision.plan is None:
                continue
            try:
                pending_plan = self._pending_plan_factory.create(
                    snapshot,
                    decision,
                )
            except (ValueError, TypeError, OverflowError) as error:
                plan = decision.plan
                errors.append(
                    self._decision_error(
                        "pending_cutline_creation",
                        plan.warning_type,
                        plan.plan_id,
                        error,
                    )
                )
                continue
            if pending_plan is not None:
                new_pending_plans.append(pending_plan)

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

        (
            mixing_trace_records,
            mixing_trace_failures,
            successful_mixed_event_ids,
        ) = (
            self._calculate_mixing_traces(
                snapshot=snapshot,
                active_events=active_states,
                mixed_cutline_event_ids=(
                    snapshot.mixed_cutline_event_ids
                ),
            )
        )

        persistence_state = self._persistence_state_builder.build(
            incoming_pending_plans=snapshot.pending_cutline_plans,
            plan_evaluations=plan_evaluations,
            new_pending_plans=new_pending_plans,
            active_cutline_events=active_states,
            input_return_suggested_event_ids=(
                snapshot.return_suggested_event_ids
            ),
            input_mixed_cutline_event_ids=snapshot.mixed_cutline_event_ids,
            return_results=return_results,
            new_mixing_trace_records=mixing_trace_records,
            successful_mixed_event_ids=successful_mixed_event_ids,
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
            persistence_state=persistence_state,
        )

    def _reconcile_plan_evaluations(
        self,
        *,
        snapshot: AlgorithmSnapshot,
        evaluations: list[PendingCutlinePlanEvaluation],
        accepted_new_events: list[AlgorithmActiveCutlineEvent],
    ) -> list[PendingCutlinePlanEvaluation]:
        plan_by_id = {
            plan.plan_id: plan for plan in snapshot.pending_cutline_plans
        }
        accepted_codes_by_plan: dict[str, set[str]] = {}
        for event in accepted_new_events:
            if event.plan_id is not None:
                accepted_codes_by_plan.setdefault(event.plan_id, set()).add(
                    event.machine_code
                )

        terminal_statuses = {
            PendingCutlinePlanStatus.CONFIRMED,
            PendingCutlinePlanStatus.EXPIRED,
            PendingCutlinePlanStatus.RETURN_SUGGESTED,
        }
        reconciled: list[PendingCutlinePlanEvaluation] = []
        for evaluation in evaluations:
            plan = plan_by_id.get(evaluation.plan_id)
            if plan is None or plan.status in terminal_statuses:
                reconciled.append(evaluation)
                continue
            detector_new_codes = set(evaluation.new_confirmed_machine_codes)
            accepted_new_codes = detector_new_codes & accepted_codes_by_plan.get(
                evaluation.plan_id,
                set(),
            )
            confirmed_codes = (
                set(evaluation.confirmed_machine_codes)
                - detector_new_codes
            ) | accepted_new_codes
            required_confirmations = abs(
                evaluation.expected_machine_count
                - evaluation.before_machine_count
            )
            if len(confirmed_codes) >= required_confirmations:
                status = PendingCutlinePlanStatus.CONFIRMED
            elif normalize_local_time(snapshot.current_time) >= (
                normalize_local_time(plan.expire_at)
            ):
                status = PendingCutlinePlanStatus.EXPIRED
            elif confirmed_codes:
                status = PendingCutlinePlanStatus.PARTIALLY_CONFIRMED
            else:
                status = PendingCutlinePlanStatus.PENDING
            reconciled.append(
                evaluation.model_copy(
                    update={
                        "status": status,
                        "confirmed_machine_codes": sorted(confirmed_codes),
                        "new_confirmed_machine_codes": sorted(
                            accepted_new_codes
                        ),
                    },
                    deep=True,
                )
            )
        return reconciled

    def _create_confirmed_active_cutline_events(
        self,
        *,
        snapshot: AlgorithmSnapshot,
        transitions: list[ConfirmedCutlineTransition],
    ) -> tuple[
        list[AlgorithmActiveCutlineEvent],
        list[AlgorithmPipelineError],
    ]:
        unique_transitions, errors = self._unique_transitions(transitions)
        plan_by_id = {
            plan.plan_id: plan for plan in snapshot.pending_cutline_plans
        }
        events: list[AlgorithmActiveCutlineEvent] = []
        for transition in unique_transitions:
            plan = plan_by_id.get(transition.plan_id)
            if plan is None:
                errors.append(
                    AlgorithmPipelineError(
                        stage="active_event_creation",
                        warning_type=transition.warning_type,
                        warning_key=(
                            f"{transition.plan_id}:"
                            f"{transition.machine_code}"
                        ),
                        reason="pending_plan_not_found",
                        message=(
                            f"plan_id={transition.plan_id}, machine_code="
                            f"{transition.machine_code}: pending plan not found"
                        ),
                    )
                )
                continue
            try:
                event = self._event_from_transition(
                    transition=transition,
                    plan=plan,
                )
            except (ValueError, TypeError, OverflowError) as error:
                errors.append(
                    AlgorithmPipelineError(
                        stage="active_event_creation",
                        warning_type=transition.warning_type,
                        warning_key=(
                            f"{transition.plan_id}:"
                            f"{transition.machine_code}"
                        ),
                        reason="active_event_creation_error",
                        message=str(error),
                    )
                )
                continue
            events.append(event)
        return events, errors

    def _event_from_transition(
        self,
        *,
        transition: ConfirmedCutlineTransition,
        plan: PendingCutlinePlan,
    ) -> AlgorithmActiveCutlineEvent:
        return self._active_event_tracker.create_event(
            event_id=(
                f"CUT-{transition.plan_id}-{transition.machine_code}"
            ),
            plan_id=transition.plan_id,
            warning_id=transition.warning_id,
            machine_code=transition.machine_code,
            source_order_code=transition.source_order_code,
            target_order_code=transition.target_order_code,
            workshop_code=transition.workshop_code,
            source_buffer_code=transition.source_buffer_code,
            target_buffer_code=transition.target_buffer_code,
            upstream_process_code=(
                transition.target_upstream_process_code
            ),
            downstream_process_code=(
                transition.target_downstream_process_code
            ),
            source_wafer_size=transition.source_wafer_size,
            source_wafer_spec=transition.source_wafer_spec,
            target_wafer_size=transition.target_wafer_size,
            target_wafer_spec=transition.target_wafer_spec,
            cutline_start_time=transition.cutline_start_time,
            contribution_capacity=None,
            warning_type=transition.warning_type,
            process_code=transition.process_code,
            warning_buffer_code=plan.buffer_code,
            warning_upstream_process_code=plan.upstream_process_code,
            warning_downstream_process_code=plan.downstream_process_code,
            is_recommended_candidate=(
                transition.is_recommended_candidate
            ),
        )

    def _unique_transitions(
        self,
        transitions: list[ConfirmedCutlineTransition],
    ) -> tuple[
        list[ConfirmedCutlineTransition],
        list[AlgorithmPipelineError],
    ]:
        identities = [
            (
                self._transition_event_id(transition),
                (
                    transition.machine_code,
                    normalize_local_time(transition.cutline_start_time),
                ),
            )
            for transition in transitions
        ]
        unique: list[ConfirmedCutlineTransition] = []
        errors: list[AlgorithmPipelineError] = []
        for indexes in self._identity_components(identities):
            group = [transitions[index] for index in indexes]
            first = group[0]
            if all(item == first for item in group[1:]):
                unique.append(first)
                continue
            errors.append(
                self._active_event_conflict_error(
                    event_ids=[
                        self._transition_event_id(item) for item in group
                    ],
                    machine_codes=[item.machine_code for item in group],
                    cutline_start_times=[
                        item.cutline_start_time for item in group
                    ],
                    business_values=[
                        repr(item.model_dump(mode="json")) for item in group
                    ],
                )
            )
        return unique, errors

    @staticmethod
    def _transition_event_id(
        transition: ConfirmedCutlineTransition,
    ) -> str:
        return f"CUT-{transition.plan_id}-{transition.machine_code}"

    def _merge_active_cutline_events(
        self,
        *,
        existing_events: list[AlgorithmActiveCutlineEvent],
        new_events: list[AlgorithmActiveCutlineEvent],
    ) -> tuple[
        list[AlgorithmActiveCutlineEvent],
        list[AlgorithmActiveCutlineEvent],
        list[AlgorithmActiveCutlineEvent],
        list[AlgorithmPipelineError],
    ]:
        tagged_events = [
            *((False, event) for event in existing_events),
            *((True, event) for event in new_events),
        ]
        identities = [
            (
                event.event_id,
                (
                    event.machine_code,
                    normalize_local_time(event.cutline_start_time),
                ),
            )
            for _, event in tagged_events
        ]
        merged: list[AlgorithmActiveCutlineEvent] = []
        accepted_existing: list[AlgorithmActiveCutlineEvent] = []
        accepted_new: list[AlgorithmActiveCutlineEvent] = []
        errors: list[AlgorithmPipelineError] = []
        for indexes in self._identity_components(identities):
            group = [tagged_events[index] for index in indexes]
            first_is_new, first = group[0]
            if all(
                self._same_event_business(first, event)
                for _, event in group[1:]
            ):
                merged.append(first)
                if first_is_new:
                    accepted_new.append(first)
                else:
                    accepted_existing.append(first)
                continue
            group_events = [event for _, event in group]
            errors.append(
                self._active_event_conflict_error(
                    event_ids=[event.event_id for event in group_events],
                    machine_codes=[
                        event.machine_code for event in group_events
                    ],
                    cutline_start_times=[
                        event.cutline_start_time for event in group_events
                    ],
                    business_values=[
                        repr(event.model_dump(mode="json"))
                        for event in group_events
                    ],
                )
            )
        return merged, accepted_existing, accepted_new, errors

    @staticmethod
    def _identity_components(
        identities: list[tuple[str, tuple[str, datetime]]],
    ) -> list[list[int]]:
        parents = list(range(len(identities)))

        def find(index: int) -> int:
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        def union(left: int, right: int) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parents[right_root] = left_root

        event_index: dict[str, int] = {}
        physical_index: dict[tuple[str, datetime], int] = {}
        for index, (event_id, physical_key) in enumerate(identities):
            previous_event = event_index.setdefault(event_id, index)
            union(index, previous_event)
            previous_physical = physical_index.setdefault(
                physical_key, index
            )
            union(index, previous_physical)

        components: dict[int, list[int]] = {}
        for index in range(len(identities)):
            components.setdefault(find(index), []).append(index)
        return sorted(components.values(), key=lambda item: item[0])

    @staticmethod
    def _same_event_business(
        left: AlgorithmActiveCutlineEvent,
        right: AlgorithmActiveCutlineEvent,
    ) -> bool:
        excluded_alias_fields = {"event_id"}
        return left.model_dump(
            exclude=excluded_alias_fields
        ) == (
            right.model_dump(
                exclude=excluded_alias_fields
            )
        )

    @staticmethod
    def _active_event_conflict_error(
        *,
        event_ids: list[str],
        machine_codes: list[str],
        cutline_start_times: list[datetime],
        business_values: list[str],
    ) -> AlgorithmPipelineError:
        left_id = event_ids[0]
        right_id = event_ids[-1]
        return AlgorithmPipelineError(
            stage="active_event_merge",
            warning_type=None,
            warning_key=f"{left_id}:{right_id}",
            reason="active_event_identity_conflict",
            message=(
                f"conflicting active cutline identity group: event_ids="
                f"{event_ids!r}, machine_codes={machine_codes!r}, "
                f"cutline_start_times="
                f"{[item.isoformat() for item in cutline_start_times]!r}, "
                f"business_values={business_values!r}"
            ),
        )

    def _apply_return_state(
        self,
        *,
        events: list[AlgorithmActiveCutlineEvent],
        return_results: list[AlgorithmReturnResult],
        preserve_without_result: bool,
    ) -> list[AlgorithmActiveCutlineEvent]:
        result_by_event_id = {
            result.event_id: result for result in return_results
        }
        updated_events: list[AlgorithmActiveCutlineEvent] = []
        for event in events:
            result = result_by_event_id.get(event.event_id)
            if result is None:
                if preserve_without_result:
                    updated_events.append(event)
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

    def _tracked_business_keys(
        self,
        *,
        snapshot: AlgorithmSnapshot,
        active_events: list[AlgorithmActiveCutlineEvent],
    ) -> set[tuple[str, str, str, str, str, str]]:
        current_time = normalize_local_time(snapshot.current_time)
        keys = {
            self._pending_business_key(plan)
            for plan in snapshot.pending_cutline_plans
            if plan.status.value in {"PENDING", "PARTIALLY_CONFIRMED"}
            and current_time < normalize_local_time(plan.expire_at)
        }
        for event in active_events:
            key = self._active_event_business_key(event)
            if key is not None:
                keys.add(key)
        return keys

    @staticmethod
    def _pending_business_key(
        plan: PendingCutlinePlan,
    ) -> tuple[str, str, str, str, str, str]:
        return (
            plan.warning_type,
            plan.workshop_code,
            plan.buffer_code,
            plan.upstream_process_code,
            plan.downstream_process_code,
            plan.monitored_order_code,
        )

    @staticmethod
    def _active_event_business_key(
        event: AlgorithmActiveCutlineEvent,
    ) -> tuple[str, str, str, str, str, str] | None:
        if (
            event.status != "active"
            or event.plan_id is None
            or event.warning_id is None
            or event.warning_type is None
            or event.process_code is None
            or event.warning_buffer_code is None
            or event.warning_upstream_process_code is None
            or event.warning_downstream_process_code is None
            or event.is_recommended_candidate is None
        ):
            return None
        monitored_order_code = (
            event.target_order_code
            if event.warning_type == "stockout"
            else event.source_order_code
        )
        return (
            event.warning_type,
            event.workshop_code,
            event.warning_buffer_code,
            event.warning_upstream_process_code,
            event.warning_downstream_process_code,
            monitored_order_code,
        )

    def _filter_equivalent_automatic_decisions(
        self,
        *,
        decisions: list[AlgorithmCutlineDecisionResult],
        tracked_keys: set[tuple[str, str, str, str, str, str]],
    ) -> list[AlgorithmCutlineDecisionResult]:
        filtered: list[AlgorithmCutlineDecisionResult] = []
        for decision in decisions:
            key = self._decision_business_key(decision)
            if key is not None and key in tracked_keys:
                continue
            filtered.append(decision)
        return filtered

    @staticmethod
    def _decision_business_key(
        decision: AlgorithmCutlineDecisionResult,
    ) -> tuple[str, str, str, str, str, str] | None:
        plan = decision.plan
        if plan is None:
            return None
        monitored_order_code = (
            plan.order_code
            if isinstance(plan, AlgorithmStockoutCutlinePlan)
            else plan.source_order_code
        )
        return (
            plan.warning_type,
            plan.workshop_code,
            plan.buffer_code,
            plan.upstream_process_code,
            plan.downstream_process_code,
            monitored_order_code,
        )

    def _evaluate_return_events(
        self,
        *,
        snapshot: AlgorithmSnapshot,
        interval_results: list[AlgorithmIntervalNetRateResult],
    ) -> tuple[list[AlgorithmReturnResult], list[AlgorithmPipelineError]]:
        results: list[AlgorithmReturnResult] = []
        errors: list[AlgorithmPipelineError] = []
        for event in snapshot.active_cutline_events:
            if (
                event.status != "active"
                or event.event_id
                in snapshot.return_suggested_event_ids
            ):
                continue
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
        *,
        snapshot: AlgorithmSnapshot,
        active_events: list[AlgorithmActiveCutlineEvent],
        mixed_cutline_event_ids: list[str],
    ) -> tuple[
        list[AlgorithmMixingTraceRecord],
        list[AlgorithmMixingTraceFailure],
        list[str],
    ]:
        records: list[AlgorithmMixingTraceRecord] = []
        failures: list[AlgorithmMixingTraceFailure] = []
        successful_event_ids: list[str] = []
        mixed_event_id_set = set(mixed_cutline_event_ids)
        for event in active_events:
            if (
                event.event_id in mixed_event_id_set
                or not self._is_complete_mixing_event(event)
            ):
                continue
            batch = self._mixing_trace.calculate_for_event(
                snapshot=snapshot,
                event=event,
            )
            records.extend(batch.records)
            failures.extend(batch.failures)
            if batch.records:
                successful_event_ids.append(event.event_id)

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
        return records, failures, sorted(set(successful_event_ids))

    @staticmethod
    def _is_complete_mixing_event(
        event: AlgorithmActiveCutlineEvent,
    ) -> bool:
        return (
            event.status in {"active", "return_recommended"}
            and event.plan_id is not None
            and event.warning_id is not None
            and event.process_code is not None
            and bool(event.process_code.strip())
            and event.is_recommended_candidate is not None
        )

    def _normalize_return_watermark(
        self,
        *,
        events: list[AlgorithmActiveCutlineEvent],
        return_suggested_event_ids: list[str],
    ) -> list[AlgorithmActiveCutlineEvent]:
        suggested_ids = set(return_suggested_event_ids)
        return [
            self._active_event_tracker.mark_return_recommended(event=event)
            if event.status == "active" and event.event_id in suggested_ids
            else event
            for event in events
        ]

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
