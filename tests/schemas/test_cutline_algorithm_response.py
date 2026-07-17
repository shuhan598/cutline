from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas import response_schema as response


NOW = datetime(2026, 7, 17, 8, 0)

LIST_FIELDS = (
    "stockout_warnings",
    "overflow_warnings",
    "cutline_decisions",
    "return_recommendations",
    "silk_screen_results",
    "mixing_trace_records",
    "new_active_cutline_events",
    "updated_active_cutline_events",
    "closed_active_cutline_event_ids",
    "errors",
)


def stockout_selected_machine(**updates):
    values = {
        "machine_code": "EA004",
        "source_order_code": "ORD-S2-002",
        "target_order_code": "ORD-S2-001",
        "source_buffer_code": "310110302",
        "target_buffer_code": "310110302",
        "process_code": "制绒",
        "workshop_code": "S2",
        "wafer_size": "182",
        "source_wafer_spec": "N",
        "target_wafer_spec": "N",
        "contribution_capacity": 600.0,
    }
    values.update(updates)
    return response.StockoutSelectedMachineResponse(**values)


def stockout_plan(**updates):
    values = {
        "plan_id": "stockout:2026-07-17T08:00:00:310110302:ORD-S2-001",
        "warning_type": "stockout",
        "calculation_time": NOW,
        "workshop_code": "S2",
        "buffer_code": "310110302",
        "order_code": "ORD-S2-001",
        "wafer_size": "182",
        "wafer_spec": "N",
        "upstream_process_code": "制绒",
        "downstream_process_code": "碱抛",
        "initial_capacity_gap": 400.0,
        "total_contribution_capacity": 600.0,
        "remaining_capacity_gap": 0.0,
        "selected_machines": [stockout_selected_machine()],
    }
    values.update(updates)
    return response.StockoutCutlinePlanResponse(**values)


def return_recommendation(event_id: str = "CUT-001"):
    return response.ReturnRecommendationResponse(
        event_id=event_id,
        machine_code="EA004",
        source_order_code="ORD-S2-002",
        target_order_code="ORD-S2-001",
        return_recommended_time=NOW,
    )


def active_event():
    return response.ActiveCutlineEventResponse(
        event_id="CUT-001",
        machine_code="EA004",
        source_order_code="ORD-S2-002",
        target_order_code="ORD-S2-001",
        workshop_code="S2",
        target_buffer_code="310110302",
        upstream_process_code="制绒",
        downstream_process_code="碱抛",
        target_wafer_size="182",
        target_wafer_spec="N",
        cutline_start_time=NOW,
        negative_start_time=None,
    )


def test_empty_response_has_only_the_final_public_top_level_contract():
    value = response.CutlineAlgorithmResponse(calculation_time=NOW)

    assert value.calculation_time == NOW
    assert set(value.model_fields) == {"calculation_time", *LIST_FIELDS}
    assert all(getattr(value, field_name) == [] for field_name in LIST_FIELDS)
    assert "return_results" not in value.model_fields
    assert "mixing_trace_failures" not in value.model_fields
    with pytest.raises(ValidationError):
        response.CutlineAlgorithmResponse()


def test_all_response_lists_use_independent_default_factories():
    first = response.CutlineAlgorithmResponse(calculation_time=NOW)
    second = response.CutlineAlgorithmResponse(calculation_time=NOW)

    for field_name in LIST_FIELDS:
        field = response.CutlineAlgorithmResponse.model_fields[field_name]
        assert field.default_factory is list
        assert getattr(first, field_name) is not getattr(second, field_name)


def test_automatic_decision_serializes_only_plan_branch_and_public_fields():
    decision = response.AutomaticCutlineDecisionResponse(
        warning_id="stockout:2026-07-17T08:00:00:310110302:ORD-S2-001",
        plan=stockout_plan(),
    )

    serialized = decision.model_dump(mode="json")

    assert set(serialized) == {"warning_id", "plan"}
    assert "manual_intervention" not in serialized
    assert "risk_resolved" not in serialized["plan"]
    assert "manual_intervention_required" not in serialized["plan"]
    machine = serialized["plan"]["selected_machines"][0]
    assert set(machine) == {
        "machine_code",
        "source_order_code",
        "target_order_code",
        "source_buffer_code",
        "target_buffer_code",
        "process_code",
        "workshop_code",
        "wafer_size",
        "source_wafer_spec",
        "target_wafer_spec",
        "contribution_capacity",
    }
    assert machine["contribution_capacity"] == 600.0
    assert "reduced_capacity" not in machine
    assert "idle_rate" not in machine
    assert "utilization_rate" not in machine
    assert not any("net_rate" in key for key in machine)


def test_manual_decision_serializes_only_manual_branch_and_reason():
    decision = response.ManualCutlineDecisionResponse(
        warning_id="stockout:2026-07-17T08:00:00:310110302:ORD-S2-001",
        manual_intervention=response.ManualInterventionResponse(
            reason="no_candidate_machine"
        ),
    )

    serialized = decision.model_dump(mode="json")

    assert set(serialized) == {"warning_id", "manual_intervention"}
    assert "plan" not in serialized
    assert serialized["manual_intervention"] == {
        "reason": "no_candidate_machine"
    }


def test_decision_models_reject_the_other_branch_as_an_extra_field():
    with pytest.raises(ValidationError):
        response.AutomaticCutlineDecisionResponse(
            warning_id="warning-1",
            plan=stockout_plan(),
            manual_intervention={"reason": "not_allowed"},
        )
    with pytest.raises(ValidationError):
        response.ManualCutlineDecisionResponse(
            warning_id="warning-1",
            manual_intervention={"reason": "no_candidate_machine"},
            plan=stockout_plan(),
        )


def test_active_event_contains_only_fields_needed_for_future_return_checks():
    serialized = active_event().model_dump(mode="json")

    assert set(serialized) == {
        "event_id",
        "machine_code",
        "source_order_code",
        "target_order_code",
        "workshop_code",
        "target_buffer_code",
        "upstream_process_code",
        "downstream_process_code",
        "target_wafer_size",
        "target_wafer_spec",
        "cutline_start_time",
        "negative_start_time",
    }
    assert serialized["negative_start_time"] is None
    assert "status" not in serialized
    assert "plan_id" not in serialized


def test_event_update_always_serializes_negative_start_time_even_when_null():
    update = response.ActiveCutlineEventUpdateResponse(
        event_id="CUT-001",
        negative_start_time=None,
    )

    assert update.model_dump(mode="json") == {
        "event_id": "CUT-001",
        "negative_start_time": None,
    }


def test_response_requires_return_recommendations_and_closed_ids_to_match():
    recommendation = return_recommendation("CUT-001")

    valid = response.CutlineAlgorithmResponse(
        calculation_time=NOW,
        return_recommendations=[recommendation],
        closed_active_cutline_event_ids=["CUT-001"],
    )
    assert valid.return_recommendations == [recommendation]

    with pytest.raises(ValidationError, match="closed active cutline event ids"):
        response.CutlineAlgorithmResponse(
            calculation_time=NOW,
            return_recommendations=[recommendation],
        )
    with pytest.raises(ValidationError, match="closed active cutline event ids"):
        response.CutlineAlgorithmResponse(
            calculation_time=NOW,
            closed_active_cutline_event_ids=["CUT-001"],
        )


def test_silk_screen_response_has_only_customer_facing_fields():
    result = response.SilkScreenClearanceResponse(
        workshop_code="S2",
        current_order_code="ORD-S2-001",
        machine_codes=["EA021"],
        calculation_time=NOW,
        silk_screen_clear_minutes=30.0,
        remaining_production_hours=2.5,
        prepare_clearance=True,
        reason="clearance_preparation_required",
        message="当前订单已进入丝网清台准备窗口。",
    )

    serialized = result.model_dump(mode="json")

    assert set(serialized) == {
        "workshop_code",
        "current_order_code",
        "machine_codes",
        "calculation_time",
        "silk_screen_clear_minutes",
        "remaining_production_hours",
        "prepare_clearance",
        "reason",
        "message",
    }
    assert "next_order_code" not in serialized
    assert "current_time" not in serialized


def test_external_models_forbid_unknown_internal_diagnostic_fields():
    with pytest.raises(ValidationError):
        response.StockoutSelectedMachineResponse(
            **stockout_selected_machine().model_dump(),
            idle_rate=-0.25,
        )
    with pytest.raises(ValidationError):
        response.ActiveCutlineEventResponse(
            **active_event().model_dump(),
            status="active",
        )


def test_stockout_warning_response_has_only_the_required_business_fields():
    warning = response.StockoutWarningResponse(
        warning_id="stockout:2026-07-17T08:00:00:310110302:ORD-S2-001",
        warning_type="stockout",
        warning_time=NOW,
        buffer_code="310110302",
        order_code="ORD-S2-001",
        wafer_size="182",
        wafer_spec="N",
        workshop_code="S2",
        upstream_process_code="制绒",
        downstream_process_code="碱抛",
        current_quantity=100.0,
        upstream_output_rate=200.0,
        downstream_input_rate=600.0,
        net_consumption_rate=400.0,
        depletion_minutes=15.0,
        stockout_warning_lead_minutes=30.0,
    )

    assert set(warning.model_dump()) == {
        "warning_id",
        "warning_type",
        "warning_time",
        "buffer_code",
        "order_code",
        "wafer_size",
        "wafer_spec",
        "workshop_code",
        "upstream_process_code",
        "downstream_process_code",
        "current_quantity",
        "upstream_output_rate",
        "downstream_input_rate",
        "net_consumption_rate",
        "depletion_minutes",
        "stockout_warning_lead_minutes",
    }


def test_overflow_warning_response_excludes_all_order_growth_details():
    values = {
        "warning_id": "overflow:2026-07-17T08:00:00:310110302",
        "warning_type": "overflow",
        "warning_time": NOW,
        "buffer_code": "310110302",
        "workshop_code": "S2",
        "total_inventory": 900.0,
        "max_capacity": 1000.0,
        "remaining_capacity": 100.0,
        "buffer_growth_rate": 300.0,
        "overflow_minutes": 20.0,
        "overflow_warning_lead_minutes": 30.0,
    }
    warning = response.OverflowWarningResponse(**values)

    assert set(warning.model_dump()) == set(values)
    with pytest.raises(ValidationError):
        response.OverflowWarningResponse(
            **values,
            order_growth_details=[{"order_code": "ORD-S2-001"}],
        )


def test_overflow_selected_machine_has_only_reduced_capacity_kind():
    machine = response.OverflowSelectedMachineResponse(
        machine_code="EA004",
        source_order_code="ORD-S2-002",
        target_order_code="ORD-S2-001",
        source_buffer_code="310110302",
        target_buffer_code="310110303",
        process_code="制绒",
        workshop_code="S2",
        wafer_size="182",
        source_wafer_spec="N",
        target_wafer_spec="N",
        reduced_capacity=600.0,
    )

    serialized = machine.model_dump()
    assert serialized["reduced_capacity"] == 600.0
    assert "contribution_capacity" not in serialized


def test_return_recommendation_contains_no_tracking_diagnostics():
    serialized = return_recommendation().model_dump(mode="json")

    assert set(serialized) == {
        "event_id",
        "machine_code",
        "source_order_code",
        "target_order_code",
        "return_recommended_time",
    }
    assert "negative_start_time" not in serialized
    assert "returned_time" not in serialized


def test_mixing_error_has_machine_context_without_internal_failure_object():
    error = response.MixingTraceErrorResponse(
        stage="mixing_trace",
        machine_code="EA004",
        reason="process_duration_not_found",
        message="process duration was not found",
    )

    assert error.model_dump() == {
        "stage": "mixing_trace",
        "machine_code": "EA004",
        "reason": "process_duration_not_found",
        "message": "process duration was not found",
    }
