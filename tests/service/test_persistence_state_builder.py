from __future__ import annotations

import pytest

from app.schemas.pending_cutline_schema import PendingCutlinePlanStatus
from app.schemas.result_schema import PendingCutlinePlanEvaluation
from app.service.persistence_state_builder import (
    PersistenceStateBuildError,
    PersistenceStateBuilder,
)
from tests.core.cutline_confirmation.helpers import (
    CREATED_AT,
    MONITORED_ORDER,
    SOURCE_ORDER,
    make_active_event,
    make_stockout_plan,
)


def _evaluation(plan, *, status, confirmed_machine_codes):
    return PendingCutlinePlanEvaluation(
        plan_id=plan.plan_id,
        warning_id=plan.warning_id,
        status=status,
        before_machine_count=plan.before_machine_count,
        before_machine_codes=plan.before_machine_codes,
        current_machine_count=plan.expected_machine_count,
        current_machine_codes=["M1", "M2"],
        expected_machine_count=plan.expected_machine_count,
        expected_delta_direction=plan.expected_delta_direction,
        confirmed_machine_codes=confirmed_machine_codes,
        new_confirmed_machine_codes=confirmed_machine_codes,
    )


def _build(**updates):
    values = {
        "incoming_pending_plans": [],
        "plan_evaluations": [],
        "new_pending_plans": [],
        "active_cutline_events": [],
        "input_return_suggested_event_ids": [],
        "input_mixed_cutline_event_ids": [],
        "return_results": [],
        "new_mixing_trace_records": [],
        "successful_mixed_event_ids": [],
    }
    values.update(updates)
    return PersistenceStateBuilder().build(**values)


def test_builder_applies_confirmed_evaluation_and_emits_complete_state():
    plan = make_stockout_plan()
    event = make_active_event(
        plan_id=plan.plan_id,
        machine_code="M1",
        source_order_code=plan.source_order_code,
        target_order_code=plan.target_order_code,
        cutline_start_time=CREATED_AT,
    ).model_copy(update={"warning_id": plan.warning_id})

    state = _build(
        incoming_pending_plans=[plan],
        plan_evaluations=[
            _evaluation(
                plan,
                status=PendingCutlinePlanStatus.CONFIRMED,
                confirmed_machine_codes=["M1"],
            )
        ],
        active_cutline_events=[event],
        input_return_suggested_event_ids=["CUT-OLD-RETURN"],
        input_mixed_cutline_event_ids=["CUT-OLD-MIX"],
    )

    assert len(state.pending_cutline_plans) == 1
    updated = state.pending_cutline_plans[0]
    assert updated.status is PendingCutlinePlanStatus.CONFIRMED
    assert updated.confirmed_machine_codes == ["M1"]
    assert state.active_cutline_events == [event]
    assert state.completed_pending_plan_ids == [plan.plan_id]
    assert state.expired_pending_plan_ids == []
    assert state.return_suggested_event_ids == ["CUT-OLD-RETURN"]
    assert state.mixed_cutline_event_ids == ["CUT-OLD-MIX"]
    assert state.new_mixing_trace_records == []


def test_builder_keeps_partial_open_and_reports_expired_plan():
    partial = make_stockout_plan(
        plan_id="PLAN-PARTIAL",
        baseline_orders=(("M1", SOURCE_ORDER), ("M2", SOURCE_ORDER), ("M3", MONITORED_ORDER)),
        candidate_machine_codes=("M1", "M2"),
        before_machine_codes=("M3",),
        expected_machine_count=3,
    )
    expired = make_stockout_plan(plan_id="PLAN-EXPIRED")

    state = _build(
        incoming_pending_plans=[expired, partial],
        plan_evaluations=[
            _evaluation(
                partial,
                status=PendingCutlinePlanStatus.PARTIALLY_CONFIRMED,
                confirmed_machine_codes=["M1"],
            ),
            _evaluation(
                expired,
                status=PendingCutlinePlanStatus.EXPIRED,
                confirmed_machine_codes=[],
            ),
        ],
    )

    assert [plan.plan_id for plan in state.pending_cutline_plans] == [
        "PLAN-EXPIRED",
        "PLAN-PARTIAL",
    ]
    by_id = {plan.plan_id: plan for plan in state.pending_cutline_plans}
    assert by_id["PLAN-PARTIAL"].status is PendingCutlinePlanStatus.PARTIALLY_CONFIRMED
    assert by_id["PLAN-EXPIRED"].status is PendingCutlinePlanStatus.EXPIRED
    assert state.expired_pending_plan_ids == ["PLAN-EXPIRED"]
    assert state.completed_pending_plan_ids == []


def test_builder_preserves_terminal_plan_and_appends_new_pending_plan():
    terminal = make_stockout_plan(
        plan_id="PLAN-DONE",
        confirmed_machine_codes=("M1",),
        status=PendingCutlinePlanStatus.CONFIRMED,
    )
    new_plan = make_stockout_plan(plan_id="PLAN-NEW")

    state = _build(
        incoming_pending_plans=[terminal],
        plan_evaluations=[
            _evaluation(
                terminal,
                status=PendingCutlinePlanStatus.EXPIRED,
                confirmed_machine_codes=[],
            )
        ],
        new_pending_plans=[new_plan],
    )

    by_id = {plan.plan_id: plan for plan in state.pending_cutline_plans}
    assert by_id[terminal.plan_id] == terminal
    assert by_id[new_plan.plan_id] == new_plan
    assert state.completed_pending_plan_ids == [terminal.plan_id]


def test_builder_promotes_only_confirmed_plan_when_all_active_ids_are_returned():
    confirmed = make_stockout_plan(
        plan_id="PLAN-CONFIRMED",
        confirmed_machine_codes=("M1",),
        status=PendingCutlinePlanStatus.CONFIRMED,
    )
    partial = make_stockout_plan(
        plan_id="PLAN-PARTIAL",
        baseline_orders=(("M1", SOURCE_ORDER), ("M2", SOURCE_ORDER), ("M3", MONITORED_ORDER)),
        candidate_machine_codes=("M1", "M2"),
        confirmed_machine_codes=("M1",),
        before_machine_codes=("M3",),
        expected_machine_count=3,
        status=PendingCutlinePlanStatus.PARTIALLY_CONFIRMED,
    )
    confirmed_event = make_active_event(
        plan_id=confirmed.plan_id,
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=CREATED_AT,
    )
    partial_event = confirmed_event.model_copy(
        update={"event_id": "CUT-PARTIAL-M1", "plan_id": partial.plan_id}
    )

    state = _build(
        incoming_pending_plans=[partial, confirmed],
        active_cutline_events=[partial_event, confirmed_event],
        input_return_suggested_event_ids=[
            partial_event.event_id,
            confirmed_event.event_id,
        ],
    )

    by_id = {plan.plan_id: plan for plan in state.pending_cutline_plans}
    assert by_id[confirmed.plan_id].status is PendingCutlinePlanStatus.RETURN_SUGGESTED
    assert by_id[partial.plan_id].status is PendingCutlinePlanStatus.PARTIALLY_CONFIRMED
    assert state.completed_pending_plan_ids == [confirmed.plan_id]


def test_builder_accumulates_return_recommended_status_without_new_result():
    confirmed = make_stockout_plan(
        plan_id="PLAN-STATUS-RETURN",
        confirmed_machine_codes=("M1",),
        status=PendingCutlinePlanStatus.CONFIRMED,
    )
    event = make_active_event(
        plan_id=confirmed.plan_id,
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=CREATED_AT,
    ).model_copy(update={"status": "return_recommended"}, deep=True)

    state = _build(
        incoming_pending_plans=[confirmed],
        active_cutline_events=[event],
    )

    assert state.return_suggested_event_ids == [event.event_id]
    assert state.pending_cutline_plans[0].status is (
        PendingCutlinePlanStatus.RETURN_SUGGESTED
    )


def test_builder_accumulates_legacy_return_recommended_status() -> None:
    event = make_active_event(
        plan_id="PLAN-LEGACY",
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=CREATED_AT,
        include_plan_id=False,
    ).model_copy(
        update={
            "status": "return_recommended",
            "process_code": None,
            "is_recommended_candidate": None,
        },
        deep=True,
    )

    state = _build(active_cutline_events=[event])

    assert state.return_suggested_event_ids == [event.event_id]


def test_builder_rejects_duplicate_plan_id_instead_of_overwriting():
    first = make_stockout_plan(plan_id="PLAN-DUPLICATE")
    conflict = first.model_copy(update={"warning_id": "WARNING-OTHER"})

    with pytest.raises(PersistenceStateBuildError, match="PLAN-DUPLICATE"):
        _build(
            incoming_pending_plans=[first],
            new_pending_plans=[conflict],
        )


def test_builder_rejects_evaluation_that_conflicts_with_plan_baseline():
    plan = make_stockout_plan()
    invalid = _evaluation(
        plan,
        status=PendingCutlinePlanStatus.CONFIRMED,
        confirmed_machine_codes=["M-UNKNOWN"],
    )

    with pytest.raises(PersistenceStateBuildError, match="PLAN-STOCKOUT"):
        _build(
            incoming_pending_plans=[plan],
            plan_evaluations=[invalid],
        )
