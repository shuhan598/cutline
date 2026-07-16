from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

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
from app.schemas.common_schema import AlgorithmConfig
from app.service.cutline_pipeline import CutlinePipeline
from tests.core.cutline_plan.helpers import overflow_warning, stockout_warning
from tests.core.mixing_trace.test_mixing_trace_calculator import (
    capacity,
    machine_master,
    runtime,
    selected_machine,
    snapshot as mixing_snapshot,
    stockout_plan,
    overflow_plan,
)
from tests.core.return_judge.helpers import (
    CURRENT_TIME,
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


def test_formal_plan_creates_exact_active_event_with_matching_mixing_id(
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
    snapshot = mixing_snapshot(
        config=AlgorithmConfig(cutline_execution_delay_minutes=15)
    )
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline)
    _inject_stockout_decisions(monkeypatch, pipeline, [decision])

    result = pipeline.evaluate_algorithm(snapshot)

    assert [event.model_dump() for event in result.new_active_cutline_events] == [
        {
            "event_id": "CUT-PLAN-EVENT-pk03",
            "plan_id": "PLAN-EVENT",
            "machine_code": "pk03",
            "source_order_code": "ORD-A",
            "target_order_code": "ORD-B",
            "workshop_code": "S2",
            "source_buffer_code": "BUF-SOURCE-pk03",
            "target_buffer_code": "BUF-TARGET-pk03",
            "upstream_process_code": "PK",
            "downstream_process_code": "NEXT",
            "source_wafer_size": "210",
            "source_wafer_spec": "P",
            "target_wafer_size": "210",
            "target_wafer_spec": "N",
            "cutline_start_time": calculation_time + timedelta(minutes=15),
            "negative_start_time": None,
            "status": "active",
            "contribution_capacity": 7.0,
            "warning_type": "stockout",
        }
    ]
    assert [record.cutline_event_id for record in result.mixing_trace_records] == [
        "CUT-PLAN-EVENT-pk03"
    ]
    assert result.return_results == []
    assert result.updated_active_cutline_events == []


@pytest.mark.parametrize(
    ("error_type", "error_message"),
    [
        (ValueError, "bad active event value"),
        (TypeError, "bad active event type"),
        (OverflowError, "bad active event overflow"),
        (ValidationError, None),
    ],
    ids=["value_error", "type_error", "overflow_error", "validation_error"],
)
def test_active_event_creation_error_is_isolated_and_later_machine_continues(
    monkeypatch,
    error_type,
    error_message,
):
    machines = [selected_machine("MC-BAD"), selected_machine("MC-GOOD")]
    snapshot = mixing_snapshot(
        machine_runtimes=[runtime(code) for code in ("MC-BAD", "MC-GOOD")],
        machine_masters=[
            machine_master(code) for code in ("MC-BAD", "MC-GOOD")
        ],
        machine_product_capacities=[capacity("MC-BAD"), capacity("MC-GOOD")],
    )
    decision = _formal_decision(plan_id="PLAN-ISOLATE", machines=machines)
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline)
    _inject_stockout_decisions(monkeypatch, pipeline, [decision])
    create_event = pipeline._active_event_tracker.create_event
    validation_messages = []

    def create_with_one_failure(**kwargs):
        if kwargs["machine_code"] == "MC-BAD":
            if error_type is ValidationError:
                try:
                    return create_event(**(kwargs | {"event_id": ""}))
                except ValidationError as error:
                    validation_messages.append(str(error))
                    raise
            raise error_type(error_message)
        return create_event(**kwargs)

    monkeypatch.setattr(
        pipeline._active_event_tracker,
        "create_event",
        create_with_one_failure,
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert [event.event_id for event in result.new_active_cutline_events] == [
        "CUT-PLAN-ISOLATE-MC-GOOD"
    ]
    active_errors = [
        error for error in result.errors if error.stage == "active_event_creation"
    ]
    expected_message = (
        validation_messages[0]
        if error_type is ValidationError
        else error_message
    )
    assert [error.model_dump() for error in active_errors] == [
        {
            "stage": "active_event_creation",
            "warning_type": "stockout",
            "warning_key": "PLAN-ISOLATE:MC-BAD",
            "reason": "active_event_creation_error",
            "message": expected_message,
        }
    ]


def test_repeated_plan_keeps_stable_event_id_and_default_zero_delay(
    monkeypatch,
):
    calculation_time = datetime(2026, 7, 16, 8, 30)
    decision = _formal_decision(
        plan_id="PLAN-STABLE",
        calculation_time=calculation_time,
    )
    snapshot = mixing_snapshot()
    pipeline = CutlinePipeline()
    tracker = pipeline._active_event_tracker
    _stub_upper_flow(monkeypatch, pipeline)
    _inject_stockout_decisions(monkeypatch, pipeline, [decision])

    first = pipeline.evaluate_algorithm(snapshot)
    second = pipeline.evaluate_algorithm(snapshot)

    assert pipeline._active_event_tracker is tracker
    assert [event.event_id for event in first.new_active_cutline_events] == [
        "CUT-PLAN-STABLE-pk03"
    ]
    assert [event.event_id for event in second.new_active_cutline_events] == [
        "CUT-PLAN-STABLE-pk03"
    ]
    assert first.new_active_cutline_events[0].cutline_start_time == calculation_time


def test_overflow_event_uses_reduced_capacity(monkeypatch):
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

    event = result.new_active_cutline_events[0]
    assert event.warning_type == "overflow"
    assert event.contribution_capacity == 9
    assert event.event_id == "CUT-PLAN-OVERFLOW-EVENT-pk03"


@pytest.mark.parametrize(
    "unexpected_error",
    [MemoryError("event oom"), RuntimeError("event bug")],
    ids=["memory_error", "runtime_error"],
)
def test_unexpected_active_event_creation_error_propagates(
    monkeypatch,
    unexpected_error,
):
    snapshot = mixing_snapshot()
    decision = _formal_decision(plan_id="PLAN-UNEXPECTED")
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline)
    _inject_stockout_decisions(monkeypatch, pipeline, [decision])
    monkeypatch.setattr(
        pipeline._active_event_tracker,
        "create_event",
        lambda **kwargs: (_ for _ in ()).throw(unexpected_error),
    )

    with pytest.raises(type(unexpected_error), match=str(unexpected_error)):
        pipeline.evaluate_algorithm(snapshot)


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


def test_silk_error_is_recorded_and_mixing_still_runs(monkeypatch):
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
    assert len(result.mixing_trace_records) == 1
    assert result.mixing_trace_failures == []
    assert len(result.errors) == 1
    error = result.errors[0]
    assert error.stage == "silk_screen_transition"
    assert error.warning_type is None
    assert error.warning_key is None
    assert error.reason == "silk_screen_transition_calculation_error"
    assert error.message == "silk failed"


def test_formal_plan_generates_mixing_record_and_manual_decision_does_not(
    monkeypatch,
):
    snapshot = mixing_snapshot()
    formal = _formal_decision()
    manual = _manual_decision()
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline)
    _inject_stockout_decisions(monkeypatch, pipeline, [formal, manual])

    result = pipeline.evaluate_algorithm(snapshot)

    assert len(result.mixing_trace_records) == 1
    assert result.mixing_trace_records[0].plan_id == "PLAN001"
    assert [event.plan_id for event in result.new_active_cutline_events] == [
        "PLAN001"
    ]
    assert result.mixing_trace_failures == []
    assert result.errors == []


def test_multi_machine_mixing_failures_stay_out_of_pipeline_errors(monkeypatch):
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

    assert [item.machine_code for item in result.mixing_trace_records] == [
        "pk03",
        "pk05",
    ]
    assert [item.machine_code for item in result.mixing_trace_failures] == ["pk04"]
    assert result.mixing_trace_failures[0].reason == "process_duration_not_found"
    assert [item.machine_code for item in result.new_active_cutline_events] == [
        "pk03",
        "pk04",
        "pk05",
    ]
    assert result.errors == []


def test_multiple_plans_get_global_record_and_failure_sorting(monkeypatch):
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

    assert [item.machine_code for item in result.mixing_trace_records] == [
        "A-REC",
        "Z-REC",
    ]
    assert [item.machine_code for item in result.mixing_trace_failures] == [
        "A-FAIL",
        "Z-FAIL",
    ]
    assert [
        (item.plan_id, item.machine_code)
        for item in result.new_active_cutline_events
    ] == [
        ("PLAN-LATE", "Z-REC"),
        ("PLAN-LATE", "Z-FAIL"),
        ("PLAN-EARLY", "A-REC"),
        ("PLAN-EARLY", "A-FAIL"),
    ]


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


def test_complete_algorithm_stage_call_order(monkeypatch):
    stock_decision = _formal_decision(plan_id="PLAN-STOCK")
    overflow_decision = _formal_decision(plan_id="PLAN-OVERFLOW")
    stock_warning = stockout_warning()
    overflow_warning_result = overflow_warning()
    events = [active_event(event_id="EVENT-01"), active_event(event_id="EVENT-02")]
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
        "calculate_for_decision",
        lambda *, snapshot, decision: calls.append(
            f"mixing:{decision.plan.plan_id}"
        )
        or AlgorithmMixingTraceBatchResult(),
    )

    pipeline.evaluate_algorithm(snapshot)

    assert calls == [
        "net_rate",
        "depletion",
        "overflow_time",
        "stockout_warning",
        "overflow_warning",
        "stockout_decision",
        "overflow_decision",
        "return:EVENT-01",
        "return:EVENT-02",
        "silk",
        "mixing:PLAN-STOCK",
        "mixing:PLAN-OVERFLOW",
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
    snapshot = mixing_snapshot()
    pipeline = CutlinePipeline()
    _stub_upper_flow(monkeypatch, pipeline)
    _inject_stockout_decisions(monkeypatch, pipeline, [_formal_decision()])
    monkeypatch.setattr(
        pipeline._mixing_trace,
        "calculate_for_decision",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("mixing bug")),
    )

    with pytest.raises(RuntimeError, match="mixing bug"):
        pipeline.evaluate_algorithm(snapshot)


def test_return_business_exception_type_remains_specific():
    error = ReturnEvaluationError("target_interval_not_found", "EVENT-01")

    assert error.reason == "target_interval_not_found"
    assert str(error) == "EVENT-01: target_interval_not_found"
