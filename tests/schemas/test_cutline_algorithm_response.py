from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas import common_schema
from app.schemas import response_schema as response
from app.schemas import result_schema as result
from tests.schemas import test_algorithm_evaluate_result_schema as helpers


NOW = datetime(2026, 7, 16, 12, 0)

LIST_FIELDS = (
    "stockout_warnings",
    "overflow_warnings",
    "cutline_decisions",
    "return_results",
    "silk_screen_results",
    "mixing_trace_records",
    "mixing_trace_failures",
    "new_active_cutline_events",
    "updated_active_cutline_events",
    "errors",
)


def manual_intervention_decision() -> result.AlgorithmCutlineDecisionResult:
    intervention = result.AlgorithmManualInterventionResult(
        warning_type="stockout",
        warning_time=NOW,
        workshop_code="S1",
        buffer_code="BUF-1",
        order_code="ORD-A",
        wafer_size="182",
        wafer_spec="N",
        upstream_process_code="P1",
        downstream_process_code="P2",
        reason="capacity_gap_remains",
        initial_risk_value=10,
        remaining_risk_value=4,
        evaluated_candidate_count=0,
        passed_candidate_count=0,
        rejected_candidate_count=0,
    )
    return result.AlgorithmCutlineDecisionResult(
        plan=None,
        manual_intervention=intervention,
    )


def selected_machine_with_idle_rate(
    idle_rate: float,
) -> result.AlgorithmSelectedMachineEvaluation:
    return result.AlgorithmSelectedMachineEvaluation(
        machine_code="M1",
        source_order_code="ORD-A",
        target_order_code="ORD-B",
        source_buffer_code="BUF-A",
        target_buffer_code="BUF-B",
        process_code="P1",
        workshop_code="S1",
        wafer_size="182",
        source_wafer_spec="N",
        target_wafer_spec="R",
        contribution_capacity=1,
        utilization_rate=1.25,
        idle_rate=idle_rate,
        source_net_rate_before=10,
        source_net_rate_after=9,
        target_net_rate_before=10,
        target_net_rate_after=9,
    )


def test_empty_response_requires_only_calculation_time():
    value = response.CutlineAlgorithmResponse(calculation_time=NOW)

    assert value.calculation_time == NOW
    assert set(value.model_fields) == {"calculation_time", *LIST_FIELDS}
    assert all(getattr(value, field_name) == [] for field_name in LIST_FIELDS)
    with pytest.raises(ValidationError):
        response.CutlineAlgorithmResponse()


def test_all_response_lists_use_independent_default_factories():
    first = response.CutlineAlgorithmResponse(calculation_time=NOW)
    second = response.CutlineAlgorithmResponse(calculation_time=NOW)

    for field_name in LIST_FIELDS:
        field = response.CutlineAlgorithmResponse.model_fields[field_name]
        assert field.default_factory is list
        assert getattr(first, field_name) is not getattr(second, field_name)
    assert first.new_active_cutline_events is not first.updated_active_cutline_events


def test_response_reuses_exact_existing_result_types_without_diagnostics():
    expected_annotations = {
        "stockout_warnings": list[result.AlgorithmStockoutWarningResult],
        "overflow_warnings": list[result.AlgorithmOverflowWarningResult],
        "cutline_decisions": list[result.AlgorithmCutlineDecisionResult],
        "return_results": list[result.AlgorithmReturnResult],
        "silk_screen_results": list[
            result.AlgorithmSilkScreenTransitionResult
        ],
        "mixing_trace_records": list[result.AlgorithmMixingTraceRecord],
        "mixing_trace_failures": list[result.AlgorithmMixingTraceFailure],
        "new_active_cutline_events": list[
            common_schema.AlgorithmActiveCutlineEvent
        ],
        "updated_active_cutline_events": list[
            common_schema.AlgorithmActiveCutlineEvent
        ],
        "errors": list[result.AlgorithmPipelineError],
    }

    for field_name, expected in expected_annotations.items():
        assert response.CutlineAlgorithmResponse.model_fields[
            field_name
        ].annotation == expected
    assert not {
        "net_rate_results",
        "depletion_results",
        "overflow_time_results",
    } & response.CutlineAlgorithmResponse.model_fields.keys()


def test_response_accepts_stockout_warning():
    warning = helpers.stockout_warning()

    value = response.CutlineAlgorithmResponse(
        calculation_time=NOW,
        stockout_warnings=[warning],
    )

    assert value.stockout_warnings == [warning]


def test_response_accepts_overflow_warning():
    warning = helpers.overflow_warning()

    value = response.CutlineAlgorithmResponse(
        calculation_time=NOW,
        overflow_warnings=[warning],
    )

    assert value.overflow_warnings == [warning]


def test_response_accepts_formal_cutline_plan_decision():
    decision = helpers.cutline_decision()

    value = response.CutlineAlgorithmResponse(
        calculation_time=NOW,
        cutline_decisions=[decision],
    )

    assert value.cutline_decisions == [decision]


def test_response_accepts_manual_intervention_decision():
    decision = manual_intervention_decision()

    value = response.CutlineAlgorithmResponse(
        calculation_time=NOW,
        cutline_decisions=[decision],
    )

    assert value.cutline_decisions == [decision]


def test_response_accepts_return_result():
    return_result = helpers.return_result()

    value = response.CutlineAlgorithmResponse(
        calculation_time=NOW,
        return_results=[return_result],
    )

    assert value.return_results == [return_result]


def test_response_accepts_silk_screen_result():
    silk_screen_result = helpers.silk_screen_result()

    value = response.CutlineAlgorithmResponse(
        calculation_time=NOW,
        silk_screen_results=[silk_screen_result],
    )

    assert value.silk_screen_results == [silk_screen_result]


def test_response_accepts_mixing_trace_record():
    record = helpers.mixing_record()

    value = response.CutlineAlgorithmResponse(
        calculation_time=NOW,
        mixing_trace_records=[record],
    )

    assert value.mixing_trace_records == [record]


def test_response_accepts_mixing_trace_failure():
    failure = helpers.mixing_failure()

    value = response.CutlineAlgorithmResponse(
        calculation_time=NOW,
        mixing_trace_failures=[failure],
    )

    assert value.mixing_trace_failures == [failure]


def test_response_accepts_new_active_cutline_event():
    event = helpers.active_cutline_event()

    value = response.CutlineAlgorithmResponse(
        calculation_time=NOW,
        new_active_cutline_events=[event],
    )

    assert value.new_active_cutline_events == [event]


def test_response_accepts_updated_active_cutline_event():
    event = helpers.active_cutline_event()

    value = response.CutlineAlgorithmResponse(
        calculation_time=NOW,
        updated_active_cutline_events=[event],
    )

    assert value.updated_active_cutline_events == [event]


def test_response_accepts_pipeline_error():
    error = result.AlgorithmPipelineError(
        stage="stockout_warning",
        reason="warning_calculation_failed",
        message="one warning failed",
    )

    value = response.CutlineAlgorithmResponse(
        calculation_time=NOW,
        errors=[error],
    )

    assert value.errors == [error]


def test_response_preserves_negative_idle_rate_from_real_result_type():
    machine = selected_machine_with_idle_rate(-0.25)
    plan = result.AlgorithmStockoutCutlinePlan(
        plan_id="PLAN-NEGATIVE-IDLE",
        calculation_time=NOW,
        workshop_code="S1",
        buffer_code="BUF-1",
        order_code="ORD-A",
        wafer_size="182",
        wafer_spec="N",
        upstream_process_code="P1",
        downstream_process_code="P2",
        initial_capacity_gap=1,
        total_contribution_capacity=1,
        remaining_capacity_gap=0,
        selected_machines=[machine],
    )
    decision = result.AlgorithmCutlineDecisionResult(
        plan=plan,
        manual_intervention=None,
    )

    value = response.CutlineAlgorithmResponse(
        calculation_time=NOW,
        cutline_decisions=[decision],
    )

    assert value.cutline_decisions[0].plan.selected_machines[0].idle_rate == -0.25
