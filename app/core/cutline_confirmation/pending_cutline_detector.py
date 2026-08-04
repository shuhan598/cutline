"""Detect real cutline execution from AGV binding history."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from app.core.candidate_machine.candidate_context import CandidateContext
from app.core.candidate_machine.errors import CandidateMachineCalculationError
from app.core.workshop.machine_workshop_resolver import (
    MachineWorkshopResolutionError,
)
from app.schemas.common_schema import (
    AlgorithmActiveCutlineEvent,
    AlgorithmAgvRelation,
    AlgorithmOrder,
    AlgorithmProduct,
)
from app.schemas.pending_cutline_schema import (
    BaselineMachineBinding,
    PendingCandidateMachine,
    PendingCutlinePlan,
    PendingCutlinePlanStatus,
)
from app.schemas.request_schema import AlgorithmSnapshot
from app.schemas.result_schema import (
    AlgorithmIntervalNetRateResult,
    ConfirmedCutlineTransition,
    PendingCutlineDetectionBatchResult,
    PendingCutlinePlanEvaluation,
)
from app.utils.time_utils import normalize_local_time


class PendingCutlineDetectionError(ValueError):
    """Pending cutline data cannot be evaluated unambiguously."""


@dataclass(frozen=True)
class _Claim:
    transition: ConfirmedCutlineTransition
    binding_time: datetime


class PendingCutlineDetector:
    """Compare saved baselines with AGV history inside each plan window."""

    def detect(
        self,
        snapshot: AlgorithmSnapshot,
        interval_results: list[AlgorithmIntervalNetRateResult],
    ) -> PendingCutlineDetectionBatchResult:
        try:
            context = CandidateContext(snapshot)
        except CandidateMachineCalculationError as exc:
            raise PendingCutlineDetectionError(str(exc)) from exc

        history_by_machine = self._history_by_machine(snapshot)
        claims_by_plan: dict[str, list[_Claim]] = defaultdict(list)
        active_confirmed_by_plan: dict[str, set[str]] = defaultdict(set)
        remaining_slots_by_plan: dict[str, int] = {}

        plans = sorted(
            snapshot.pending_cutline_plans,
            key=lambda item: item.plan_id,
        )
        for plan in plans:
            if plan.status in {
                PendingCutlinePlanStatus.CONFIRMED,
                PendingCutlinePlanStatus.EXPIRED,
                PendingCutlinePlanStatus.RETURN_SUGGESTED,
            }:
                remaining_slots_by_plan[plan.plan_id] = 0
                continue
            baseline_by_machine = {
                item.machine_code: item
                for item in plan.baseline_machine_bindings
            }
            candidates_by_machine = {
                item.machine_code: item for item in plan.candidate_machines
            }
            machine_codes = [
                *sorted(candidates_by_machine),
                *sorted(set(baseline_by_machine) - set(candidates_by_machine)),
            ]
            known_confirmed = set(plan.confirmed_machine_codes)
            owned_active_codes = self._owned_active_codes(snapshot, plan)
            active_confirmed_by_plan[plan.plan_id].update(owned_active_codes)
            known_confirmed.update(owned_active_codes)
            required_confirmations = abs(
                plan.expected_machine_count - plan.before_machine_count
            )
            remaining_slots = max(
                0,
                required_confirmations - len(known_confirmed),
            )
            remaining_slots_by_plan[plan.plan_id] = remaining_slots
            if remaining_slots == 0:
                continue

            for machine_code in machine_codes:
                if machine_code in known_confirmed:
                    continue
                baseline = baseline_by_machine[machine_code]
                candidate = candidates_by_machine.get(machine_code)
                claim = self._first_claim(
                    snapshot=snapshot,
                    context=context,
                    plan=plan,
                    baseline=baseline,
                    candidate=candidate,
                    history=history_by_machine.get(machine_code, []),
                    interval_results=interval_results,
                )
                if claim is None:
                    continue
                if self._is_claimed_by_active_event(snapshot, claim):
                    continue
                claims_by_plan[plan.plan_id].append(claim)

        winning_claims = self._arbitrate_claims(
            claims_by_plan,
            remaining_slots_by_plan,
        )
        transitions = sorted(
            (claim.transition for claim in winning_claims),
            key=lambda item: (
                normalize_local_time(item.cutline_start_time),
                item.machine_code,
                item.plan_id,
            ),
        )
        winning_codes_by_plan: dict[str, set[str]] = defaultdict(set)
        for transition in transitions:
            winning_codes_by_plan[transition.plan_id].add(
                transition.machine_code
            )

        evaluations = [
            self._evaluate_plan(
                snapshot=snapshot,
                context=context,
                plan=plan,
                active_confirmed_codes=active_confirmed_by_plan[plan.plan_id],
                new_confirmed_codes=winning_codes_by_plan[plan.plan_id],
            )
            for plan in plans
        ]
        return PendingCutlineDetectionBatchResult(
            transitions=transitions,
            plan_evaluations=evaluations,
        )

    def _history_by_machine(
        self,
        snapshot: AlgorithmSnapshot,
    ) -> dict[str, list[AlgorithmAgvRelation]]:
        grouped: dict[str, list[AlgorithmAgvRelation]] = defaultdict(list)
        for relation in snapshot.agv_binding_history:
            grouped[relation.machine_code].append(relation)
        for relations in grouped.values():
            relations.sort(
                key=lambda item: (
                    normalize_local_time(item.binding_time),
                    item.order_code,
                    item.product_code,
                )
            )
        return grouped

    def _first_claim(
        self,
        *,
        snapshot: AlgorithmSnapshot,
        context: CandidateContext,
        plan: PendingCutlinePlan,
        baseline: BaselineMachineBinding,
        candidate: PendingCandidateMachine | None,
        history: list[AlgorithmAgvRelation],
        interval_results: list[AlgorithmIntervalNetRateResult],
    ) -> _Claim | None:
        created_at = normalize_local_time(plan.created_at)
        expire_at = normalize_local_time(plan.expire_at)
        snapshot_time = normalize_local_time(snapshot.current_time)
        for relation in history:
            binding_time = normalize_local_time(relation.binding_time)
            if not (
                created_at < binding_time <= expire_at
                and binding_time <= snapshot_time
            ):
                continue
            if (
                relation.order_code == baseline.order_code
                and relation.product_code == baseline.product_code
            ):
                continue
            self._validate_previous_product(plan, baseline, relation)
            transition = self._build_transition(
                context=context,
                plan=plan,
                baseline=baseline,
                candidate=candidate,
                relation=relation,
                interval_results=interval_results,
            )
            if transition is not None:
                return _Claim(
                    transition=transition,
                    binding_time=binding_time,
                )
        return None

    def _validate_previous_product(
        self,
        plan: PendingCutlinePlan,
        baseline: BaselineMachineBinding,
        relation: AlgorithmAgvRelation,
    ) -> None:
        previous_code = relation.previous_product_code
        if previous_code is None or not previous_code.strip():
            return
        if previous_code == baseline.product_code:
            return
        raise PendingCutlineDetectionError(
            f"plan_id={plan.plan_id}, warning_id={plan.warning_id}, "
            f"machine_code={baseline.machine_code}: previous product conflicts "
            f"with baseline; baseline_product_name={baseline.product_name}, "
            f"baseline_product_code={baseline.product_code}, "
            f"current_previous_product_name={relation.previous_product_name}, "
            f"current_previous_product_code={previous_code}, "
            f"binding_time={relation.binding_time.isoformat()}, "
            f"created_at={plan.created_at.isoformat()}, "
            f"expire_at={plan.expire_at.isoformat()}"
        )

    def _build_transition(
        self,
        *,
        context: CandidateContext,
        plan: PendingCutlinePlan,
        baseline: BaselineMachineBinding,
        candidate: PendingCandidateMachine | None,
        relation: AlgorithmAgvRelation,
        interval_results: list[AlgorithmIntervalNetRateResult],
    ) -> ConfirmedCutlineTransition | None:
        self._validate_machine_scope(context, plan, baseline)
        self._validate_persisted_buffer_code(
            context=context,
            plan=plan,
            buffer_code=plan.buffer_code,
            expected_order_code=plan.monitored_order_code,
            role="warning",
        )
        if candidate is not None:
            recommended = self._recommended_transition(
                context,
                plan,
                baseline,
                candidate,
                relation,
            )
            if recommended is not None:
                return recommended
        if plan.warning_type == "stockout":
            transition = self._nonrecommended_stockout_transition(
                context,
                plan,
                baseline,
                relation,
                interval_results,
            )
        else:
            transition = self._nonrecommended_overflow_transition(
                context,
                plan,
                baseline,
                relation,
                interval_results,
            )
        if candidate is not None and transition is not None:
            return transition.model_copy(
                update={"is_recommended_candidate": True}
            )
        return transition

    def _validate_machine_scope(
        self,
        context: CandidateContext,
        plan: PendingCutlinePlan,
        baseline: BaselineMachineBinding,
    ) -> None:
        machine = context.machine_by_code.get(baseline.machine_code)
        if machine is None:
            raise PendingCutlineDetectionError(
                f"plan_id={plan.plan_id}, warning_id={plan.warning_id}, "
                f"machine_code={baseline.machine_code}: machine master missing"
            )
        try:
            workshop_code = context.workshop_resolver.resolve_machine_workshop(
                machine
            )
        except MachineWorkshopResolutionError as exc:
            raise PendingCutlineDetectionError(
                f"plan_id={plan.plan_id}, warning_id={plan.warning_id}, "
                f"machine_code={baseline.machine_code}: {exc}"
            ) from exc
        if (
            machine.process_code
            != (plan.process_code or plan.upstream_process_code)
            or workshop_code != plan.workshop_code
            or baseline.process_code != machine.process_code
            or baseline.workshop_code != workshop_code
        ):
            raise PendingCutlineDetectionError(
                f"plan_id={plan.plan_id}, warning_id={plan.warning_id}, "
                f"machine_code={baseline.machine_code}: machine scope conflicts "
                f"with process/workshop baseline=({baseline.process_code}, "
                f"{baseline.workshop_code}), current=({machine.process_code}, "
                f"{workshop_code}), plan=({plan.process_code or plan.upstream_process_code}, "
                f"{plan.workshop_code})"
            )

    def _recommended_transition(
        self,
        context: CandidateContext,
        plan: PendingCutlinePlan,
        baseline: BaselineMachineBinding,
        candidate: PendingCandidateMachine,
        relation: AlgorithmAgvRelation,
    ) -> ConfirmedCutlineTransition | None:
        if (
            relation.order_code != candidate.expected_target_order_code
            or relation.product_code != candidate.expected_target_product_code
        ):
            return None
        if candidate.source_buffer_code is not None:
            self._validate_persisted_buffer_code(
                context=context,
                plan=plan,
                buffer_code=candidate.source_buffer_code,
                expected_order_code=baseline.order_code,
                role="source",
            )
        self._validate_persisted_buffer_code(
            context=context,
            plan=plan,
            buffer_code=candidate.target_buffer_code,
            expected_order_code=candidate.expected_target_order_code,
            role="target",
        )
        return self._transition(
            plan=plan,
            baseline=baseline,
            relation=relation,
            target_order_code=candidate.expected_target_order_code,
            source_buffer_code=candidate.source_buffer_code,
            target_buffer_code=candidate.target_buffer_code,
            target_upstream_process_code=(
                candidate.target_upstream_process_code
            ),
            target_downstream_process_code=(
                candidate.target_downstream_process_code
            ),
            target_wafer_size=candidate.expected_target_wafer_size,
            target_wafer_spec=relation.wafer_spec,
            is_recommended_candidate=True,
        )

    def _validate_persisted_buffer_code(
        self,
        *,
        context: CandidateContext,
        plan: PendingCutlinePlan,
        buffer_code: str,
        expected_order_code: str,
        role: str,
    ) -> None:
        batch = context.main_buffer_batch
        if not batch.groups_by_group_key:
            return
        group_key = batch.group_key_by_buffer_code.get(buffer_code)
        group = batch.groups_by_group_key.get(group_key)
        if (
            group is None
            or group.order_code != expected_order_code
            or group.workshop_code != plan.workshop_code
        ):
            raise PendingCutlineDetectionError(
                f"plan_id={plan.plan_id}, warning_id={plan.warning_id}: "
                f"{role} buffer_code {buffer_code} cannot be uniquely "
                "located in the current main Buffer batch"
            )

    def _nonrecommended_stockout_transition(
        self,
        context: CandidateContext,
        plan: PendingCutlinePlan,
        baseline: BaselineMachineBinding,
        relation: AlgorithmAgvRelation,
        interval_results: list[AlgorithmIntervalNetRateResult],
    ) -> ConfirmedCutlineTransition | None:
        if (
            baseline.order_code == plan.monitored_order_code
            or relation.order_code != plan.monitored_order_code
        ):
            return None
        target_order, target_product = self._order_product(
            context,
            plan,
            baseline.machine_code,
            relation.order_code,
        )
        if relation.product_code != target_order.product_code:
            return None
        source_buffer_code = self._resolve_source_buffer(
            plan,
            baseline,
            interval_results,
        )
        return self._transition(
            plan=plan,
            baseline=baseline,
            relation=relation,
            target_order_code=relation.order_code,
            source_buffer_code=source_buffer_code,
            target_buffer_code=plan.buffer_code,
            target_upstream_process_code=plan.upstream_process_code,
            target_downstream_process_code=plan.downstream_process_code,
            target_wafer_size=target_product.wafer_size,
            target_wafer_spec=relation.wafer_spec,
            is_recommended_candidate=False,
        )

    def _nonrecommended_overflow_transition(
        self,
        context: CandidateContext,
        plan: PendingCutlinePlan,
        baseline: BaselineMachineBinding,
        relation: AlgorithmAgvRelation,
        interval_results: list[AlgorithmIntervalNetRateResult],
    ) -> ConfirmedCutlineTransition | None:
        if (
            baseline.order_code != plan.monitored_order_code
            or relation.order_code == plan.monitored_order_code
        ):
            return None
        target_order, target_product = self._order_product(
            context,
            plan,
            baseline.machine_code,
            relation.order_code,
        )
        if relation.product_code != target_order.product_code:
            return None
        target_interval = self._resolve_overflow_target(
            plan,
            relation,
            target_product.wafer_size,
            interval_results,
        )
        return self._transition(
            plan=plan,
            baseline=baseline,
            relation=relation,
            target_order_code=relation.order_code,
            source_buffer_code=plan.buffer_code,
            target_buffer_code=target_interval.buffer_code,
            target_upstream_process_code=target_interval.upstream_process_code,
            target_downstream_process_code=(
                target_interval.downstream_process_code
            ),
            target_wafer_size=target_product.wafer_size,
            target_wafer_spec=relation.wafer_spec,
            is_recommended_candidate=False,
        )

    def _order_product(
        self,
        context: CandidateContext,
        plan: PendingCutlinePlan,
        machine_code: str,
        order_code: str,
    ) -> tuple[AlgorithmOrder, AlgorithmProduct]:
        try:
            return context.order_product(order_code)
        except CandidateMachineCalculationError as exc:
            raise PendingCutlineDetectionError(
                f"plan_id={plan.plan_id}, warning_id={plan.warning_id}, "
                f"machine_code={machine_code}: {exc}"
            ) from exc

    def _resolve_source_buffer(
        self,
        plan: PendingCutlinePlan,
        baseline: BaselineMachineBinding,
        interval_results: list[AlgorithmIntervalNetRateResult],
    ) -> str | None:
        matches = [
            item
            for item in interval_results
            if item.order_code == baseline.order_code
            and item.wafer_size == baseline.wafer_size
            and item.wafer_spec == baseline.wafer_spec
            and item.workshop_code == plan.workshop_code
            and item.upstream_process_code == plan.upstream_process_code
        ]
        identities = {
            (
                item.buffer_code,
                item.upstream_process_code,
                item.downstream_process_code,
            )
            for item in matches
        }
        if len(identities) > 1:
            labels = ["/".join(identity) for identity in sorted(identities)]
            raise PendingCutlineDetectionError(
                f"plan_id={plan.plan_id}, warning_id={plan.warning_id}, "
                f"machine_code={baseline.machine_code}: source interval is "
                f"ambiguous for order={baseline.order_code}; "
                f"intervals={', '.join(labels)}"
            )
        if not matches:
            return None
        first = matches[0]
        if any(item != first for item in matches[1:]):
            identity = (
                first.buffer_code,
                first.upstream_process_code,
                first.downstream_process_code,
            )
            raise PendingCutlineDetectionError(
                f"plan_id={plan.plan_id}, warning_id={plan.warning_id}, "
                f"machine_code={baseline.machine_code}: duplicate source "
                f"interval business records conflict for order="
                f"{baseline.order_code}, interval={'/'.join(identity)}"
            )
        return first.buffer_code

    def _resolve_overflow_target(
        self,
        plan: PendingCutlinePlan,
        relation: AlgorithmAgvRelation,
        target_wafer_size: str,
        interval_results: list[AlgorithmIntervalNetRateResult],
    ) -> AlgorithmIntervalNetRateResult:
        matches = [
            item
            for item in interval_results
            if item.order_code == relation.order_code
            and item.wafer_size == target_wafer_size
            and item.wafer_spec == relation.wafer_spec
            and item.workshop_code == plan.workshop_code
            and item.upstream_process_code == plan.upstream_process_code
            and item.buffer_code != plan.buffer_code
            and plan.buffer_code not in item.buffer_codes
        ]
        identities = {
            (
                item.buffer_code,
                item.upstream_process_code,
                item.downstream_process_code,
            )
            for item in matches
        }
        if len(identities) > 1:
            labels = ["/".join(identity) for identity in sorted(identities)]
            raise PendingCutlineDetectionError(
                f"plan_id={plan.plan_id}, warning_id={plan.warning_id}, "
                f"machine_code={relation.machine_code}: target interval is "
                f"ambiguous for order={relation.order_code}; "
                f"intervals={', '.join(labels)}"
            )
        if not matches:
            raise PendingCutlineDetectionError(
                f"plan_id={plan.plan_id}, warning_id={plan.warning_id}, "
                f"machine_code={relation.machine_code}: target interval is "
                f"missing for order={relation.order_code}"
            )
        first = matches[0]
        if any(item != first for item in matches[1:]):
            identity = (
                first.buffer_code,
                first.upstream_process_code,
                first.downstream_process_code,
            )
            raise PendingCutlineDetectionError(
                f"plan_id={plan.plan_id}, warning_id={plan.warning_id}, "
                f"machine_code={relation.machine_code}: duplicate target "
                f"interval business records conflict for order="
                f"{relation.order_code}, interval={'/'.join(identity)}"
            )
        return first

    def _transition(
        self,
        *,
        plan: PendingCutlinePlan,
        baseline: BaselineMachineBinding,
        relation: AlgorithmAgvRelation,
        target_order_code: str,
        source_buffer_code: str | None,
        target_buffer_code: str,
        target_upstream_process_code: str,
        target_downstream_process_code: str,
        target_wafer_size: str,
        target_wafer_spec: str,
        is_recommended_candidate: bool,
    ) -> ConfirmedCutlineTransition:
        return ConfirmedCutlineTransition(
            plan_id=plan.plan_id,
            warning_id=plan.warning_id,
            warning_type=plan.warning_type,
            machine_code=baseline.machine_code,
            source_order_code=baseline.order_code,
            target_order_code=target_order_code,
            workshop_code=plan.workshop_code,
            process_code=baseline.process_code,
            source_buffer_code=source_buffer_code,
            target_buffer_code=target_buffer_code,
            target_upstream_process_code=target_upstream_process_code,
            target_downstream_process_code=target_downstream_process_code,
            source_wafer_size=baseline.wafer_size,
            source_wafer_spec=baseline.wafer_spec,
            target_wafer_size=target_wafer_size,
            target_wafer_spec=target_wafer_spec,
            cutline_start_time=relation.binding_time,
            is_recommended_candidate=is_recommended_candidate,
        )

    def _owned_active_codes(
        self,
        snapshot: AlgorithmSnapshot,
        plan: PendingCutlinePlan,
    ) -> set[str]:
        baseline_by_code = {
            baseline.machine_code: baseline
            for baseline in plan.baseline_machine_bindings
        }
        machine_by_stable_id = {
            f"CUT-{plan.plan_id}-{machine_code}": machine_code
            for machine_code in baseline_by_code
        }
        result: set[str] = set()
        for event in snapshot.active_cutline_events:
            stable_machine = machine_by_stable_id.get(event.event_id)
            if stable_machine is not None:
                if event.machine_code != stable_machine:
                    raise PendingCutlineDetectionError(
                        f"plan_id={plan.plan_id}, warning_id={plan.warning_id}: "
                        "stable event_id="
                        f"{event.event_id} requires machine_code="
                        f"{stable_machine}, got machine_code="
                        f"{event.machine_code}"
                    )
                machine_code = stable_machine
            elif event.plan_id == plan.plan_id:
                machine_code = event.machine_code
            else:
                continue
            baseline = baseline_by_code.get(machine_code)
            if baseline is None:
                raise PendingCutlineDetectionError(
                    f"plan_id={plan.plan_id}, warning_id={plan.warning_id}: "
                    "active event_id="
                    f"{event.event_id} has machine_code={event.machine_code} "
                    "outside baseline_machine_bindings"
                )
            self._validate_owned_active_event(
                plan=plan,
                baseline=baseline,
                event=event,
                stable_event_id=(stable_machine is not None),
            )
            result.add(machine_code)
        return result

    def _validate_owned_active_event(
        self,
        *,
        plan: PendingCutlinePlan,
        baseline: BaselineMachineBinding,
        event: AlgorithmActiveCutlineEvent,
        stable_event_id: bool,
    ) -> None:
        prefix = (
            f"plan_id={plan.plan_id}, warning_id={plan.warning_id}, "
            f"event_id={event.event_id}, machine_code={event.machine_code}: "
        )
        is_legacy = event.plan_id is None and event.warning_id is None
        if is_legacy:
            if not stable_event_id:
                raise PendingCutlineDetectionError(
                    prefix + "legacy active event requires the stable event_id"
                )
        elif (
            event.plan_id != plan.plan_id
            or event.warning_id != plan.warning_id
        ):
            raise PendingCutlineDetectionError(
                prefix
                + "active event identity conflicts with Pending: "
                f"event plan_id={event.plan_id!r}, "
                f"event warning_id={event.warning_id!r}"
            )

        if event.source_order_code != baseline.order_code:
            raise PendingCutlineDetectionError(
                prefix
                + "source_order_code conflicts with baseline: "
                f"expected={baseline.order_code!r}, "
                f"got={event.source_order_code!r}"
            )
        if plan.warning_type == "stockout":
            direction_is_valid = (
                baseline.order_code != plan.monitored_order_code
                and event.target_order_code == plan.monitored_order_code
            )
        else:
            direction_is_valid = (
                baseline.order_code == plan.monitored_order_code
                and event.target_order_code != plan.monitored_order_code
            )
        if not direction_is_valid:
            raise PendingCutlineDetectionError(
                prefix
                + f"{plan.warning_type} direction conflicts with Pending: "
                f"baseline_order_code={baseline.order_code!r}, "
                f"target_order_code={event.target_order_code!r}, "
                f"monitored_order_code={plan.monitored_order_code!r}"
            )

        observed_at = normalize_local_time(event.cutline_start_time)
        created_at = normalize_local_time(plan.created_at)
        expire_at = normalize_local_time(plan.expire_at)
        if not created_at < observed_at <= expire_at:
            raise PendingCutlineDetectionError(
                prefix
                + "observed cutline time is outside "
                "(created_at, expire_at]: "
                f"observed_at={event.cutline_start_time.isoformat()}, "
                f"created_at={plan.created_at.isoformat()}, "
                f"expire_at={plan.expire_at.isoformat()}"
            )

        if event.workshop_code != plan.workshop_code:
            raise PendingCutlineDetectionError(
                prefix
                + "workshop_code conflicts with Pending: "
                f"expected={plan.workshop_code!r}, "
                f"got={event.workshop_code!r}"
            )
        if (
            event.process_code is not None
            and event.process_code != baseline.process_code
        ):
            raise PendingCutlineDetectionError(
                prefix
                + "process_code conflicts with baseline: "
                f"expected={baseline.process_code!r}, "
                f"got={event.process_code!r}"
            )
        if (
            event.warning_type is not None
            and event.warning_type != plan.warning_type
        ):
            raise PendingCutlineDetectionError(
                prefix
                + "warning_type conflicts with Pending: "
                f"expected={plan.warning_type!r}, "
                f"got={event.warning_type!r}"
            )

    def _is_claimed_by_active_event(
        self,
        snapshot: AlgorithmSnapshot,
        claim: _Claim,
    ) -> bool:
        transition = claim.transition
        for event in snapshot.active_cutline_events:
            event_key = (
                event.machine_code,
                event.source_order_code,
                event.target_order_code,
                normalize_local_time(event.cutline_start_time),
            )
            if event_key != self._claim_switch_key(claim):
                continue
            if event.plan_id == transition.plan_id:
                return True
            raise PendingCutlineDetectionError(
                "active cutline event conflicts with pending claim: "
                f"plan_id={transition.plan_id}, "
                f"warning_id={transition.warning_id}, "
                f"active_plan_id={event.plan_id}, event_id={event.event_id}, "
                f"machine_code={transition.machine_code}, "
                f"source_order_code={transition.source_order_code}, "
                f"target_order_code={transition.target_order_code}, "
                f"observed_at={transition.cutline_start_time.isoformat()}"
            )
        return False

    def _arbitrate_claims(
        self,
        claims_by_plan: dict[str, list[_Claim]],
        remaining_slots_by_plan: dict[str, int],
    ) -> list[_Claim]:
        raw_claims = self._deduplicate_claims(
            [
                claim
                for plan_id in sorted(claims_by_plan)
                for claim in claims_by_plan[plan_id]
            ]
        )
        self._raise_claim_conflict(raw_claims)
        deduplicated_by_plan: dict[str, list[_Claim]] = defaultdict(list)
        for claim in raw_claims:
            deduplicated_by_plan[claim.transition.plan_id].append(claim)

        selected_recommended: list[_Claim] = []
        for plan_id in sorted(deduplicated_by_plan):
            candidates = sorted(
                (
                    claim
                    for claim in deduplicated_by_plan[plan_id]
                    if claim.transition.is_recommended_candidate
                ),
                key=self._claim_sort_key,
            )
            selected_recommended.extend(
                candidates[: remaining_slots_by_plan[plan_id]]
            )

        claimed_switches = {
            self._claim_switch_key(claim)
            for claim in selected_recommended
        }
        selected_count_by_plan: dict[str, int] = defaultdict(int)
        for claim in selected_recommended:
            selected_count_by_plan[claim.transition.plan_id] += 1

        fallback_slots_by_plan = {
            plan_id: max(
                0,
                remaining_slots_by_plan[plan_id]
                - selected_count_by_plan[plan_id],
            )
            for plan_id in deduplicated_by_plan
        }
        selected_fallback: list[_Claim] = []
        for plan_id in sorted(deduplicated_by_plan):
            fallback_slots = fallback_slots_by_plan[plan_id]
            if fallback_slots == 0:
                continue
            fallbacks = sorted(
                (
                    claim
                    for claim in deduplicated_by_plan[plan_id]
                    if not claim.transition.is_recommended_candidate
                    and self._claim_switch_key(claim)
                    not in claimed_switches
                ),
                key=self._claim_sort_key,
            )
            selected_fallback.extend(fallbacks[:fallback_slots])

        return [*selected_recommended, *selected_fallback]

    def _deduplicate_claims(self, claims: list[_Claim]) -> list[_Claim]:
        by_business_key: dict[
            tuple[str, str, str, str, str, datetime],
            _Claim,
        ] = {}
        for claim in claims:
            by_business_key.setdefault(self._claim_business_key(claim), claim)
        return list(by_business_key.values())

    def _raise_claim_conflict(
        self,
        claims: list[_Claim],
    ) -> None:
        claims_by_switch: dict[
            tuple[str, str, str, datetime],
            list[_Claim],
        ] = defaultdict(list)
        for claim in claims:
            claims_by_switch[self._claim_switch_key(claim)].append(claim)
        for switch_key, contenders in sorted(
            claims_by_switch.items(),
            key=lambda item: (item[0][3], item[0][0], item[0][1], item[0][2]),
        ):
            plan_ids = {item.transition.plan_id for item in contenders}
            if len(plan_ids) < 2:
                continue
            machine_code, source_order, target_order, _ = switch_key
            contexts = sorted(
                (
                    item.transition.plan_id,
                    item.transition.warning_id,
                )
                for item in contenders
            )
            raise PendingCutlineDetectionError(
                f"conflicting cutline claims for machine_code="
                f"{machine_code}, source_order_code={source_order}, "
                f"current_order_code={target_order}, "
                f"observed_at="
                f"{contenders[0].transition.cutline_start_time.isoformat()}, "
                f"claims={contexts!r}"
            )

    def _claim_switch_key(
        self,
        claim: _Claim,
    ) -> tuple[str, str, str, datetime]:
        transition = claim.transition
        return (
            transition.machine_code,
            transition.source_order_code,
            transition.target_order_code,
            claim.binding_time,
        )

    def _claim_business_key(
        self,
        claim: _Claim,
    ) -> tuple[str, str, str, str, str, datetime]:
        transition = claim.transition
        return (
            transition.plan_id,
            transition.warning_id,
            transition.machine_code,
            transition.source_order_code,
            transition.target_order_code,
            claim.binding_time,
        )

    def _claim_sort_key(self, claim: _Claim) -> tuple[datetime, str, str]:
        return (
            claim.binding_time,
            claim.transition.machine_code,
            claim.transition.plan_id,
        )

    def _evaluate_plan(
        self,
        *,
        snapshot: AlgorithmSnapshot,
        context: CandidateContext,
        plan: PendingCutlinePlan,
        active_confirmed_codes: set[str],
        new_confirmed_codes: set[str],
    ) -> PendingCutlinePlanEvaluation:
        current_codes = self._current_machine_codes(context, plan)
        if plan.status in {
            PendingCutlinePlanStatus.CONFIRMED,
            PendingCutlinePlanStatus.EXPIRED,
            PendingCutlinePlanStatus.RETURN_SUGGESTED,
        }:
            return PendingCutlinePlanEvaluation(
                plan_id=plan.plan_id,
                warning_id=plan.warning_id,
                status=plan.status,
                before_machine_count=plan.before_machine_count,
                before_machine_codes=sorted(plan.before_machine_codes),
                current_machine_count=len(current_codes),
                current_machine_codes=current_codes,
                expected_machine_count=plan.expected_machine_count,
                expected_delta_direction=plan.expected_delta_direction,
                confirmed_machine_codes=sorted(
                    plan.confirmed_machine_codes
                ),
                new_confirmed_machine_codes=[],
            )
        confirmed_codes = (
            set(plan.confirmed_machine_codes)
            | active_confirmed_codes
            | new_confirmed_codes
        )
        required_confirmations = abs(
            plan.expected_machine_count - plan.before_machine_count
        )
        if len(confirmed_codes) >= required_confirmations:
            status = PendingCutlinePlanStatus.CONFIRMED
        elif normalize_local_time(snapshot.current_time) >= normalize_local_time(
            plan.expire_at
        ):
            status = PendingCutlinePlanStatus.EXPIRED
        elif confirmed_codes:
            status = PendingCutlinePlanStatus.PARTIALLY_CONFIRMED
        else:
            status = PendingCutlinePlanStatus.PENDING
        return PendingCutlinePlanEvaluation(
            plan_id=plan.plan_id,
            warning_id=plan.warning_id,
            status=status,
            before_machine_count=plan.before_machine_count,
            before_machine_codes=sorted(plan.before_machine_codes),
            current_machine_count=len(current_codes),
            current_machine_codes=current_codes,
            expected_machine_count=plan.expected_machine_count,
            expected_delta_direction=plan.expected_delta_direction,
            confirmed_machine_codes=sorted(confirmed_codes),
            new_confirmed_machine_codes=sorted(new_confirmed_codes),
        )

    def _current_machine_codes(
        self,
        context: CandidateContext,
        plan: PendingCutlinePlan,
    ) -> list[str]:
        result: list[str] = []
        for machine_code, runtime in sorted(
            context.runtime_by_machine_code.items()
        ):
            if (
                runtime.status != "running"
                or runtime.current_order_code != plan.monitored_order_code
            ):
                continue
            machine = context.machine_by_code[machine_code]
            if machine.process_code != (
                plan.process_code or plan.upstream_process_code
            ):
                continue
            try:
                workshop_code = (
                    context.workshop_resolver.resolve_machine_workshop(machine)
                )
            except MachineWorkshopResolutionError as exc:
                raise PendingCutlineDetectionError(
                    f"plan_id={plan.plan_id}, warning_id={plan.warning_id}, "
                    f"machine_code={machine_code}: {exc}"
                ) from exc
            if workshop_code == plan.workshop_code:
                result.append(machine_code)
        return result
