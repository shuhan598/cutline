import pytest
from pydantic import ValidationError

from app.core.candidate_machine.machine_load import calculate_runtime_load
from app.core.cutline_plan.machine_selection_evaluator import (
    MachineSelectionEvaluator,
)
from app.core.cutline_plan.plan_builder import CutlinePlanBuilder
from app.schemas.result_schema import (
    AlgorithmOverflowSelectionResult,
    AlgorithmRejectedMachineEvaluation,
    AlgorithmSelectedMachineEvaluation,
    AlgorithmStockoutSelectionResult,
)
from tests.core.cutline_plan.helpers import (
    algorithm_snapshot,
    overflow_warning,
    stockout_warning,
)


def _selected(machine_code: str = "M-01"):
    utilization_rate, idle_rate = calculate_runtime_load(
        input_quantity_30m=5000,
        output_quantity_30m=4000,
    )
    return AlgorithmSelectedMachineEvaluation(
        machine_code=machine_code,
        source_order_code="ORD-SOURCE",
        target_order_code="ORD-TARGET",
        source_buffer_code="BUF-SOURCE",
        target_buffer_code="BUF-TARGET",
        process_code="P01",
        workshop_code="S1",
        wafer_size="182",
        source_wafer_spec="N",
        target_wafer_spec="N",
        contribution_capacity=8000,
        reduced_capacity=None,
        utilization_rate=utilization_rate,
        idle_rate=idle_rate,
        source_net_rate_before=-10000,
        source_net_rate_after=-2000,
        source_depletion_minutes_after=None,
        target_net_rate_before=10000,
        target_net_rate_after=2000,
        target_overflow_minutes_after=120,
    )


def _rejected(machine_code: str = "M-02"):
    return AlgorithmRejectedMachineEvaluation(
        machine_code=machine_code,
        reason="source_order_stockout_risk",
        source_order_code="ORD-OTHER",
        target_order_code="ORD-TARGET",
        source_buffer_code="BUF-OTHER",
        target_buffer_code="BUF-TARGET",
        source_net_rate_before=0,
        source_net_rate_after=5000,
        source_depletion_minutes_after=20,
        message="unsafe source impact",
    )


def _stockout_selection(*, resolved: bool):
    return AlgorithmStockoutSelectionResult(
        workshop_code="S1",
        buffer_code="BUF-TARGET",
        order_code="ORD-TARGET",
        wafer_size="182",
        wafer_spec="N",
        upstream_process_code="P01",
        downstream_process_code="P02",
        initial_capacity_gap=10000,
        total_contribution_capacity=10000 if resolved else 4000,
        remaining_capacity_gap=0 if resolved else 6000,
        selected_machines=[_selected()],
        rejected_machines=[_rejected()],
        risk_resolved=resolved,
        failure_reason=None if resolved else "insufficient_contribution_capacity",
    )


def _overflow_selection(*, resolved: bool):
    selected = _selected().model_copy(
        update={"contribution_capacity": None, "reduced_capacity": 8000}
    )
    return AlgorithmOverflowSelectionResult(
        workshop_code="S1",
        buffer_code="BUF-OVERFLOW",
        upstream_process_code="P01",
        downstream_process_code="P02",
        source_order_code="ORD-SOURCE",
        source_wafer_size="182",
        source_wafer_spec="N",
        initial_growth_rate=10000,
        total_reduced_capacity=8000,
        remaining_growth_rate=0 if resolved else 2000,
        updated_overflow_minutes=None if resolved else 20,
        selected_machines=[selected],
        rejected_machines=[_rejected()],
        risk_resolved=resolved,
        failure_reason=None if resolved else "insufficient_reduced_capacity",
    )


def test_resolved_stockout_builds_plan_without_manual_intervention():
    snapshot = algorithm_snapshot()
    decision = CutlinePlanBuilder().build_stockout_decision(
        snapshot,
        stockout_warning(),
        _stockout_selection(resolved=True),
    )

    assert decision.plan is not None
    assert decision.manual_intervention is None
    assert decision.plan.warning_type == "stockout"
    assert decision.plan.calculation_time == snapshot.current_time
    assert decision.plan.plan_id
    assert decision.plan.risk_resolved is True
    assert decision.plan.manual_intervention_required is False


def test_unresolved_stockout_builds_only_manual_intervention():
    warning = stockout_warning()
    decision = CutlinePlanBuilder().build_stockout_decision(
        algorithm_snapshot(),
        warning,
        _stockout_selection(resolved=False),
    )

    assert decision.plan is None
    assert decision.manual_intervention is not None
    assert decision.manual_intervention.warning_time == warning.warning_time
    assert decision.manual_intervention.manual_intervention_required is True
    assert decision.manual_intervention.risk_resolved is False


def test_resolved_overflow_builds_plan_without_manual_intervention():
    snapshot = algorithm_snapshot()
    decision = CutlinePlanBuilder().build_overflow_decision(
        snapshot,
        overflow_warning(),
        _overflow_selection(resolved=True),
    )

    assert decision.plan is not None
    assert decision.manual_intervention is None
    assert decision.plan.warning_type == "overflow"
    assert decision.plan.calculation_time == snapshot.current_time
    assert decision.plan.source_order_code == "ORD-SOURCE"


def test_unresolved_overflow_builds_only_manual_intervention():
    decision = CutlinePlanBuilder().build_overflow_decision(
        algorithm_snapshot(),
        overflow_warning(),
        _overflow_selection(resolved=False),
    )

    assert decision.plan is None
    assert decision.manual_intervention is not None
    assert decision.manual_intervention.source_order_code == "ORD-SOURCE"
    assert decision.manual_intervention.remaining_risk_value == 2000


def test_formal_plan_contains_only_selected_machines():
    decision = CutlinePlanBuilder().build_stockout_decision(
        algorithm_snapshot(),
        stockout_warning(),
        _stockout_selection(resolved=True),
    )

    assert [item.machine_code for item in decision.plan.selected_machines] == [
        "M-01"
    ]
    assert not hasattr(decision.plan, "rejected_machines")


def test_manual_intervention_keeps_passed_and_rejected_diagnostics():
    decision = CutlinePlanBuilder().build_stockout_decision(
        algorithm_snapshot(),
        stockout_warning(),
        _stockout_selection(resolved=False),
    )
    manual = decision.manual_intervention

    assert [item.machine_code for item in manual.passed_machines] == ["M-01"]
    assert [item.machine_code for item in manual.rejected_machines] == ["M-02"]
    assert manual.evaluated_candidate_count == 2
    assert manual.passed_candidate_count == 1
    assert manual.rejected_candidate_count == 1


def test_builder_uses_snapshot_time_instead_of_wall_clock():
    snapshot = algorithm_snapshot()
    stockout_decision = CutlinePlanBuilder().build_stockout_decision(
        snapshot,
        stockout_warning(),
        _stockout_selection(resolved=True),
    )
    overflow_decision = CutlinePlanBuilder().build_overflow_decision(
        snapshot,
        overflow_warning(),
        _overflow_selection(resolved=True),
    )

    assert stockout_decision.plan.calculation_time == snapshot.current_time
    assert overflow_decision.plan.calculation_time == snapshot.current_time


def test_builder_does_not_mutate_warning_or_selection_inputs():
    warning = stockout_warning()
    selection = _stockout_selection(resolved=False)
    before = warning.model_dump(), selection.model_dump()

    CutlinePlanBuilder().build_stockout_decision(
        algorithm_snapshot(), warning, selection
    )

    assert warning.model_dump() == before[0]
    assert selection.model_dump() == before[1]


@pytest.mark.parametrize(
    ("contribution_capacity", "reduced_capacity"),
    [(None, None), (8000, 8000)],
)
def test_selected_machine_requires_exactly_one_capacity_kind(
    contribution_capacity,
    reduced_capacity,
):
    data = _selected().model_dump()
    data.update(
        contribution_capacity=contribution_capacity,
        reduced_capacity=reduced_capacity,
    )

    with pytest.raises(ValidationError, match="exactly one"):
        AlgorithmSelectedMachineEvaluation(**data)


def test_stockout_selection_allows_resolved_state_with_remaining_gap():
    data = _stockout_selection(resolved=True).model_dump()
    data["remaining_capacity_gap"] = 1

    selection = AlgorithmStockoutSelectionResult(**data)

    assert selection.risk_resolved is True
    assert selection.remaining_capacity_gap == 1


def test_resolved_selection_rejects_failure_reason():
    data = _overflow_selection(resolved=True).model_dump()
    data["failure_reason"] = "insufficient_reduced_capacity"

    with pytest.raises(ValidationError, match="failure reason"):
        AlgorithmOverflowSelectionResult(**data)


def test_unresolved_selection_requires_failure_reason():
    data = _overflow_selection(resolved=False).model_dump()
    data["failure_reason"] = None

    with pytest.raises(ValidationError, match="failure reason"):
        AlgorithmOverflowSelectionResult(**data)


def test_builder_does_not_rerun_candidate_or_impact_evaluation(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("selection evaluator must not be called")

    monkeypatch.setattr(
        MachineSelectionEvaluator,
        "select_stockout_machines",
        fail_if_called,
    )
    monkeypatch.setattr(
        MachineSelectionEvaluator,
        "select_overflow_machines",
        fail_if_called,
    )

    decision = CutlinePlanBuilder().build_stockout_decision(
        algorithm_snapshot(),
        stockout_warning(),
        _stockout_selection(resolved=True),
    )

    assert decision.plan is not None
