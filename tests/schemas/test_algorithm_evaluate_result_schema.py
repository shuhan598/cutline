from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas import common_schema
from app.schemas import result_schema as schema


NOW = datetime(2026, 7, 16, 12, 0)

LIST_FIELDS = (
    "net_rate_results",
    "depletion_results",
    "overflow_time_results",
    "stockout_warnings",
    "overflow_warnings",
    "cutline_decisions",
    "return_results",
    "new_active_cutline_events",
    "updated_active_cutline_events",
    "silk_screen_results",
    "mixing_trace_records",
    "mixing_trace_failures",
    "errors",
)


def net_rate_result():
    return schema.AlgorithmIntervalNetRateResult(
        main_id="MAIN-1",
        buffer_code="BUF-1",
        buffer_codes=["BUF-1"],
        order_code="ORD-A",
        wafer_size="182",
        wafer_spec="N",
        workshop_code="S1",
        upstream_process_code="P1",
        downstream_process_code="P2",
        current_quantity=100,
        upstream_output_rate=80,
        downstream_input_rate=100,
        net_consumption_rate=20,
    )


def depletion_result():
    return schema.AlgorithmDepletionTimeResult(
        main_id="MAIN-1",
        buffer_code="BUF-1",
        buffer_codes=["BUF-1"],
        order_code="ORD-A",
        wafer_size="182",
        wafer_spec="N",
        workshop_code="S1",
        upstream_process_code="P1",
        downstream_process_code="P2",
        current_quantity=100,
        upstream_output_rate=80,
        downstream_input_rate=100,
        net_consumption_rate=20,
        depletion_minutes=300,
    )


def overflow_time_result():
    return schema.AlgorithmBufferOverflowTimeResult(
        main_id="MAIN-2",
        buffer_code="BUF-2",
        buffer_codes=["BUF-2"],
        workshop_code="S1",
        upstream_process_code="P1",
        downstream_process_code="P2",
        max_capacity=1000,
        total_inventory=900,
        remaining_capacity=100,
        buffer_growth_rate=20,
        overflow_minutes=300,
    )


def stockout_warning():
    return schema.AlgorithmStockoutWarningResult(
        warning_time=NOW,
        main_id="MAIN-1",
        buffer_code="BUF-1",
        buffer_codes=["BUF-1"],
        order_code="ORD-A",
        wafer_size="182",
        wafer_spec="N",
        workshop_code="S1",
        upstream_process_code="P1",
        downstream_process_code="P2",
        current_quantity=100,
        upstream_output_rate=80,
        downstream_input_rate=100,
        net_consumption_rate=20,
        depletion_minutes=300,
        stockout_warning_lead_minutes=360,
    )


def overflow_warning():
    return schema.AlgorithmOverflowWarningResult(
        warning_time=NOW,
        main_id="MAIN-2",
        buffer_code="BUF-2",
        buffer_codes=["BUF-2"],
        workshop_code="S1",
        upstream_process_code="P1",
        downstream_process_code="P2",
        max_capacity=1000,
        total_inventory=900,
        remaining_capacity=100,
        buffer_growth_rate=20,
        overflow_minutes=300,
        overflow_warning_lead_minutes=360,
    )


@pytest.mark.parametrize(
    ("factory", "expected_main_id", "expected_buffer_codes"),
    [
        (net_rate_result, "MAIN-1", ["BUF-1"]),
        (depletion_result, "MAIN-1", ["BUF-1"]),
        (overflow_time_result, "MAIN-2", ["BUF-2"]),
        (stockout_warning, "MAIN-1", ["BUF-1"]),
        (overflow_warning, "MAIN-2", ["BUF-2"]),
    ],
)
def test_buffer_calculation_results_require_and_preserve_group_identity(
    factory,
    expected_main_id,
    expected_buffer_codes,
):
    result = factory()

    assert result.main_id == expected_main_id
    assert result.buffer_codes == expected_buffer_codes
    assert result.__class__.model_fields["main_id"].is_required()
    assert result.__class__.model_fields["buffer_codes"].is_required()


def cutline_decision():
    plan = schema.AlgorithmStockoutCutlinePlan(
        plan_id="PLAN-1",
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
    )
    return schema.AlgorithmCutlineDecisionResult(
        plan=plan,
        manual_intervention=None,
    )


def return_result():
    return schema.AlgorithmReturnResult(
        event_id="CUT-1",
        machine_code="M1",
        source_order_code="ORD-A",
        target_order_code="ORD-B",
        workshop_code="S1",
        source_buffer_code="BUF-1",
        target_buffer_code="BUF-2",
        upstream_process_code="P1",
        downstream_process_code="P2",
        target_wafer_size="182",
        target_wafer_spec="N",
        current_time=NOW,
        cutline_start_time=NOW,
        previous_negative_start_time=None,
        updated_negative_start_time=None,
        cutline_duration_minutes=0,
        negative_duration_minutes=0,
        net_consumption_rate=1,
        current_quantity=100,
        stability_window_minutes=20,
        stockout_warning_lead_minutes=30,
        safe_inventory_quantity=50,
        condition_net_rate_met=False,
        condition_stability_met=False,
        condition_inventory_met=True,
        return_recommended=False,
        previous_status="active",
        updated_status="active",
        reason="net_rate_not_negative",
    )


def active_cutline_event():
    return common_schema.AlgorithmActiveCutlineEvent(
        event_id="CUT-PLAN-1-M1",
        plan_id="PLAN-1",
        machine_code="M1",
        source_order_code="ORD-A",
        target_order_code="ORD-B",
        workshop_code="S1",
        source_buffer_code="BUF-A",
        target_buffer_code="BUF-B",
        upstream_process_code="P1",
        downstream_process_code="P2",
        source_wafer_size="182",
        source_wafer_spec="N",
        target_wafer_size="182",
        target_wafer_spec="R",
        cutline_start_time=NOW,
    )


def silk_screen_result():
    return schema.AlgorithmSilkScreenTransitionResult(
        workshop_code="S1",
        process_code="SW",
        process_name="丝网",
        current_order_code="ORD-A",
        current_product_code="PROD-A",
        machine_codes=["M1"],
        total_quantity=1000,
        produced_quantity=500,
        remaining_quantity=500,
        current_order_output_rate=100,
        remaining_production_hours=5,
        current_time=NOW,
        estimated_finish_time=NOW,
        silk_screen_clear_minutes=30,
        clearance_prepare_time=NOW,
        prepare_clearance=False,
        reason="not_yet_time_to_prepare",
        message="not yet time",
    )


def mixing_record():
    return schema.AlgorithmMixingTraceRecord(
        mix_trace_id="MIX-PLAN-1-M1",
        plan_id="PLAN-1",
        cutline_event_id="CUT-PLAN-1-M1",
        machine_code="M1",
        workshop_code="S1",
        process_code="P1",
        process_name="制绒",
        source_order_code="ORD-A",
        target_order_code="ORD-B",
        source_product_code="PROD-A",
        target_product_code="PROD-B",
        mix_start_time=NOW,
        mixed_basket_start_index=1,
        mixed_basket_end_index=10,
        mixed_basket_count=10,
        estimated_total_mixed_pieces=1200,
        compositions=[],
        notification_status="due",
    )


def mixing_failure():
    return schema.AlgorithmMixingTraceFailure(
        plan_id="PLAN-1",
        cutline_event_id="CUT-PLAN-1-M2",
        machine_code="M2",
        source_order_code="ORD-A",
        target_order_code="ORD-B",
        reason="machine_runtime_not_found",
        message="runtime missing",
    )


def test_empty_algorithm_evaluate_result_requires_only_calculation_time():
    result = schema.AlgorithmEvaluateResult(calculation_time=NOW)

    assert result.calculation_time == NOW
    assert set(result.model_fields) == {
        "calculation_time",
        *LIST_FIELDS,
        "persistence_state",
    }
    assert all(getattr(result, field_name) == [] for field_name in LIST_FIELDS)
    assert isinstance(result.persistence_state, schema.AlgorithmPersistenceState)


def test_algorithm_persistence_state_is_strict_and_keeps_full_active_events():
    event = active_cutline_event()
    state = schema.AlgorithmPersistenceState(
        active_cutline_events=[event],
        expired_pending_plan_ids=["PLAN-EXPIRED"],
        completed_pending_plan_ids=["PLAN-COMPLETE"],
        return_suggested_event_ids=[event.event_id],
        mixed_cutline_event_ids=[event.event_id],
    )

    assert state.active_cutline_events == [event]
    assert state.return_suggested_event_ids == [event.event_id]
    with pytest.raises(ValidationError):
        schema.AlgorithmPersistenceState(unexpected=True)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("return_suggested_event_ids", ["CUT-1", "CUT-1"]),
        ("mixed_cutline_event_ids", ["CUT-1", "CUT-1"]),
        ("return_suggested_event_ids", ["   "]),
        ("mixed_cutline_event_ids", [""]),
    ],
)
def test_algorithm_persistence_state_rejects_duplicate_or_blank_watermarks(
    field_name, value
):
    with pytest.raises(ValidationError, match=field_name):
        schema.AlgorithmPersistenceState(**{field_name: value})


def test_all_algorithm_evaluate_result_lists_use_independent_factories():
    first = schema.AlgorithmEvaluateResult(calculation_time=NOW)
    second = schema.AlgorithmEvaluateResult(calculation_time=NOW)

    assert first.new_active_cutline_events is not first.updated_active_cutline_events
    for field_name in LIST_FIELDS:
        field = schema.AlgorithmEvaluateResult.model_fields[field_name]
        assert field.default_factory is list
        assert getattr(first, field_name) is not getattr(second, field_name)


def test_algorithm_evaluate_result_uses_existing_result_types():
    expected_annotations = {
        "net_rate_results": list[schema.AlgorithmIntervalNetRateResult],
        "depletion_results": list[schema.AlgorithmDepletionTimeResult],
        "overflow_time_results": list[schema.AlgorithmBufferOverflowTimeResult],
        "stockout_warnings": list[schema.AlgorithmStockoutWarningResult],
        "overflow_warnings": list[schema.AlgorithmOverflowWarningResult],
        "cutline_decisions": list[schema.AlgorithmCutlineDecisionResult],
        "return_results": list[schema.AlgorithmReturnResult],
        "new_active_cutline_events": list[common_schema.AlgorithmActiveCutlineEvent],
        "updated_active_cutline_events": list[
            common_schema.AlgorithmActiveCutlineEvent
        ],
        "silk_screen_results": list[schema.AlgorithmSilkScreenTransitionResult],
        "mixing_trace_records": list[schema.AlgorithmMixingTraceRecord],
        "mixing_trace_failures": list[schema.AlgorithmMixingTraceFailure],
        "errors": list[schema.AlgorithmPipelineError],
    }

    for field_name, expected in expected_annotations.items():
        assert schema.AlgorithmEvaluateResult.model_fields[field_name].annotation == expected


def test_algorithm_evaluate_result_accepts_all_existing_module_results():
    values = {
        "net_rate_results": [net_rate_result()],
        "depletion_results": [depletion_result()],
        "overflow_time_results": [overflow_time_result()],
        "stockout_warnings": [stockout_warning()],
        "overflow_warnings": [overflow_warning()],
        "cutline_decisions": [cutline_decision()],
        "return_results": [return_result()],
        "silk_screen_results": [silk_screen_result()],
        "mixing_trace_records": [mixing_record()],
        "mixing_trace_failures": [mixing_failure()],
    }

    result = schema.AlgorithmEvaluateResult(calculation_time=NOW, **values)

    for field_name, expected in values.items():
        assert getattr(result, field_name) == expected


def test_algorithm_evaluate_result_accepts_existing_active_cutline_events():
    event = active_cutline_event()

    result = schema.AlgorithmEvaluateResult(
        calculation_time=NOW,
        new_active_cutline_events=[event],
        updated_active_cutline_events=[event],
    )

    assert result.new_active_cutline_events == [event]
    assert result.updated_active_cutline_events == [event]


def test_algorithm_pipeline_error_required_and_optional_fields():
    error = schema.AlgorithmPipelineError(
        stage="stockout_warning",
        reason="warning_calculation_failed",
        message="one warning failed",
    )

    assert error.model_dump() == {
        "stage": "stockout_warning",
        "warning_type": None,
        "warning_key": None,
        "reason": "warning_calculation_failed",
        "message": "one warning failed",
    }

    with pytest.raises(ValidationError):
        schema.AlgorithmPipelineError(reason="missing_stage", message="bad")


def test_existing_cutline_decision_validation_is_unchanged():
    with pytest.raises(ValidationError, match="exactly one"):
        schema.AlgorithmCutlineDecisionResult(
            plan=None,
            manual_intervention=None,
        )
