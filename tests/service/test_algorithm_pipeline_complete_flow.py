from datetime import datetime, timedelta

import pytest

from app.core.mixing_trace.mixing_trace_calculator import MixingTraceCalculator
from app.core.return_judge.return_evaluator import (
    ReturnEvaluationError,
    ReturnEvaluator,
)
from app.core.return_judge.active_cutline_event_tracker import (
    ActiveCutlineEventTracker,
)
from app.core.silk_screen.errors import (
    SilkScreenTransitionCalculationError,
)
from app.core.silk_screen.order_transition_planner import (
    SilkScreenOrderTransitionPlanner,
)
from app.schemas.result_schema import (
    AlgorithmCutlineDecisionResult,
    AlgorithmEvaluateResult,
    AlgorithmManualInterventionResult,
    AlgorithmMixingTraceBatchResult,
)
from app.service.cutline_pipeline import CutlinePipeline
from tests.core.cutline_plan.helpers import overflow_warning, stockout_warning
from tests.core.mixing_trace.test_mixing_trace_calculator import (
    capacity,
    machine_master,
    mixing_event,
    PLAN_TIME,
    runtime,
    selected_machine,
    snapshot as mixing_snapshot,
    stockout_plan,
    overflow_plan,
)
from tests.core.return_judge.helpers import (
    CURRENT_TIME,
    CUTLINE_START_TIME,
    active_event,
    algorithm_snapshot,
    interval,
)
from tests.core.silk_screen.test_order_transition_planner import (
    _snapshot as silk_snapshot,
)


def _stub_upper_flow(
    monkeypatch,
    pipeline,
    *,
    interval_results=(),
    stockout_warnings=(),
    overflow_warnings=(),
    calls=None,
):
    intervals = list(interval_results)
    stockout = list(stockout_warnings)
    overflow = list(overflow_warnings)

    def record(name, value):
        if calls is not None:
            calls.append(name)
        return value

    monkeypatch.setattr(
        pipeline._net_rate,
        "calculate",
        lambda snapshot: record("net_rate", intervals),
    )
    monkeypatch.setattr(
        pipeline._depletion,
        "calculate_algorithm",
        lambda results: record("depletion", []),
    )
    monkeypatch.setattr(
        pipeline._overflow_time,
        "calculate_algorithm",
        lambda snapshot, results: record("overflow_time", []),
    )
    monkeypatch.setattr(
        pipeline._stockout,
        "evaluate_algorithm",
        lambda snapshot, results: record("stockout_warning", stockout),
    )
    monkeypatch.setattr(
        pipeline._overflow,
        "evaluate_algorithm",
        lambda snapshot, results: record("overflow_warning", overflow),
    )


def _formal_decision(*, plan_id="PLAN001", calculation_time=None, machines=()):
    plan = stockout_plan(
        *machines,
        plan_id=plan_id,
        calculation_time=calculation_time or datetime(2026, 7, 16, 10, 0),
    )
    return AlgorithmCutlineDecisionResult(plan=plan, manual_intervention=None)


def _manual_decision():
    intervention = AlgorithmManualInterventionResult(
        warning_type="stockout",
        warning_time=CURRENT_TIME,
        workshop_code="WS-01",
        buffer_code="BUF-TARGET",
        order_code="ORD-TARGET",
        wafer_size="182",
        wafer_spec="N",
        upstream_process_code="P01",
        downstream_process_code="P02",
        reason="no_candidates",
        initial_risk_value=1,
        remaining_risk_value=1,
        evaluated_candidate_count=0,
        passed_candidate_count=0,
        rejected_candidate_count=0,
    )
    return AlgorithmCutlineDecisionResult(
        plan=None,
        manual_intervention=intervention,
    )


def _inject_stockout_decisions(monkeypatch, pipeline, decisions):
    values = list(decisions)
    warnings = [
        stockout_warning().model_copy(
            update={"buffer_code": f"BUF-DECISION-{index}"}
        )
        for index in range(len(values))
    ]
    monkeypatch.setattr(
        pipeline._stockout,
        "evaluate_algorithm",
        lambda snapshot, results: warnings,
    )
    decision_by_warning = dict(zip(map(id, warnings), values))
    monkeypatch.setattr(
        pipeline,
        "_build_stockout_decision",
        lambda snapshot, warning, interval_results, overflow_results: (
            decision_by_warning[id(warning)],
            None,
        ),
    )


def test_pipeline_initializes_single_remaining_stage_components():
    pipeline = CutlinePipeline()

    assert isinstance(pipeline._return, ReturnEvaluator)
    assert isinstance(pipeline._silk_transition, SilkScreenOrderTransitionPlanner)
    assert isinstance(pipeline._mixing_trace, MixingTraceCalculator)
    assert isinstance(pipeline._active_event_tracker, ActiveCutlineEventTracker)


def test_formal_plan_waits_for_confirmation_without_future_mixing_record(
    monkeypatch,
):
    calculation_time = datetime(2026, 7, 16, 10, 0)
    machine = selected_machine("pk03").model_copy(
        update={
            "wafer_size": "210",
            "source_wafer_spec": "P",
            "target_wafer_spec": "N",
            "contribution_capacity": 7,
        }
    )
    decision = _formal_decision(
        plan_id="PLAN-EVENT",
        calculation_time=calculation_time,
        machines=[machine],
    )
    snapshot = mixing_snapshot()
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline)
    _inject_stockout_decisions(monkeypatch, pipeline, [decision])

    result = pipeline.evaluate_algorithm(snapshot)

    assert len(result.stockout_warnings) == 1
    assert result.cutline_decisions == [decision]
    assert result.new_active_cutline_events == []
    assert result.mixing_trace_records == []
    assert result.return_results == []
    assert result.updated_active_cutline_events == []


def test_repeated_unconfirmed_plan_never_calls_active_event_tracker(
    monkeypatch,
):
    decision = _formal_decision(plan_id="PLAN-STABLE")
    snapshot = mixing_snapshot()
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline)
    _inject_stockout_decisions(monkeypatch, pipeline, [decision])
    monkeypatch.setattr(
        pipeline._active_event_tracker,
        "create_event",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("unconfirmed plan must not create an active event")
        ),
    )

    first = pipeline.evaluate_algorithm(snapshot)
    second = pipeline.evaluate_algorithm(snapshot)

    assert first.new_active_cutline_events == []
    assert second.new_active_cutline_events == []
    assert first.mixing_trace_records == []
    assert second.mixing_trace_records == []


def test_unconfirmed_overflow_plan_does_not_create_active_event(monkeypatch):
    machine = selected_machine("pk03").model_copy(
        update={"contribution_capacity": None, "reduced_capacity": 9}
    )
    decision = AlgorithmCutlineDecisionResult(
        plan=overflow_plan(machine, plan_id="PLAN-OVERFLOW-EVENT"),
        manual_intervention=None,
    )
    snapshot = mixing_snapshot()
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline)
    _inject_stockout_decisions(monkeypatch, pipeline, [decision])

    result = pipeline.evaluate_algorithm(snapshot)

    assert result.new_active_cutline_events == []
    assert result.return_results == []


def test_empty_remaining_inputs_return_accessible_complete_result(monkeypatch):
    pipeline = CutlinePipeline()
    snapshot = algorithm_snapshot()
    _stub_upper_flow(monkeypatch, pipeline)

    result = pipeline.evaluate_algorithm(snapshot)

    assert isinstance(result, AlgorithmEvaluateResult)
    assert result.calculation_time == snapshot.current_time
    assert result.return_results == []
    assert result.new_active_cutline_events == []
    assert result.updated_active_cutline_events == []
    assert result.silk_screen_results == []
    assert result.mixing_trace_records == []
    assert result.mixing_trace_failures == []
    assert result.errors == []


def test_active_event_uses_real_return_evaluator_wiring(monkeypatch):
    event = active_event(
        negative_start_time=CURRENT_TIME - timedelta(minutes=30)
    )
    snapshot = algorithm_snapshot(active_cutline_events=[event])
    target_interval = interval()
    pipeline = CutlinePipeline()
    _stub_upper_flow(
        monkeypatch,
        pipeline,
        interval_results=[target_interval],
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert len(result.return_results) == 1
    return_result = result.return_results[0]
    assert return_result.event_id == event.event_id
    assert return_result.machine_code == event.machine_code
    assert return_result.net_consumption_rate == target_interval.net_consumption_rate
    assert return_result.current_quantity == target_interval.current_quantity
    assert return_result.updated_negative_start_time == event.negative_start_time
    assert return_result.condition_net_rate_met is True
    assert return_result.condition_stability_met is True
    assert return_result.condition_inventory_met is True
    assert return_result.return_recommended is True
    assert return_result.updated_status == "return_recommended"
    assert len(result.updated_active_cutline_events) == 1
    updated_event = result.updated_active_cutline_events[0]
    assert updated_event is not event
    assert updated_event.event_id == event.event_id
    assert updated_event.negative_start_time == event.negative_start_time
    assert updated_event.status == "return_recommended"


def test_first_negative_interval_sets_current_time_and_stays_active(monkeypatch):
    event = active_event(negative_start_time=None)
    snapshot = algorithm_snapshot(active_cutline_events=[event])
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline, interval_results=[interval()])

    result = pipeline.evaluate_algorithm(snapshot)

    updated_event = result.updated_active_cutline_events[0]
    assert updated_event.negative_start_time == snapshot.current_time
    assert updated_event.status == "active"
    assert event.negative_start_time is None
    assert event.status == "active"


def test_non_negative_interval_clears_negative_time_and_stays_active(monkeypatch):
    original_negative_start = CURRENT_TIME - timedelta(minutes=30)
    event = active_event(negative_start_time=original_negative_start)
    snapshot = algorithm_snapshot(active_cutline_events=[event])
    pipeline = CutlinePipeline()
    _stub_upper_flow(
        monkeypatch,
        pipeline,
        interval_results=[interval(net_consumption_rate=1)],
    )

    result = pipeline.evaluate_algorithm(snapshot)

    updated_event = result.updated_active_cutline_events[0]
    assert updated_event.negative_start_time is None
    assert updated_event.status == "active"
    assert event.negative_start_time == original_negative_start


def test_multiple_active_events_are_isolated_and_keep_snapshot_order(monkeypatch):
    first = active_event(event_id="EVENT-02", machine_code="MC-02")
    second = active_event(
        event_id="EVENT-01",
        machine_code="MC-01",
        target_buffer_code="BUF-SECOND",
        target_order_code="ORD-SECOND",
    )
    snapshot = algorithm_snapshot(active_cutline_events=[first, second])
    intervals = [
        interval(),
        interval(buffer_code="BUF-SECOND", order_code="ORD-SECOND"),
    ]
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline, interval_results=intervals)
    evaluated_event_lists = []
    evaluate_event = pipeline._return.evaluate_algorithm

    def evaluate_single_event(*, snapshot, interval_results):
        evaluated_event_lists.append(
            [event.event_id for event in snapshot.active_cutline_events]
        )
        return evaluate_event(
            snapshot=snapshot,
            interval_results=interval_results,
        )

    monkeypatch.setattr(
        pipeline._return,
        "evaluate_algorithm",
        evaluate_single_event,
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert evaluated_event_lists == [["EVENT-02"], ["EVENT-01"]]
    assert [item.event_id for item in result.return_results] == [
        "EVENT-02",
        "EVENT-01",
    ]
    assert [item.event_id for item in result.updated_active_cutline_events] == [
        "EVENT-02",
        "EVENT-01",
    ]
    assert all(
        updated is not original
        for updated, original in zip(
            result.updated_active_cutline_events,
            snapshot.active_cutline_events,
        )
    )


def test_return_error_isolated_per_event_and_next_event_continues(monkeypatch):
    missing = active_event(
        event_id="EVENT-MISSING",
        target_buffer_code="BUF-MISSING",
    )
    valid = active_event(event_id="EVENT-VALID", machine_code="MC-VALID")
    snapshot = algorithm_snapshot(active_cutline_events=[missing, valid])
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline, interval_results=[interval()])

    result = pipeline.evaluate_algorithm(snapshot)

    assert [item.event_id for item in result.return_results] == ["EVENT-VALID"]
    assert len(result.errors) == 1
    error = result.errors[0]
    assert error.stage == "return_evaluation"
    assert error.warning_type is None
    assert error.warning_key == "EVENT-MISSING"
    assert error.reason == "target_interval_not_found"
    assert error.message == "EVENT-MISSING: target_interval_not_found"
    assert [item.event_id for item in result.updated_active_cutline_events] == [
        "EVENT-VALID"
    ]


@pytest.mark.parametrize("status", ["return_recommended", "returned", "cancelled"])
def test_non_active_events_do_not_produce_return_results(monkeypatch, status):
    snapshot = algorithm_snapshot(
        active_cutline_events=[active_event(status=status)]
    )
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline, interval_results=[interval()])

    result = pipeline.evaluate_algorithm(snapshot)

    assert result.return_results == []
    assert result.updated_active_cutline_events == []
    assert result.errors == []


def test_real_silk_transition_result_is_included(monkeypatch):
    snapshot = silk_snapshot()
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline)

    result = pipeline.evaluate_algorithm(snapshot)

    assert len(result.silk_screen_results) == 1
    silk_result = result.silk_screen_results[0]
    assert silk_result.current_order_code == "ORD-01"
    assert silk_result.machine_codes == ["M01"]
    assert silk_result.reason == "not_yet_time_to_prepare"


def test_silk_error_is_recorded_without_decision_driven_mixing(monkeypatch):
    snapshot = mixing_snapshot()
    decision = _formal_decision()
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline)
    _inject_stockout_decisions(monkeypatch, pipeline, [decision])
    monkeypatch.setattr(
        pipeline._silk_transition,
        "evaluate",
        lambda **kwargs: (_ for _ in ()).throw(
            SilkScreenTransitionCalculationError("silk failed")
        ),
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert result.silk_screen_results == []
    assert result.mixing_trace_records == []
    assert result.mixing_trace_failures == []
    silk_errors = [
        error
        for error in result.errors
        if error.stage == "silk_screen_transition"
    ]
    assert len(silk_errors) == 1
    error = silk_errors[0]
    assert error.stage == "silk_screen_transition"
    assert error.warning_type is None
    assert error.warning_key is None
    assert error.reason == "silk_screen_transition_calculation_error"
    assert error.message == "silk failed"
    assert any(
        error.stage == "pending_cutline_creation"
        for error in result.errors
    )


def test_decisions_do_not_generate_mixing_records(
    monkeypatch,
):
    snapshot = mixing_snapshot()
    formal = _formal_decision()
    manual = _manual_decision()
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline)
    _inject_stockout_decisions(monkeypatch, pipeline, [formal, manual])
    factory_calls = []
    create_pending = pipeline._pending_plan_factory.create

    def record_factory_call(snapshot, decision):
        factory_calls.append(decision)
        return create_pending(snapshot, decision)

    monkeypatch.setattr(
        pipeline._pending_plan_factory,
        "create",
        record_factory_call,
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert result.mixing_trace_records == []
    assert result.new_active_cutline_events == []
    assert result.mixing_trace_failures == []
    assert [error.stage for error in result.errors] == [
        "pending_cutline_creation"
    ]
    assert factory_calls == [formal]


def test_unconfirmed_multi_machine_plan_does_not_attempt_mixing(monkeypatch):
    successful = selected_machine("pk03")
    failing = selected_machine("pk04")
    second_successful = selected_machine("pk05")
    snapshot = mixing_snapshot(
        machine_runtimes=[runtime(code) for code in ("pk03", "pk04", "pk05")],
        machine_masters=[
            machine_master(code) for code in ("pk03", "pk04", "pk05")
        ],
        machine_product_capacities=[capacity("pk03"), capacity("pk05")],
    )
    decision = _formal_decision(
        machines=[successful, failing, second_successful]
    )
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline)
    _inject_stockout_decisions(monkeypatch, pipeline, [decision])

    result = pipeline.evaluate_algorithm(snapshot)

    assert result.mixing_trace_records == []
    assert result.mixing_trace_failures == []
    assert result.new_active_cutline_events == []
    assert [error.stage for error in result.errors] == [
        "pending_cutline_creation"
    ]


def test_multiple_unconfirmed_plans_do_not_attempt_mixing(monkeypatch):
    machines = ["Z-REC", "Z-FAIL", "A-REC", "A-FAIL"]
    snapshot = mixing_snapshot(
        machine_runtimes=[runtime(code) for code in machines],
        machine_masters=[machine_master(code) for code in machines],
        machine_product_capacities=[capacity("Z-REC"), capacity("A-REC")],
    )
    late = _formal_decision(
        plan_id="PLAN-LATE",
        calculation_time=datetime(2026, 7, 16, 11, 0),
        machines=[selected_machine("Z-REC"), selected_machine("Z-FAIL")],
    )
    early = _formal_decision(
        plan_id="PLAN-EARLY",
        calculation_time=datetime(2026, 7, 16, 9, 0),
        machines=[selected_machine("A-REC"), selected_machine("A-FAIL")],
    )
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline)
    _inject_stockout_decisions(monkeypatch, pipeline, [late, early])

    result = pipeline.evaluate_algorithm(snapshot)

    assert result.mixing_trace_records == []
    assert result.mixing_trace_failures == []
    assert result.new_active_cutline_events == []


def test_complete_flow_does_not_mutate_snapshot_decision_or_plan(monkeypatch):
    event = active_event(
        negative_start_time=CURRENT_TIME - timedelta(minutes=30)
    )
    snapshot = mixing_snapshot(current_time=CURRENT_TIME)
    snapshot.active_cutline_events = [event]
    decision = _formal_decision()
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline, interval_results=[interval()])
    _inject_stockout_decisions(monkeypatch, pipeline, [decision])
    before_snapshot = snapshot.model_dump()
    before_decision = decision.model_dump()

    pipeline.evaluate_algorithm(snapshot)

    assert snapshot.model_dump() == before_snapshot
    assert decision.model_dump() == before_decision


def test_complete_active_event_generates_one_mixing_record(monkeypatch):
    event = mixing_event(
        event_id="EVENT-ACTIVE-001",
        plan_id="PLAN-ACTIVE-001",
    )
    snapshot = mixing_snapshot().model_copy(
        update={"active_cutline_events": [event]},
        deep=True,
    )
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline)
    monkeypatch.setattr(
        pipeline._return,
        "evaluate_algorithm",
        lambda *, snapshot, interval_results: [],
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert [item.cutline_event_id for item in result.mixing_trace_records] == [
        event.event_id
    ]
    assert result.persistence_state.new_mixing_trace_records == (
        result.mixing_trace_records
    )
    assert result.persistence_state.mixed_cutline_event_ids == [event.event_id]


def test_blank_process_legacy_event_is_skipped_without_recurring_failure(
    monkeypatch,
):
    event = mixing_event(event_id="EVENT-LEGACY-BLANK").model_copy(
        update={"process_code": "   "},
        deep=True,
    )
    snapshot = mixing_snapshot().model_copy(
        update={"active_cutline_events": [event]},
        deep=True,
    )
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline)
    monkeypatch.setattr(
        pipeline._return,
        "evaluate_algorithm",
        lambda *, snapshot, interval_results: [],
    )
    monkeypatch.setattr(
        pipeline._mixing_trace,
        "calculate_for_event",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("incomplete legacy event must not be calculated")
        ),
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert result.mixing_trace_records == []
    assert result.mixing_trace_failures == []
    assert result.persistence_state.mixed_cutline_event_ids == []


def test_mixed_event_watermark_prevents_replayed_calculation(monkeypatch):
    event = mixing_event(event_id="EVENT-MIXED")
    snapshot = mixing_snapshot().model_copy(
        update={
            "active_cutline_events": [event],
            "mixed_cutline_event_ids": [event.event_id],
        },
        deep=True,
    )
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline)
    monkeypatch.setattr(
        pipeline._return,
        "evaluate_algorithm",
        lambda *, snapshot, interval_results: [],
    )
    monkeypatch.setattr(
        pipeline._mixing_trace,
        "calculate_for_event",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("mixed event must not be recalculated")
        ),
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert result.mixing_trace_records == []
    assert result.mixing_trace_failures == []
    assert result.persistence_state.new_mixing_trace_records == []
    assert result.persistence_state.mixed_cutline_event_ids == [event.event_id]


def test_failed_event_does_not_advance_watermark_and_can_retry(monkeypatch):
    event = mixing_event(event_id="EVENT-RETRY", plan_id="PLAN-RETRY")
    failing_snapshot = mixing_snapshot(
        machine_product_capacities=[]
    ).model_copy(update={"active_cutline_events": [event]}, deep=True)
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline)
    monkeypatch.setattr(
        pipeline._return,
        "evaluate_algorithm",
        lambda *, snapshot, interval_results: [],
    )

    failed = pipeline.evaluate_algorithm(failing_snapshot)

    assert failed.mixing_trace_records == []
    assert [item.cutline_event_id for item in failed.mixing_trace_failures] == [
        event.event_id
    ]
    assert failed.persistence_state.mixed_cutline_event_ids == []

    corrected_snapshot = mixing_snapshot().model_copy(
        update={"active_cutline_events": [event]},
        deep=True,
    )
    retried = pipeline.evaluate_algorithm(corrected_snapshot)

    assert [item.cutline_event_id for item in retried.mixing_trace_records] == [
        event.event_id
    ]
    assert retried.persistence_state.mixed_cutline_event_ids == [event.event_id]


def test_same_machine_later_event_can_generate_new_mixing_record(monkeypatch):
    first = mixing_event(event_id="EVENT-FIRST", plan_id="PLAN-FIRST")
    second = mixing_event(
        event_id="EVENT-SECOND",
        plan_id="PLAN-SECOND",
        cutline_start_time=PLAN_TIME + timedelta(minutes=5),
    )
    snapshot = mixing_snapshot().model_copy(
        update={
            "active_cutline_events": [first, second],
            "mixed_cutline_event_ids": [first.event_id],
        },
        deep=True,
    )
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline)
    monkeypatch.setattr(
        pipeline._return,
        "evaluate_algorithm",
        lambda *, snapshot, interval_results: [],
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert [item.cutline_event_id for item in result.mixing_trace_records] == [
        second.event_id
    ]
    assert result.persistence_state.mixed_cutline_event_ids == [
        first.event_id,
        second.event_id,
    ]


def test_input_return_watermark_skips_only_that_active_event(monkeypatch):
    suggested = active_event(event_id="EVENT-SUGGESTED", machine_code="MC-01")
    remaining = active_event(
        event_id="EVENT-REMAINING",
        machine_code="MC-02",
        target_buffer_code="BUF-SECOND",
        target_order_code="ORD-SECOND",
        cutline_start_time=CUTLINE_START_TIME + timedelta(minutes=1),
    )
    snapshot = algorithm_snapshot(
        active_cutline_events=[suggested, remaining]
    ).model_copy(
        update={"return_suggested_event_ids": [suggested.event_id]},
        deep=True,
    )
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline)
    evaluated: list[str] = []
    monkeypatch.setattr(
        pipeline._return,
        "evaluate_algorithm",
        lambda *, snapshot, interval_results: evaluated.append(
            snapshot.active_cutline_events[0].event_id
        )
        or [],
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert evaluated == [remaining.event_id]
    assert result.return_results == []
    persisted = {
        item.event_id: item
        for item in result.persistence_state.active_cutline_events
    }
    assert persisted[suggested.event_id].status == "return_recommended"
    assert persisted[remaining.event_id].status == "active"
    assert result.persistence_state.return_suggested_event_ids == [
        suggested.event_id
    ]


def test_complete_algorithm_stage_call_order(monkeypatch):
    stock_decision = _formal_decision(plan_id="PLAN-STOCK")
    overflow_decision = _formal_decision(plan_id="PLAN-OVERFLOW")
    stock_warning = stockout_warning()
    overflow_warning_result = overflow_warning()
    events = [
        mixing_event(event_id="EVENT-01", plan_id="PLAN-EVENT-01"),
        mixing_event(
            event_id="EVENT-02",
            plan_id="PLAN-EVENT-02",
            cutline_start_time=PLAN_TIME + timedelta(minutes=1),
        ),
    ]
    snapshot = algorithm_snapshot(active_cutline_events=events)
    pipeline = CutlinePipeline()
    calls = []
    _stub_upper_flow(
        monkeypatch,
        pipeline,
        stockout_warnings=[stock_warning],
        overflow_warnings=[overflow_warning_result],
        calls=calls,
    )
    monkeypatch.setattr(
        pipeline,
        "_build_stockout_decision",
        lambda *args: calls.append("stockout_decision")
        or (stock_decision, None),
    )
    monkeypatch.setattr(
        pipeline,
        "_build_overflow_decision",
        lambda *args: calls.append("overflow_decision")
        or (overflow_decision, None),
    )
    monkeypatch.setattr(
        pipeline._return,
        "evaluate_algorithm",
        lambda *, snapshot, interval_results: calls.append(
            f"return:{snapshot.active_cutline_events[0].event_id}"
        )
        or [],
    )
    monkeypatch.setattr(
        pipeline._silk_transition,
        "evaluate",
        lambda *, snapshot: calls.append("silk") or [],
    )
    monkeypatch.setattr(
        pipeline._mixing_trace,
        "calculate_for_event",
        lambda *, snapshot, event: calls.append(
            f"mixing:{event.event_id}"
        )
        or AlgorithmMixingTraceBatchResult(),
    )

    pipeline.evaluate_algorithm(snapshot)

    assert calls == [
        "net_rate",
        "return:EVENT-01",
        "return:EVENT-02",
        "depletion",
        "overflow_time",
        "stockout_warning",
        "overflow_warning",
        "stockout_decision",
        "overflow_decision",
        "silk",
        "mixing:EVENT-01",
        "mixing:EVENT-02",
    ]


def test_unexpected_return_exception_propagates(monkeypatch):
    snapshot = algorithm_snapshot(active_cutline_events=[active_event()])
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline)
    monkeypatch.setattr(
        pipeline._return,
        "evaluate_algorithm",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("return bug")),
    )

    with pytest.raises(RuntimeError, match="return bug"):
        pipeline.evaluate_algorithm(snapshot)


def test_unexpected_silk_exception_propagates(monkeypatch):
    snapshot = algorithm_snapshot()
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline)
    monkeypatch.setattr(
        pipeline._silk_transition,
        "evaluate",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("silk bug")),
    )

    with pytest.raises(RuntimeError, match="silk bug"):
        pipeline.evaluate_algorithm(snapshot)


def test_unexpected_mixing_exception_propagates(monkeypatch):
    event = mixing_event(event_id="EVENT-ERROR")
    snapshot = mixing_snapshot().model_copy(
        update={"active_cutline_events": [event]},
        deep=True,
    )
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline)
    monkeypatch.setattr(
        pipeline._return,
        "evaluate_algorithm",
        lambda *, snapshot, interval_results: [],
    )
    monkeypatch.setattr(
        pipeline._mixing_trace,
        "calculate_for_event",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("mixing bug")),
    )

    with pytest.raises(RuntimeError, match="mixing bug"):
        pipeline.evaluate_algorithm(snapshot)


def test_return_business_exception_type_remains_specific():
    error = ReturnEvaluationError("target_interval_not_found", "EVENT-01")

    assert error.reason == "target_interval_not_found"
    assert str(error) == "EVENT-01: target_interval_not_found"
