from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.cutline_confirmation.pending_cutline_detector import (
    PendingCutlineDetector,
)
from app.schemas.result_schema import (
    AlgorithmCutlineDecisionResult,
    AlgorithmMixingTraceBatchResult,
    AlgorithmSelectedMachineEvaluation,
    AlgorithmStockoutCutlinePlan,
    AlgorithmStockoutWarningResult,
)
from app.service.cutline_pipeline import CutlinePipeline
from tests.core.cutline_confirmation.helpers import (
    ALTERNATE_BUFFER,
    ALTERNATE_ORDER,
    ALTERNATE_PRODUCT_NAME,
    CREATED_AT,
    CUT_PROCESS,
    DOWNSTREAM_PROCESS,
    MONITORED_ORDER,
    MONITORED_PRODUCT_NAME,
    NOW,
    SOURCE_BUFFER,
    SOURCE_ORDER,
    SOURCE_PRODUCT_NAME,
    WARNING_BUFFER,
    WORKSHOP,
    make_active_event,
    make_agv_binding,
    make_interval_result,
    make_overflow_plan,
    make_snapshot,
    make_stockout_plan,
)
from tests.core.cutline_plan.helpers import stockout_warning
from tests.core.mixing_trace.test_mixing_trace_calculator import (
    selected_machine,
    stockout_plan,
)


def _stub_non_confirmation_stages(
    monkeypatch,
    pipeline: CutlinePipeline,
    *,
    interval_results=(),
    stockout_warnings=(),
    stub_mixing=True,
) -> None:
    intervals = list(interval_results)
    warnings = list(stockout_warnings)
    monkeypatch.setattr(
        pipeline._net_rate,
        "calculate",
        lambda snapshot: intervals,
    )
    monkeypatch.setattr(
        pipeline._depletion,
        "calculate_algorithm",
        lambda results: [],
    )
    monkeypatch.setattr(
        pipeline._overflow_time,
        "calculate_algorithm",
        lambda snapshot, results: [],
    )
    monkeypatch.setattr(
        pipeline._stockout,
        "evaluate_algorithm",
        lambda snapshot, results: warnings,
    )
    monkeypatch.setattr(
        pipeline._overflow,
        "evaluate_algorithm",
        lambda snapshot, results: [],
    )
    monkeypatch.setattr(
        pipeline._silk_transition,
        "evaluate",
        lambda *, snapshot: [],
    )
    if stub_mixing:
        monkeypatch.setattr(
            pipeline._mixing_trace,
            "calculate_for_event",
            lambda *, snapshot, event: AlgorithmMixingTraceBatchResult(),
        )


def _confirmed_stockout_snapshot(*, active_events=()):
    plan = make_stockout_plan()
    binding_time = CREATED_AT + timedelta(minutes=3)
    changed = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        binding_time,
        previous_product_name=SOURCE_PRODUCT_NAME,
    )
    snapshot = make_snapshot(
        pending_plans=[plan],
        history=[changed],
        current_orders={"M1": MONITORED_ORDER, "M2": MONITORED_ORDER},
        active_events=list(active_events),
    )
    return snapshot, plan, binding_time


def _equivalent_stockout_warning():
    return AlgorithmStockoutWarningResult(
        warning_time=NOW,
        main_id=f"MAIN-{WARNING_BUFFER}",
        buffer_code=WARNING_BUFFER,
        buffer_codes=[WARNING_BUFFER],
        order_code=MONITORED_ORDER,
        wafer_size="210",
        wafer_spec="M10-P",
        workshop_code=WORKSHOP,
        upstream_process_code=CUT_PROCESS,
        downstream_process_code=DOWNSTREAM_PROCESS,
        current_quantity=100.0,
        upstream_output_rate=5.0,
        downstream_input_rate=10.0,
        net_consumption_rate=5.0,
        depletion_minutes=20.0,
        stockout_warning_lead_minutes=30.0,
    )


def _equivalent_stockout_decision(
    *,
    plan_id: str = "PLAN-CURRENT-ROUND",
) -> AlgorithmCutlineDecisionResult:
    machine = AlgorithmSelectedMachineEvaluation(
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        source_buffer_code=SOURCE_BUFFER,
        target_buffer_code=WARNING_BUFFER,
        process_code=CUT_PROCESS,
        workshop_code=WORKSHOP,
        wafer_size="210",
        source_wafer_spec="M10-P",
        target_wafer_spec="M10-P",
        contribution_capacity=120.0,
        utilization_rate=1.0,
        idle_rate=0.0,
        source_net_rate_before=5.0,
        source_net_rate_after=-115.0,
        source_depletion_minutes_after=1.0,
        target_net_rate_before=5.0,
        target_net_rate_after=-115.0,
        target_overflow_minutes_after=None,
    )
    plan = AlgorithmStockoutCutlinePlan(
        plan_id=plan_id,
        calculation_time=NOW,
        workshop_code=WORKSHOP,
        buffer_code=WARNING_BUFFER,
        order_code=MONITORED_ORDER,
        wafer_size="210",
        wafer_spec="M10-P",
        upstream_process_code=CUT_PROCESS,
        downstream_process_code=DOWNSTREAM_PROCESS,
        initial_capacity_gap=5.0,
        total_contribution_capacity=120.0,
        remaining_capacity_gap=0.0,
        selected_machines=[machine],
    )
    return AlgorithmCutlineDecisionResult(plan=plan, manual_intervention=None)


def _inject_equivalent_decision(
    monkeypatch,
    pipeline: CutlinePipeline,
    decision: AlgorithmCutlineDecisionResult,
) -> AlgorithmStockoutWarningResult:
    warning = _equivalent_stockout_warning()
    monkeypatch.setattr(
        pipeline._stockout,
        "evaluate_algorithm",
        lambda snapshot, results: [warning],
    )
    monkeypatch.setattr(
        pipeline,
        "_build_stockout_decision",
        lambda snapshot, warning, interval_results, overflow_results: (
            decision,
            None,
        ),
    )
    return warning


def test_confirmed_transition_creates_event_from_agv_time_with_plan_metadata(
    monkeypatch,
) -> None:
    snapshot, plan, binding_time = _confirmed_stockout_snapshot()
    pipeline = CutlinePipeline()
    _stub_non_confirmation_stages(
        monkeypatch,
        pipeline,
        interval_results=[
            make_interval_result(MONITORED_ORDER, WARNING_BUFFER)
        ],
        stub_mixing=False,
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert len(result.new_active_cutline_events) == 1
    event = result.new_active_cutline_events[0]
    assert event.event_id == f"CUT-{plan.plan_id}-M1"
    assert event.plan_id == plan.plan_id
    assert event.machine_code == "M1"
    assert event.source_order_code == SOURCE_ORDER
    assert event.target_order_code == MONITORED_ORDER
    assert event.workshop_code == WORKSHOP
    assert event.source_buffer_code == SOURCE_BUFFER
    assert event.target_buffer_code == WARNING_BUFFER
    assert event.upstream_process_code == CUT_PROCESS
    assert event.downstream_process_code == DOWNSTREAM_PROCESS
    assert event.source_wafer_size == "210"
    assert event.source_wafer_spec == "M10-P"
    assert event.target_wafer_size == "210"
    assert event.target_wafer_spec == "M10-P"
    assert event.cutline_start_time == binding_time
    assert event.negative_start_time is None
    assert event.status == "active"
    assert event.contribution_capacity is None
    assert event.warning_type == "stockout"
    assert event.warning_id == plan.warning_id
    assert event.process_code == CUT_PROCESS
    assert event.warning_buffer_code == WARNING_BUFFER
    assert event.warning_upstream_process_code == CUT_PROCESS
    assert event.warning_downstream_process_code == DOWNSTREAM_PROCESS
    assert event.is_recommended_candidate is True
    assert [item.event_id for item in result.return_results] == [event.event_id]
    assert result.persistence_state.pending_cutline_plans[0].status.value == (
        "CONFIRMED"
    )
    assert result.persistence_state.completed_pending_plan_ids == [plan.plan_id]
    persisted_event = result.persistence_state.active_cutline_events[0]
    assert persisted_event.event_id == event.event_id
    assert persisted_event.warning_id == plan.warning_id
    assert persisted_event.is_recommended_candidate is True
    assert persisted_event.status == event.status
    assert [
        item.cutline_event_id
        for item in result.persistence_state.new_mixing_trace_records
    ] == [event.event_id]
    assert result.persistence_state.mixed_cutline_event_ids == [event.event_id]


def test_customer_selected_machine_creates_event_with_optional_source_buffer(
    monkeypatch,
) -> None:
    plan = make_stockout_plan(
        baseline_orders=(
            ("M1", SOURCE_ORDER),
            ("M2", MONITORED_ORDER),
            ("M3", SOURCE_ORDER),
        ),
        candidate_machine_codes=("M1",),
    )
    changed = make_agv_binding(
        "M3",
        MONITORED_ORDER,
        CREATED_AT + timedelta(minutes=4),
        previous_product_name=SOURCE_PRODUCT_NAME,
    )
    snapshot = make_snapshot(
        pending_plans=[plan],
        history=[changed],
        current_orders={
            "M1": SOURCE_ORDER,
            "M2": MONITORED_ORDER,
            "M3": MONITORED_ORDER,
        },
    )
    pipeline = CutlinePipeline()
    _stub_non_confirmation_stages(
        monkeypatch,
        pipeline,
        interval_results=[
            make_interval_result(MONITORED_ORDER, WARNING_BUFFER)
        ],
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert len(result.new_active_cutline_events) == 1
    event = result.new_active_cutline_events[0]
    assert event.event_id == "CUT-PLAN-STOCKOUT-M3"
    assert event.source_buffer_code is None
    assert event.is_recommended_candidate is False
    assert [item.event_id for item in result.return_results] == [event.event_id]


def test_existing_and_new_events_are_merged_before_return_evaluation(
    monkeypatch,
) -> None:
    existing = make_active_event(
        plan_id="PLAN-EXISTING",
        machine_code="M3",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=CREATED_AT - timedelta(minutes=5),
    )
    snapshot, plan, _ = _confirmed_stockout_snapshot(
        active_events=[existing]
    )
    pipeline = CutlinePipeline()
    _stub_non_confirmation_stages(
        monkeypatch,
        pipeline,
        interval_results=[
            make_interval_result(MONITORED_ORDER, WARNING_BUFFER)
        ],
    )
    evaluated_ids: list[str] = []
    evaluate_return = pipeline._return.evaluate_algorithm

    def record_return(*, snapshot, interval_results):
        evaluated_ids.extend(
            event.event_id for event in snapshot.active_cutline_events
        )
        return evaluate_return(
            snapshot=snapshot,
            interval_results=interval_results,
        )

    monkeypatch.setattr(
        pipeline._return,
        "evaluate_algorithm",
        record_return,
    )

    result = pipeline.evaluate_algorithm(snapshot)

    expected_new_id = f"CUT-{plan.plan_id}-M1"
    assert evaluated_ids == [existing.event_id, expected_new_id]
    assert [item.event_id for item in result.return_results] == [
        existing.event_id,
        expected_new_id,
    ]
    assert [item.event_id for item in result.new_active_cutline_events] == [
        expected_new_id
    ]


def _evaluate_existing_event_merge(monkeypatch, events):
    pipeline = CutlinePipeline()
    _stub_non_confirmation_stages(monkeypatch, pipeline)
    evaluated_ids: list[str] = []

    def record_return(*, snapshot, interval_results):
        evaluated_ids.append(snapshot.active_cutline_events[0].event_id)
        return []

    monkeypatch.setattr(
        pipeline._return,
        "evaluate_algorithm",
        record_return,
    )
    result = pipeline.evaluate_algorithm(
        make_snapshot(pending_plans=[], active_events=list(events))
    )
    return result, evaluated_ids


def test_duplicate_existing_events_with_same_id_enter_return_once(
    monkeypatch,
) -> None:
    existing = make_active_event(
        plan_id="PLAN-EXISTING",
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=CREATED_AT,
    )

    result, evaluated_ids = _evaluate_existing_event_merge(
        monkeypatch,
        [existing, existing.model_copy(deep=True)],
    )

    assert evaluated_ids == [existing.event_id]
    assert result.errors == []


def test_duplicate_existing_events_with_different_ids_enter_return_once(
    monkeypatch,
) -> None:
    existing = make_active_event(
        plan_id="PLAN-EXISTING",
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=CREATED_AT,
    )
    duplicate = existing.model_copy(update={"event_id": "CUT-ALIAS-M1"})

    result, evaluated_ids = _evaluate_existing_event_merge(
        monkeypatch,
        [existing, duplicate],
    )

    assert evaluated_ids == [existing.event_id]
    assert result.errors == []


def test_conflicting_existing_events_with_same_id_report_merge_error(
    monkeypatch,
) -> None:
    existing = make_active_event(
        plan_id="PLAN-EXISTING",
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=CREATED_AT,
    )
    conflict = existing.model_copy(
        update={"target_buffer_code": ALTERNATE_BUFFER}
    )

    result, evaluated_ids = _evaluate_existing_event_merge(
        monkeypatch,
        [existing, conflict],
    )

    assert evaluated_ids == []
    assert result.return_results == []
    assert result.updated_active_cutline_events == []
    assert [
        (error.stage, error.reason, error.warning_key)
        for error in result.errors
    ] == [
        (
            "active_event_merge",
            "active_event_identity_conflict",
            f"{existing.event_id}:{conflict.event_id}",
        )
    ]


def test_conflicting_existing_events_with_same_physical_key_report_error(
    monkeypatch,
) -> None:
    existing = make_active_event(
        plan_id="PLAN-EXISTING",
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=CREATED_AT,
    )
    conflict = existing.model_copy(
        update={
            "event_id": "CUT-OTHER-M1",
            "target_buffer_code": ALTERNATE_BUFFER,
        }
    )

    result, evaluated_ids = _evaluate_existing_event_merge(
        monkeypatch,
        [existing, conflict],
    )

    assert evaluated_ids == []
    assert result.return_results == []
    assert result.updated_active_cutline_events == []
    assert [
        (error.stage, error.reason, error.warning_key)
        for error in result.errors
    ] == [
        (
            "active_event_merge",
            "active_event_identity_conflict",
            f"{existing.event_id}:{conflict.event_id}",
        )
    ]


def test_conflicting_existing_event_lifecycle_does_not_default_to_first(
    monkeypatch,
) -> None:
    existing = make_active_event(
        plan_id="PLAN-EXISTING",
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=CREATED_AT,
    )
    conflict = existing.model_copy(
        update={
            "event_id": "CUT-OTHER-M1",
            "negative_start_time": CREATED_AT + timedelta(minutes=1),
        }
    )

    result, evaluated_ids = _evaluate_existing_event_merge(
        monkeypatch,
        [existing, conflict],
    )

    assert evaluated_ids == []
    assert result.return_results == []
    assert result.updated_active_cutline_events == []
    assert [
        (error.stage, error.reason, error.warning_key)
        for error in result.errors
    ] == [
        (
            "active_event_merge",
            "active_event_identity_conflict",
            f"{existing.event_id}:{conflict.event_id}",
        )
    ]


def test_connected_existing_identity_conflict_quarantines_entire_group_once(
    monkeypatch,
) -> None:
    first = make_active_event(
        plan_id="PLAN-EXISTING",
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=CREATED_AT,
    )
    bridge = first.model_copy(
        update={
            "machine_code": "M2",
            "cutline_start_time": CREATED_AT + timedelta(minutes=1),
        }
    )
    tail = bridge.model_copy(update={"event_id": "CUT-TAIL-M2"})

    result, evaluated_ids = _evaluate_existing_event_merge(
        monkeypatch,
        [first, bridge, tail],
    )

    assert evaluated_ids == []
    assert result.return_results == []
    assert result.updated_active_cutline_events == []
    conflict_errors = [
        error
        for error in result.errors
        if error.reason == "active_event_identity_conflict"
    ]
    assert len(conflict_errors) == 1
    assert first.event_id in conflict_errors[0].message
    assert tail.event_id in conflict_errors[0].message


def test_quarantined_existing_events_do_not_suppress_equivalent_decision(
    monkeypatch,
) -> None:
    existing = make_active_event(
        plan_id="PLAN-EXISTING",
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=CREATED_AT,
    )
    conflict = existing.model_copy(
        update={"target_buffer_code": ALTERNATE_BUFFER}
    )
    decision = _equivalent_stockout_decision()
    snapshot = make_snapshot(
        pending_plans=[],
        active_events=[existing, conflict],
    )
    pipeline = CutlinePipeline()
    _stub_non_confirmation_stages(monkeypatch, pipeline)
    warning = _inject_equivalent_decision(monkeypatch, pipeline, decision)
    evaluated_ids: list[str] = []

    def record_return(*, snapshot, interval_results):
        evaluated_ids.extend(
            event.event_id for event in snapshot.active_cutline_events
        )
        return []

    monkeypatch.setattr(
        pipeline._return,
        "evaluate_algorithm",
        record_return,
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert evaluated_ids == []
    assert result.stockout_warnings == [warning]
    assert result.cutline_decisions == [decision]


def test_unconfirmed_pending_plan_never_enters_return_evaluation(
    monkeypatch,
) -> None:
    snapshot = make_snapshot(pending_plans=[make_stockout_plan()])
    pipeline = CutlinePipeline()
    _stub_non_confirmation_stages(monkeypatch, pipeline)
    detector = PendingCutlineDetector.detect
    detector_calls = 0

    def record_detection(self, snapshot, interval_results):
        nonlocal detector_calls
        detector_calls += 1
        return detector(
            self,
            snapshot=snapshot,
            interval_results=interval_results,
        )

    monkeypatch.setattr(PendingCutlineDetector, "detect", record_detection)
    monkeypatch.setattr(
        pipeline._return,
        "evaluate_algorithm",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("unconfirmed Pending must not enter ReturnEvaluator")
        ),
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert detector_calls == 1
    assert result.new_active_cutline_events == []
    assert result.return_results == []
    assert result.updated_active_cutline_events == []


def test_same_round_return_timer_is_applied_to_new_event_not_existing_updates(
    monkeypatch,
) -> None:
    snapshot, _, _ = _confirmed_stockout_snapshot()
    pipeline = CutlinePipeline()
    _stub_non_confirmation_stages(
        monkeypatch,
        pipeline,
        interval_results=[
            make_interval_result(
                MONITORED_ORDER,
                WARNING_BUFFER,
                net_consumption_rate=-5.0,
            )
        ],
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert len(result.return_results) == 1
    assert result.return_results[0].previous_negative_start_time is None
    assert result.return_results[0].updated_negative_start_time == NOW
    assert result.new_active_cutline_events[0].negative_start_time == NOW
    assert result.new_active_cutline_events[0].status == "active"
    assert result.updated_active_cutline_events == []


def test_pending_detection_error_is_reported_at_named_pipeline_stage(
    monkeypatch,
) -> None:
    conflict = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        CREATED_AT + timedelta(minutes=3),
        previous_product_name=ALTERNATE_PRODUCT_NAME,
    )
    snapshot = make_snapshot(
        pending_plans=[make_stockout_plan()],
        history=[conflict],
        current_orders={"M1": MONITORED_ORDER, "M2": MONITORED_ORDER},
    )
    pipeline = CutlinePipeline()
    _stub_non_confirmation_stages(monkeypatch, pipeline)

    result = pipeline.evaluate_algorithm(snapshot)

    assert result.new_active_cutline_events == []
    confirmation_errors = [
        error
        for error in result.errors
        if error.stage == "pending_cutline_confirmation"
    ]
    assert len(confirmation_errors) == 1
    assert "previous product conflicts" in confirmation_errors[0].message
    assert "PLAN-STOCKOUT" in confirmation_errors[0].message
    assert "M1" in confirmation_errors[0].message
    assert result.persistence_state.pending_cutline_plans == [
        snapshot.pending_cutline_plans[0]
    ]


def test_input_active_event_prevents_duplicate_confirmed_event(
    monkeypatch,
) -> None:
    binding_time = CREATED_AT + timedelta(minutes=3)
    existing = make_active_event(
        plan_id="PLAN-STOCKOUT",
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=binding_time,
    )
    snapshot, _, _ = _confirmed_stockout_snapshot(active_events=[existing])
    pipeline = CutlinePipeline()
    detector = PendingCutlineDetector.detect
    detector_calls = 0

    def record_detection(self, snapshot, interval_results):
        nonlocal detector_calls
        detector_calls += 1
        return detector(
            self,
            snapshot=snapshot,
            interval_results=interval_results,
        )

    monkeypatch.setattr(PendingCutlineDetector, "detect", record_detection)
    _stub_non_confirmation_stages(
        monkeypatch,
        pipeline,
        interval_results=[
            make_interval_result(MONITORED_ORDER, WARNING_BUFFER)
        ],
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert detector_calls == 1
    assert result.new_active_cutline_events == []
    assert [item.event_id for item in result.return_results] == [
        existing.event_id
    ]


def test_duplicate_transitions_in_current_batch_create_and_evaluate_once(
    monkeypatch,
) -> None:
    snapshot, _, _ = _confirmed_stockout_snapshot()
    interval_results = [
        make_interval_result(MONITORED_ORDER, WARNING_BUFFER)
    ]
    batch = PendingCutlineDetector().detect(
        snapshot=snapshot,
        interval_results=interval_results,
    )
    duplicate_batch = batch.model_copy(
        update={"transitions": [batch.transitions[0], batch.transitions[0]]},
        deep=True,
    )
    pipeline = CutlinePipeline()
    _stub_non_confirmation_stages(
        monkeypatch,
        pipeline,
        interval_results=interval_results,
    )
    monkeypatch.setattr(
        PendingCutlineDetector,
        "detect",
        lambda self, snapshot, interval_results: duplicate_batch,
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert len(result.new_active_cutline_events) == 1
    assert len(result.return_results) == 1
    assert result.new_active_cutline_events[0].event_id == (
        result.return_results[0].event_id
    )


def _evaluate_conflicting_transition_batch(
    monkeypatch,
    *,
    conflict_update,
):
    snapshot, _, _ = _confirmed_stockout_snapshot()
    interval_results = [
        make_interval_result(MONITORED_ORDER, WARNING_BUFFER)
    ]
    batch = PendingCutlineDetector().detect(
        snapshot=snapshot,
        interval_results=interval_results,
    )
    first = batch.transitions[0]
    conflict = first.model_copy(update=conflict_update)
    conflict_batch = batch.model_copy(
        update={"transitions": [first, conflict]},
        deep=True,
    )
    pipeline = CutlinePipeline()
    _stub_non_confirmation_stages(
        monkeypatch,
        pipeline,
        interval_results=interval_results,
    )
    monkeypatch.setattr(
        PendingCutlineDetector,
        "detect",
        lambda self, snapshot, interval_results: conflict_batch,
    )
    evaluated_ids: list[str] = []

    def record_return(*, snapshot, interval_results):
        evaluated_ids.extend(
            event.event_id for event in snapshot.active_cutline_events
        )
        return []

    monkeypatch.setattr(
        pipeline._return,
        "evaluate_algorithm",
        record_return,
    )

    result = pipeline.evaluate_algorithm(snapshot)
    return result, evaluated_ids, first, conflict


def test_conflicting_current_transitions_with_same_event_id_are_quarantined(
    monkeypatch,
) -> None:
    result, evaluated_ids, first, conflict = (
        _evaluate_conflicting_transition_batch(
            monkeypatch,
            conflict_update={"target_buffer_code": ALTERNATE_BUFFER},
        )
    )

    assert evaluated_ids == []
    assert result.new_active_cutline_events == []
    assert result.return_results == []
    assert [error.reason for error in result.errors] == [
        "active_event_identity_conflict"
    ]
    assert first.plan_id in result.errors[0].message
    assert conflict.machine_code in result.errors[0].message


def test_conflicting_current_transitions_with_same_physical_key_are_quarantined(
    monkeypatch,
) -> None:
    result, evaluated_ids, first, conflict = (
        _evaluate_conflicting_transition_batch(
            monkeypatch,
            conflict_update={
                "plan_id": "PLAN-OTHER",
                "warning_id": "WARNING-OTHER",
                "target_buffer_code": ALTERNATE_BUFFER,
            },
        )
    )

    assert evaluated_ids == []
    assert result.new_active_cutline_events == []
    assert result.return_results == []
    assert [error.reason for error in result.errors] == [
        "active_event_identity_conflict"
    ]
    assert first.plan_id in result.errors[0].message
    assert conflict.plan_id in result.errors[0].message


def _evaluate_existing_and_new_identity(
    monkeypatch,
    *,
    existing_update,
):
    snapshot, plan, _ = _confirmed_stockout_snapshot()
    interval_results = [
        make_interval_result(MONITORED_ORDER, WARNING_BUFFER)
    ]
    batch = PendingCutlineDetector().detect(
        snapshot=snapshot,
        interval_results=interval_results,
    )
    pipeline = CutlinePipeline()
    transition = batch.transitions[0]
    created = pipeline._event_from_transition(
        transition=transition,
        plan=plan,
    )
    existing = created.model_copy(update=existing_update)
    snapshot.active_cutline_events = [existing]
    _stub_non_confirmation_stages(
        monkeypatch,
        pipeline,
        interval_results=interval_results,
    )
    monkeypatch.setattr(
        PendingCutlineDetector,
        "detect",
        lambda self, snapshot, interval_results: batch,
    )
    evaluated_ids: list[str] = []

    def record_return(*, snapshot, interval_results):
        evaluated_ids.extend(
            event.event_id for event in snapshot.active_cutline_events
        )
        return []

    monkeypatch.setattr(
        pipeline._return,
        "evaluate_algorithm",
        record_return,
    )
    result = pipeline.evaluate_algorithm(snapshot)
    return result, evaluated_ids, existing, created


@pytest.mark.parametrize(
    "existing_update",
    ({}, {"event_id": "CUT-ALIAS-M1"}),
    ids=("same-event-id", "same-physical-alias"),
)
def test_equivalent_existing_and_new_events_fold_to_existing_once(
    monkeypatch,
    existing_update,
) -> None:
    result, evaluated_ids, existing, _ = _evaluate_existing_and_new_identity(
        monkeypatch,
        existing_update=existing_update,
    )

    assert evaluated_ids == [existing.event_id]
    assert result.new_active_cutline_events == []
    assert result.errors == []


@pytest.mark.parametrize(
    "existing_update",
    (
        {
            "plan_id": "PLAN-CONFLICT",
            "target_buffer_code": ALTERNATE_BUFFER,
        },
        {
            "event_id": "CUT-ALIAS-M1",
            "plan_id": "PLAN-CONFLICT",
            "target_buffer_code": ALTERNATE_BUFFER,
        },
    ),
    ids=("same-event-id", "same-physical-alias"),
)
def test_conflicting_existing_and_new_events_quarantine_both(
    monkeypatch,
    existing_update,
) -> None:
    result, evaluated_ids, _, _ = _evaluate_existing_and_new_identity(
        monkeypatch,
        existing_update=existing_update,
    )

    assert evaluated_ids == []
    assert result.new_active_cutline_events == []
    assert result.return_results == []
    assert result.updated_active_cutline_events == []
    assert [error.reason for error in result.errors] == [
        "active_event_identity_conflict"
    ]
    persisted = result.persistence_state.pending_cutline_plans[0]
    assert persisted.status.value == "PENDING"
    assert persisted.confirmed_machine_codes == []


@pytest.mark.parametrize(
    "expected_error",
    (
        ValueError("invalid confirmed event"),
        TypeError("invalid confirmed event"),
        OverflowError("invalid confirmed event"),
    ),
    ids=("value", "type", "overflow"),
)
def test_expected_confirmed_event_creation_errors_are_isolated(
    monkeypatch,
    expected_error,
) -> None:
    snapshot, _, _ = _confirmed_stockout_snapshot()
    pipeline = CutlinePipeline()
    _stub_non_confirmation_stages(monkeypatch, pipeline)
    monkeypatch.setattr(
        pipeline._active_event_tracker,
        "create_event",
        lambda **kwargs: (_ for _ in ()).throw(expected_error),
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert result.new_active_cutline_events == []
    assert result.return_results == []
    assert [
        (error.stage, error.reason, error.message)
        for error in result.errors
    ] == [
        (
            "active_event_creation",
            "active_event_creation_error",
            "invalid confirmed event",
        )
    ]
    persisted = result.persistence_state.pending_cutline_plans[0]
    assert persisted.status.value == "PENDING"
    assert persisted.confirmed_machine_codes == []


def test_unexpected_confirmed_event_creation_error_propagates(
    monkeypatch,
) -> None:
    snapshot, _, _ = _confirmed_stockout_snapshot()
    pipeline = CutlinePipeline()
    _stub_non_confirmation_stages(monkeypatch, pipeline)
    monkeypatch.setattr(
        pipeline._active_event_tracker,
        "create_event",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("tracker bug")),
    )

    with pytest.raises(RuntimeError, match="tracker bug"):
        pipeline.evaluate_algorithm(snapshot)


def test_live_equivalent_pending_suppresses_new_plan_but_keeps_warning(
    monkeypatch,
) -> None:
    snapshot = make_snapshot(pending_plans=[make_stockout_plan()])
    decision = _equivalent_stockout_decision()
    pipeline = CutlinePipeline()
    _stub_non_confirmation_stages(monkeypatch, pipeline)
    warning = _inject_equivalent_decision(monkeypatch, pipeline, decision)

    result = pipeline.evaluate_algorithm(snapshot)

    assert result.stockout_warnings == [warning]
    assert result.cutline_decisions == []
    assert result.new_active_cutline_events == []


def test_first_round_keeps_decision_and_creates_pending_without_active_event(
    monkeypatch,
) -> None:
    snapshot = make_snapshot(
        pending_plans=[],
        history=[
            make_agv_binding(
                "M1",
                SOURCE_ORDER,
                NOW,
                previous_product_name=None,
            ),
            make_agv_binding(
                "M2",
                MONITORED_ORDER,
                NOW,
                previous_product_name=None,
            ),
            make_agv_binding(
                "M3",
                SOURCE_ORDER,
                NOW,
                previous_product_name=None,
            ),
        ],
    )
    snapshot = snapshot.model_copy(
        update={"mixed_cutline_event_ids": ["CUT-OLD-MIX"]},
        deep=True,
    )
    decision = _equivalent_stockout_decision()
    pipeline = CutlinePipeline()
    _stub_non_confirmation_stages(monkeypatch, pipeline)
    warning = _inject_equivalent_decision(monkeypatch, pipeline, decision)

    result = pipeline.evaluate_algorithm(snapshot)

    assert result.stockout_warnings == [warning]
    assert result.cutline_decisions == [decision]
    assert result.new_active_cutline_events == []
    assert len(result.persistence_state.pending_cutline_plans) == 1
    pending = result.persistence_state.pending_cutline_plans[0]
    assert pending.plan_id == decision.plan.plan_id
    assert pending.status.value == "PENDING"
    assert result.persistence_state.active_cutline_events == []
    assert result.persistence_state.mixed_cutline_event_ids == ["CUT-OLD-MIX"]
    assert result.persistence_state.new_mixing_trace_records == []


def test_pending_factory_error_is_isolated_without_dropping_business_result(
    monkeypatch,
) -> None:
    snapshot = make_snapshot(pending_plans=[])
    decision = _equivalent_stockout_decision()
    pipeline = CutlinePipeline()
    _stub_non_confirmation_stages(monkeypatch, pipeline)
    warning = _inject_equivalent_decision(monkeypatch, pipeline, decision)
    monkeypatch.setattr(
        pipeline._pending_plan_factory,
        "create",
        lambda snapshot, decision: (_ for _ in ()).throw(
            ValueError("named pending failure")
        ),
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert result.stockout_warnings == [warning]
    assert result.cutline_decisions == [decision]
    assert result.persistence_state.pending_cutline_plans == []
    creation_errors = [
        error
        for error in result.errors
        if error.stage == "pending_cutline_creation"
    ]
    assert len(creation_errors) == 1
    assert creation_errors[0].warning_key == decision.plan.plan_id
    assert creation_errors[0].reason == "value_error"
    assert "named pending failure" in creation_errors[0].message


def test_metadata_rich_active_event_suppresses_equivalent_new_plan(
    monkeypatch,
) -> None:
    active = make_active_event(
        plan_id="PLAN-ACTIVE",
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=CREATED_AT,
    )
    snapshot = make_snapshot(
        pending_plans=[],
        active_events=[active],
    )
    decision = _equivalent_stockout_decision()
    pipeline = CutlinePipeline()
    _stub_non_confirmation_stages(
        monkeypatch,
        pipeline,
        interval_results=[
            make_interval_result(MONITORED_ORDER, WARNING_BUFFER)
        ],
    )
    warning = _inject_equivalent_decision(monkeypatch, pipeline, decision)

    result = pipeline.evaluate_algorithm(snapshot)

    assert result.stockout_warnings == [warning]
    assert result.cutline_decisions == []


def test_expired_equivalent_pending_does_not_suppress_new_plan(
    monkeypatch,
) -> None:
    expired_plan = make_stockout_plan(
        created_at=NOW - timedelta(minutes=31),
        expire_at=NOW - timedelta(minutes=1),
    )
    snapshot = make_snapshot(
        pending_plans=[expired_plan],
        current_time=NOW,
    )
    decision = _equivalent_stockout_decision()
    pipeline = CutlinePipeline()
    _stub_non_confirmation_stages(monkeypatch, pipeline)
    warning = _inject_equivalent_decision(monkeypatch, pipeline, decision)

    result = pipeline.evaluate_algorithm(snapshot)

    assert result.stockout_warnings == [warning]
    assert result.cutline_decisions == [decision]
    assert result.new_active_cutline_events == []


def test_pipeline_confirms_and_evaluates_return_before_new_warning_decisions(
    monkeypatch,
) -> None:
    snapshot, _, _ = _confirmed_stockout_snapshot()
    interval_results = [
        make_interval_result(MONITORED_ORDER, WARNING_BUFFER)
    ]
    warning = stockout_warning()
    decision = AlgorithmCutlineDecisionResult(
        plan=stockout_plan(
            selected_machine("pk03"),
            plan_id="PLAN-LATER-WARNING",
        ),
        manual_intervention=None,
    )
    pipeline = CutlinePipeline()
    calls: list[str] = []
    detector = PendingCutlineDetector.detect
    evaluate_return = pipeline._return.evaluate_algorithm

    monkeypatch.setattr(
        pipeline._net_rate,
        "calculate",
        lambda snapshot: calls.append("net_rate") or interval_results,
    )

    def detect(self, snapshot, interval_results):
        calls.append("pending_confirmation")
        return detector(
            self,
            snapshot=snapshot,
            interval_results=interval_results,
        )

    monkeypatch.setattr(PendingCutlineDetector, "detect", detect)

    def evaluate_single_event(*, snapshot, interval_results):
        calls.append(f"return:{snapshot.active_cutline_events[0].event_id}")
        return evaluate_return(
            snapshot=snapshot,
            interval_results=interval_results,
        )

    monkeypatch.setattr(
        pipeline._return,
        "evaluate_algorithm",
        evaluate_single_event,
    )
    monkeypatch.setattr(
        pipeline._depletion,
        "calculate_algorithm",
        lambda results: calls.append("depletion") or [],
    )
    monkeypatch.setattr(
        pipeline._overflow_time,
        "calculate_algorithm",
        lambda snapshot, results: calls.append("overflow_time") or [],
    )
    monkeypatch.setattr(
        pipeline._stockout,
        "evaluate_algorithm",
        lambda snapshot, results: calls.append("stockout_warning") or [warning],
    )
    monkeypatch.setattr(
        pipeline._overflow,
        "evaluate_algorithm",
        lambda snapshot, results: calls.append("overflow_warning") or [],
    )
    monkeypatch.setattr(
        pipeline,
        "_build_stockout_decision",
        lambda *args: calls.append("stockout_decision") or (decision, None),
    )
    monkeypatch.setattr(
        pipeline._silk_transition,
        "evaluate",
        lambda *, snapshot: calls.append("silk") or [],
    )
    monkeypatch.setattr(
        pipeline._mixing_trace,
        "calculate_for_event",
        lambda *, snapshot, event: calls.append("mixing")
        or AlgorithmMixingTraceBatchResult(),
    )

    pipeline.evaluate_algorithm(snapshot)

    assert calls == [
        "net_rate",
        "pending_confirmation",
        "return:CUT-PLAN-STOCKOUT-M1",
        "depletion",
        "overflow_time",
        "stockout_warning",
        "overflow_warning",
        "stockout_decision",
        "silk",
        "mixing",
    ]


def test_same_machine_can_create_event_for_later_independent_plan(
    monkeypatch,
) -> None:
    first_plan = make_stockout_plan()
    later_created_at = CREATED_AT + timedelta(minutes=20)
    later_plan = make_overflow_plan(
        plan_id="PLAN-LATER",
        created_at=later_created_at,
        expire_at=later_created_at + timedelta(minutes=30),
    )
    first_change = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        CREATED_AT + timedelta(minutes=3),
        previous_product_name=SOURCE_PRODUCT_NAME,
    )
    later_change = make_agv_binding(
        "M1",
        ALTERNATE_ORDER,
        later_created_at + timedelta(minutes=5),
        previous_product_name=MONITORED_PRODUCT_NAME,
    )
    snapshot = make_snapshot(
        pending_plans=[first_plan, later_plan],
        history=[first_change, later_change],
        current_orders={"M1": ALTERNATE_ORDER, "M2": MONITORED_ORDER},
        current_time=later_created_at + timedelta(minutes=6),
    )
    pipeline = CutlinePipeline()
    _stub_non_confirmation_stages(
        monkeypatch,
        pipeline,
        interval_results=[
            make_interval_result(MONITORED_ORDER, WARNING_BUFFER),
            make_interval_result(ALTERNATE_ORDER, ALTERNATE_BUFFER),
        ],
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert [
        (item.event_id, item.machine_code, item.cutline_start_time)
        for item in result.new_active_cutline_events
    ] == [
        (
            "CUT-PLAN-STOCKOUT-M1",
            "M1",
            first_change.binding_time,
        ),
        (
            "CUT-PLAN-LATER-M1",
            "M1",
            later_change.binding_time,
        ),
    ]
    assert [item.event_id for item in result.return_results] == [
        "CUT-PLAN-STOCKOUT-M1",
        "CUT-PLAN-LATER-M1",
    ]
