import pytest

from app.core.candidate_machine.errors import CandidateMachineCalculationError
from app.core.mixing_trace.mixing_trace_calculator import MixingTraceCalculator
from app.core.return_judge.return_evaluator import ReturnEvaluator
from app.core.silk_screen.order_transition_planner import (
    SilkScreenOrderTransitionPlanner,
)
from app.core.cutline_plan.errors import MachineSelectionEvaluationError
from app.core.cutline_plan.machine_selection_evaluator import (
    MachineSelectionEvaluator,
)
from app.core.cutline_plan.plan_builder import CutlinePlanBuilder
from app.schemas.result_schema import (
    AlgorithmMixingTraceBatchResult,
    AlgorithmOverflowSelectionResult,
    AlgorithmStockoutSelectionResult,
)
from app.service.cutline_pipeline import CutlinePipeline
from tests.core.candidate_machine.helpers import (
    agv_relation,
    buffer_relation,
    order,
    product,
    runtime,
    snapshot as candidate_snapshot,
)
from tests.core.cutline_plan.helpers import (
    default_overflow_intervals,
    default_overflow_states,
    default_stockout_intervals,
    overflow_state,
    overflow_warning,
    stockout_warning,
)


@pytest.fixture(autouse=True)
def _isolate_remaining_algorithm_stages(monkeypatch):
    monkeypatch.setattr(
        ReturnEvaluator,
        "evaluate_algorithm",
        lambda self, **kwargs: [],
    )
    monkeypatch.setattr(
        SilkScreenOrderTransitionPlanner,
        "evaluate",
        lambda self, **kwargs: [],
    )
    monkeypatch.setattr(
        MixingTraceCalculator,
        "calculate_for_decision",
        lambda self, **kwargs: AlgorithmMixingTraceBatchResult(),
    )


def _decision_snapshot(
    *,
    warning_buffer: str,
    warning_downstream_process: str = "P02",
    machine_status: str = "running",
    output_quantity_30m: float = 5000,
):
    value = candidate_snapshot()
    value.machine_runtimes = [
        runtime(
            "M-01",
            "ORD-SOURCE",
            machine_status,
            5000,
            output_quantity_30m,
        )
    ]
    value.orders = [
        order("ORD-SOURCE", "PROD-SOURCE", "S1"),
        order("ORD-TARGET", "PROD-TARGET", "S1"),
    ]
    value.products = [
        product("PROD-SOURCE", "182", "A"),
        product("PROD-TARGET", "182", "A"),
    ]
    value.agv_relations = [
        agv_relation(
            machine_code="M-01",
            order_code="ORD-SOURCE",
            order_name="ORD-SOURCE",
            wafer_spec="N",
        )
    ]
    value.buffer_process_relations = [
        buffer_relation(
            warning_buffer,
            "S1",
            "P01",
            warning_downstream_process,
        )
    ]
    return value


def _stub_upper_flow(
    monkeypatch,
    pipeline,
    *,
    interval_results,
    overflow_results,
    stockout_warnings=(),
    overflow_warnings=(),
):
    calls = []

    def calculate_net_rates(snapshot):
        calls.append("net_rate")
        return interval_results

    def calculate_depletions(results):
        calls.append("depletion")
        assert results is interval_results
        return []

    def calculate_overflows(snapshot, results):
        calls.append("overflow_time")
        assert results is interval_results
        return overflow_results

    def evaluate_stockout(snapshot, results):
        calls.append("stockout_warning")
        assert results == []
        return list(stockout_warnings)

    def evaluate_overflow(snapshot, results):
        calls.append("overflow_warning")
        assert results is overflow_results
        return list(overflow_warnings)

    monkeypatch.setattr(pipeline._net_rate, "calculate", calculate_net_rates)
    monkeypatch.setattr(
        pipeline._depletion,
        "calculate_algorithm",
        calculate_depletions,
    )
    monkeypatch.setattr(
        pipeline._overflow_time,
        "calculate_algorithm",
        calculate_overflows,
    )
    monkeypatch.setattr(
        pipeline._stockout,
        "evaluate_algorithm",
        evaluate_stockout,
    )
    monkeypatch.setattr(
        pipeline._overflow,
        "evaluate_algorithm",
        evaluate_overflow,
    )
    return calls


def _manual_stockout_decision(snapshot, warning):
    selection = AlgorithmStockoutSelectionResult(
        workshop_code=warning.workshop_code,
        buffer_code=warning.buffer_code,
        order_code=warning.order_code,
        wafer_size=warning.wafer_size,
        wafer_spec=warning.wafer_spec,
        upstream_process_code=warning.upstream_process_code,
        downstream_process_code=warning.downstream_process_code,
        initial_capacity_gap=warning.net_consumption_rate,
        total_contribution_capacity=0,
        remaining_capacity_gap=warning.net_consumption_rate,
        risk_resolved=False,
        failure_reason="no_candidates",
    )
    return CutlinePlanBuilder().build_stockout_decision(
        snapshot,
        warning,
        selection,
    )


def _manual_overflow_decision(snapshot, warning):
    source_detail = min(
        (detail for detail in warning.order_growth_details if detail.growth_rate > 0),
        key=lambda detail: (-detail.growth_rate, detail.order_code),
    )
    selection = AlgorithmOverflowSelectionResult(
        workshop_code=warning.workshop_code,
        buffer_code=warning.buffer_code,
        upstream_process_code=warning.upstream_process_code,
        downstream_process_code=warning.downstream_process_code,
        source_order_code=source_detail.order_code,
        source_wafer_size=source_detail.wafer_size,
        source_wafer_spec=source_detail.wafer_spec,
        initial_growth_rate=warning.buffer_growth_rate,
        total_reduced_capacity=0,
        remaining_growth_rate=warning.buffer_growth_rate,
        updated_overflow_minutes=warning.overflow_minutes,
        risk_resolved=False,
        failure_reason="no_candidates",
    )
    return CutlinePlanBuilder().build_overflow_decision(
        snapshot,
        warning,
        selection,
    )


def test_pipeline_initializes_one_machine_selection_evaluator():
    pipeline = CutlinePipeline()

    assert isinstance(pipeline._selection, MachineSelectionEvaluator)


def test_stockout_warning_builds_automatic_plan_with_real_decision_components(
    monkeypatch,
):
    snapshot = _decision_snapshot(warning_buffer="BUF-TARGET")
    warning = stockout_warning(buffer_code="BUF-TARGET")
    intervals = default_stockout_intervals()
    overflows = [overflow_state("BUF-SOURCE"), overflow_state("BUF-TARGET")]
    pipeline = CutlinePipeline()
    upper_calls = _stub_upper_flow(
        monkeypatch,
        pipeline,
        interval_results=intervals,
        overflow_results=overflows,
        stockout_warnings=[warning],
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert upper_calls == [
        "net_rate",
        "depletion",
        "overflow_time",
        "stockout_warning",
        "overflow_warning",
    ]
    assert len(result.cutline_decisions) == 1
    decision = result.cutline_decisions[0]
    assert decision.manual_intervention is None
    assert decision.plan is not None
    assert decision.plan.warning_type == "stockout"
    assert [item.machine_code for item in decision.plan.selected_machines] == [
        "M-01"
    ]
    assert result.errors == []


def test_stockout_without_candidates_builds_manual_intervention_not_error(
    monkeypatch,
):
    snapshot = _decision_snapshot(
        warning_buffer="BUF-TARGET",
        machine_status="idle",
    )
    warning = stockout_warning(buffer_code="BUF-TARGET")
    pipeline = CutlinePipeline()
    _stub_upper_flow(
        monkeypatch,
        pipeline,
        interval_results=default_stockout_intervals(),
        overflow_results=[
            overflow_state("BUF-SOURCE"),
            overflow_state("BUF-TARGET"),
        ],
        stockout_warnings=[warning],
    )

    result = pipeline.evaluate_algorithm(snapshot)

    decision = result.cutline_decisions[0]
    assert decision.plan is None
    assert decision.manual_intervention is not None
    assert decision.manual_intervention.warning_type == "stockout"
    assert decision.manual_intervention.evaluated_candidate_count == 0
    assert result.errors == []


def test_overflow_warning_builds_automatic_plan_with_real_decision_components(
    monkeypatch,
):
    snapshot = _decision_snapshot(warning_buffer="BUF-OVERFLOW")
    warning = overflow_warning()
    pipeline = CutlinePipeline()
    _stub_upper_flow(
        monkeypatch,
        pipeline,
        interval_results=default_overflow_intervals(),
        overflow_results=default_overflow_states(),
        overflow_warnings=[warning],
    )

    result = pipeline.evaluate_algorithm(snapshot)

    decision = result.cutline_decisions[0]
    assert decision.manual_intervention is None
    assert decision.plan is not None
    assert decision.plan.warning_type == "overflow"
    assert [item.machine_code for item in decision.plan.selected_machines] == [
        "M-01"
    ]
    assert decision.plan.selected_machines[0].target_order_code == "ORD-TARGET"
    assert result.errors == []


def test_overflow_without_candidates_builds_manual_intervention_not_error(
    monkeypatch,
):
    snapshot = _decision_snapshot(
        warning_buffer="BUF-OVERFLOW",
        machine_status="idle",
    )
    warning = overflow_warning()
    pipeline = CutlinePipeline()
    _stub_upper_flow(
        monkeypatch,
        pipeline,
        interval_results=default_overflow_intervals(),
        overflow_results=default_overflow_states(),
        overflow_warnings=[warning],
    )

    result = pipeline.evaluate_algorithm(snapshot)

    decision = result.cutline_decisions[0]
    assert decision.plan is None
    assert decision.manual_intervention is not None
    assert decision.manual_intervention.warning_type == "overflow"
    assert decision.manual_intervention.evaluated_candidate_count == 0
    assert result.errors == []


def test_decisions_preserve_stockout_then_overflow_warning_order(monkeypatch):
    snapshot = _decision_snapshot(warning_buffer="BUF-TARGET")
    stockout_warnings = [
        stockout_warning().model_copy(
            update={"buffer_code": "BUF-S1", "order_code": "ORD-S1"}
        ),
        stockout_warning().model_copy(
            update={"buffer_code": "BUF-S2", "order_code": "ORD-S2"}
        ),
    ]
    overflow_warnings = [
        overflow_warning().model_copy(update={"buffer_code": "BUF-O1"})
    ]
    pipeline = CutlinePipeline()
    _stub_upper_flow(
        monkeypatch,
        pipeline,
        interval_results=[],
        overflow_results=[],
        stockout_warnings=stockout_warnings,
        overflow_warnings=overflow_warnings,
    )
    calls = []

    def stockout_candidates(snapshot, warnings):
        calls.append(("stockout_candidate", warnings[0].buffer_code))
        return [object()]

    def overflow_candidates(snapshot, warnings, interval_results):
        calls.append(("overflow_candidate", warnings[0].buffer_code))
        return [object()]

    def select_stockout(**kwargs):
        calls.append(("stockout_selection", kwargs["warning"].buffer_code))
        return object()

    def select_overflow(**kwargs):
        calls.append(("overflow_selection", kwargs["warning"].buffer_code))
        return object()

    def build_stockout(snapshot, warning, selection):
        calls.append(("stockout_plan", warning.buffer_code))
        return _manual_stockout_decision(snapshot, warning)

    def build_overflow(snapshot, warning, selection):
        calls.append(("overflow_plan", warning.buffer_code))
        return _manual_overflow_decision(snapshot, warning)

    monkeypatch.setattr(pipeline._candidate, "find_algorithm", stockout_candidates)
    monkeypatch.setattr(
        pipeline._overflow_candidate,
        "find_algorithm",
        overflow_candidates,
    )
    monkeypatch.setattr(
        pipeline._selection,
        "select_stockout_machines",
        select_stockout,
    )
    monkeypatch.setattr(
        pipeline._selection,
        "select_overflow_machines",
        select_overflow,
    )
    monkeypatch.setattr(
        pipeline._plan_builder,
        "build_stockout_decision",
        build_stockout,
    )
    monkeypatch.setattr(
        pipeline._plan_builder,
        "build_overflow_decision",
        build_overflow,
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert calls == [
        ("stockout_candidate", "BUF-S1"),
        ("stockout_selection", "BUF-S1"),
        ("stockout_plan", "BUF-S1"),
        ("stockout_candidate", "BUF-S2"),
        ("stockout_selection", "BUF-S2"),
        ("stockout_plan", "BUF-S2"),
        ("overflow_candidate", "BUF-O1"),
        ("overflow_selection", "BUF-O1"),
        ("overflow_plan", "BUF-O1"),
    ]
    assert [
        decision.manual_intervention.warning_type
        for decision in result.cutline_decisions
    ] == ["stockout", "stockout", "overflow"]
    assert result.errors == []


@pytest.mark.parametrize(
    ("failed_stage", "error", "expected_reason"),
    [
        (
            "stockout_candidate",
            CandidateMachineCalculationError("candidate failed"),
            "candidate_machine_calculation_error",
        ),
        (
            "stockout_selection",
            MachineSelectionEvaluationError("selection failed"),
            "machine_selection_evaluation_error",
        ),
        ("stockout_plan", RuntimeError("plan failed"), "runtime_error"),
    ],
)
def test_stockout_error_isolated_per_warning_with_stage_context(
    monkeypatch,
    failed_stage,
    error,
    expected_reason,
):
    snapshot = _decision_snapshot(warning_buffer="BUF-TARGET")
    first = stockout_warning().model_copy(
        update={"buffer_code": "BUF-FIRST", "order_code": "ORD-FIRST"}
    )
    second = stockout_warning().model_copy(
        update={"buffer_code": "BUF-SECOND", "order_code": "ORD-SECOND"}
    )
    pipeline = CutlinePipeline()
    _stub_upper_flow(
        monkeypatch,
        pipeline,
        interval_results=[],
        overflow_results=[],
        stockout_warnings=[first, second],
    )

    def find_candidates(snapshot, warnings):
        if failed_stage == "stockout_candidate" and warnings[0] is first:
            raise error
        return [object()]

    def select_machines(**kwargs):
        if failed_stage == "stockout_selection" and kwargs["warning"] is first:
            raise error
        return object()

    def build_decision(snapshot, warning, selection):
        if failed_stage == "stockout_plan" and warning is first:
            raise error
        return _manual_stockout_decision(snapshot, warning)

    monkeypatch.setattr(pipeline._candidate, "find_algorithm", find_candidates)
    monkeypatch.setattr(
        pipeline._selection,
        "select_stockout_machines",
        select_machines,
    )
    monkeypatch.setattr(
        pipeline._plan_builder,
        "build_stockout_decision",
        build_decision,
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert len(result.cutline_decisions) == 1
    assert result.cutline_decisions[0].manual_intervention.buffer_code == "BUF-SECOND"
    assert len(result.errors) == 1
    pipeline_error = result.errors[0]
    assert pipeline_error.stage == failed_stage
    assert pipeline_error.warning_type == "stockout"
    assert pipeline_error.warning_key == "BUF-FIRST:ORD-FIRST:182:N:P01:P02"
    assert pipeline_error.reason == expected_reason
    assert pipeline_error.message == str(error)


@pytest.mark.parametrize(
    ("failed_stage", "error", "expected_reason"),
    [
        (
            "overflow_candidate",
            CandidateMachineCalculationError("overflow candidate failed"),
            "candidate_machine_calculation_error",
        ),
        (
            "overflow_selection",
            MachineSelectionEvaluationError("overflow selection failed"),
            "machine_selection_evaluation_error",
        ),
        ("overflow_plan", RuntimeError("overflow plan failed"), "runtime_error"),
    ],
)
def test_overflow_error_isolated_per_warning_with_stage_context(
    monkeypatch,
    failed_stage,
    error,
    expected_reason,
):
    snapshot = _decision_snapshot(warning_buffer="BUF-OVERFLOW")
    first = overflow_warning().model_copy(update={"buffer_code": "BUF-O1"})
    second = overflow_warning().model_copy(update={"buffer_code": "BUF-O2"})
    pipeline = CutlinePipeline()
    _stub_upper_flow(
        monkeypatch,
        pipeline,
        interval_results=[],
        overflow_results=[],
        overflow_warnings=[first, second],
    )

    def find_candidates(snapshot, warnings, interval_results):
        if failed_stage == "overflow_candidate" and warnings[0] is first:
            raise error
        return [object()]

    def select_machines(**kwargs):
        if failed_stage == "overflow_selection" and kwargs["warning"] is first:
            raise error
        return object()

    def build_decision(snapshot, warning, selection):
        if failed_stage == "overflow_plan" and warning is first:
            raise error
        return _manual_overflow_decision(snapshot, warning)

    monkeypatch.setattr(
        pipeline._overflow_candidate,
        "find_algorithm",
        find_candidates,
    )
    monkeypatch.setattr(
        pipeline._selection,
        "select_overflow_machines",
        select_machines,
    )
    monkeypatch.setattr(
        pipeline._plan_builder,
        "build_overflow_decision",
        build_decision,
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert len(result.cutline_decisions) == 1
    assert result.cutline_decisions[0].manual_intervention.buffer_code == "BUF-O2"
    assert len(result.errors) == 1
    pipeline_error = result.errors[0]
    assert pipeline_error.stage == failed_stage
    assert pipeline_error.warning_type == "overflow"
    assert pipeline_error.warning_key == "BUF-O1:S1:P01:P02"
    assert pipeline_error.reason == expected_reason
    assert pipeline_error.message == str(error)


def test_decision_flow_preserves_upper_results_inputs_and_lower_defaults(monkeypatch):
    snapshot = _decision_snapshot(warning_buffer="BUF-TARGET")
    warning = stockout_warning(buffer_code="BUF-TARGET")
    intervals = default_stockout_intervals()
    overflows = [overflow_state("BUF-SOURCE"), overflow_state("BUF-TARGET")]
    before = {
        "snapshot": snapshot.model_dump(),
        "intervals": [item.model_dump() for item in intervals],
        "overflows": [item.model_dump() for item in overflows],
        "warning": warning.model_dump(),
    }
    pipeline = CutlinePipeline()
    _stub_upper_flow(
        monkeypatch,
        pipeline,
        interval_results=intervals,
        overflow_results=overflows,
        stockout_warnings=[warning],
    )

    result = pipeline.evaluate_algorithm(snapshot)

    assert result.calculation_time == snapshot.current_time
    assert result.net_rate_results == intervals
    assert result.depletion_results == []
    assert result.overflow_time_results == overflows
    assert result.stockout_warnings == [warning]
    assert result.overflow_warnings == []
    assert result.return_results == []
    assert result.silk_screen_results == []
    assert result.mixing_trace_records == []
    assert result.mixing_trace_failures == []
    assert snapshot.model_dump() == before["snapshot"]
    assert [item.model_dump() for item in intervals] == before["intervals"]
    assert [item.model_dump() for item in overflows] == before["overflows"]
    assert warning.model_dump() == before["warning"]


@pytest.mark.parametrize(
    "fatal_error",
    [
        MemoryError("out of memory"),
        SystemExit("system exit"),
        KeyboardInterrupt("keyboard interrupt"),
    ],
)
def test_fatal_errors_from_plan_builder_are_not_isolated(monkeypatch, fatal_error):
    snapshot = _decision_snapshot(warning_buffer="BUF-TARGET")
    warning = stockout_warning(buffer_code="BUF-TARGET")
    pipeline = CutlinePipeline()
    _stub_upper_flow(
        monkeypatch,
        pipeline,
        interval_results=[],
        overflow_results=[],
        stockout_warnings=[warning],
    )
    monkeypatch.setattr(
        pipeline._candidate,
        "find_algorithm",
        lambda snapshot, warnings: [object()],
    )
    monkeypatch.setattr(
        pipeline._selection,
        "select_stockout_machines",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        pipeline._plan_builder,
        "build_stockout_decision",
        lambda snapshot, warning, selection: (_ for _ in ()).throw(
            fatal_error
        ),
    )

    with pytest.raises(type(fatal_error), match=str(fatal_error)):
        pipeline.evaluate_algorithm(snapshot)
