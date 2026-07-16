from datetime import datetime

from app.mappers.algorithm_response_mapper import AlgorithmResponseMapper
from app.schemas import result_schema as result
from app.schemas.response_schema import CutlineAlgorithmResponse
from tests.schemas import test_algorithm_evaluate_result_schema as helpers
from tests.schemas import test_cutline_algorithm_response as response_helpers


NOW = datetime(2026, 7, 16, 12, 0)

MAPPED_FIELDS = (
    "calculation_time",
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


def pipeline_error(reason: str = "warning_calculation_failed"):
    return result.AlgorithmPipelineError(
        stage="stockout_warning",
        warning_type="stockout",
        warning_key="BUF-1/ORD-A",
        reason=reason,
        message="one warning failed",
    )


def evaluate_result_with_all_response_fields():
    new_event = helpers.active_cutline_event()
    updated_event = helpers.active_cutline_event().model_copy(
        update={"event_id": "CUT-PLAN-1-M2", "machine_code": "M2"}
    )
    return result.AlgorithmEvaluateResult(
        calculation_time=NOW,
        stockout_warnings=[helpers.stockout_warning()],
        overflow_warnings=[helpers.overflow_warning()],
        cutline_decisions=[helpers.cutline_decision()],
        return_results=[helpers.return_result()],
        silk_screen_results=[helpers.silk_screen_result()],
        mixing_trace_records=[helpers.mixing_record()],
        mixing_trace_failures=[helpers.mixing_failure()],
        new_active_cutline_events=[new_event],
        updated_active_cutline_events=[updated_event],
        errors=[pipeline_error()],
    )


def test_to_response_maps_every_public_response_field():
    source = evaluate_result_with_all_response_fields()

    response = AlgorithmResponseMapper().to_response(source)

    assert isinstance(response, CutlineAlgorithmResponse)
    assert set(response.model_fields) == set(MAPPED_FIELDS)
    for field_name in MAPPED_FIELDS:
        assert getattr(response, field_name) == getattr(source, field_name)


def test_to_response_preserves_formal_cutline_decision():
    decision = helpers.cutline_decision()
    source = result.AlgorithmEvaluateResult(
        calculation_time=NOW,
        cutline_decisions=[decision],
    )

    response = AlgorithmResponseMapper().to_response(source)

    assert response.cutline_decisions == [decision]
    assert response.cutline_decisions[0].plan is not None


def test_to_response_preserves_manual_intervention_decision():
    decision = response_helpers.manual_intervention_decision()
    source = result.AlgorithmEvaluateResult(
        calculation_time=NOW,
        cutline_decisions=[decision],
    )

    response = AlgorithmResponseMapper().to_response(source)

    assert response.cutline_decisions == [decision]
    assert response.cutline_decisions[0].manual_intervention is not None


def test_to_response_does_not_expose_internal_calculation_results():
    source = result.AlgorithmEvaluateResult(
        calculation_time=NOW,
        net_rate_results=[helpers.net_rate_result()],
        depletion_results=[helpers.depletion_result()],
        overflow_time_results=[helpers.overflow_time_result()],
    )

    response = AlgorithmResponseMapper().to_response(source)

    assert not {
        "net_rate_results",
        "depletion_results",
        "overflow_time_results",
    } & response.model_fields.keys()


def test_to_response_does_not_modify_source_dump():
    source = evaluate_result_with_all_response_fields()
    source_dump = source.model_dump()

    AlgorithmResponseMapper().to_response(source)

    assert source.model_dump() == source_dump


def test_to_response_preserves_list_order():
    first_warning = helpers.stockout_warning()
    second_warning = helpers.stockout_warning().model_copy(
        update={"buffer_code": "BUF-2", "order_code": "ORD-B"}
    )
    first_error = pipeline_error("first")
    second_error = pipeline_error("second")
    source = result.AlgorithmEvaluateResult(
        calculation_time=NOW,
        stockout_warnings=[second_warning, first_warning],
        errors=[second_error, first_error],
    )

    response = AlgorithmResponseMapper().to_response(source)

    assert [item.buffer_code for item in response.stockout_warnings] == [
        "BUF-2",
        "BUF-1",
    ]
    assert [item.reason for item in response.errors] == ["second", "first"]


def test_to_response_keeps_new_and_updated_events_separate():
    new_event = helpers.active_cutline_event()
    updated_event = helpers.active_cutline_event().model_copy(
        update={"event_id": "CUT-PLAN-1-M2", "machine_code": "M2"}
    )
    source = result.AlgorithmEvaluateResult(
        calculation_time=NOW,
        new_active_cutline_events=[new_event],
        updated_active_cutline_events=[updated_event],
    )

    response = AlgorithmResponseMapper().to_response(source)

    assert response.new_active_cutline_events == [new_event]
    assert response.updated_active_cutline_events == [updated_event]


def test_to_response_does_not_clamp_negative_idle_rate():
    machine = response_helpers.selected_machine_with_idle_rate(-0.25)
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
    source = result.AlgorithmEvaluateResult(
        calculation_time=NOW,
        cutline_decisions=[decision],
    )

    response = AlgorithmResponseMapper().to_response(source)

    mapped_machine = response.cutline_decisions[0].plan.selected_machines[0]
    assert mapped_machine.idle_rate == -0.25
