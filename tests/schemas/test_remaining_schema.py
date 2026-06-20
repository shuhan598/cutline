from datetime import datetime

from app.schemas.common_schema import CutlineEvent
from app.schemas.response_schema import CutlineEvaluateResponse
from app.schemas.result_schema import (
    CandidateMachine,
    ManualInterventionResult,
    OverflowWarningResult,
    PlanResult,
    ReturnResult,
)


def test_cutline_event_has_negative_start_time_default_none():
    event = CutlineEvent(
        equipment_code="zr03",
        cut_time=datetime(2026, 6, 20, 10, 0, 0),
        previous_product_code="HG182R",
        next_product_code="HG182T",
    )
    assert event.negative_start_time is None


def test_candidate_machine_has_idle_and_utilization_defaults():
    machine = CandidateMachine(
        equipment_code="zr03",
        process_code="ZR",
        target_product_code="HG182T",
        current_output_rate_per_hour=8000.0,
        reason="x",
    )
    assert machine.idle_rate is None
    assert machine.utilization_rate is None


def test_overflow_warning_result_fields():
    result = OverflowWarningResult(
        buffer_code="BUF",
        product_code="HG182T",
        process_from="ZR",
        process_to="PK",
        warning_type="overflow",
        warning_triggered=True,
        reason="overflow_time_within_lead_time",
        segment_inventory=18000.0,
        segment_capacity=20000.0,
        net_rate_per_hour=-4000.0,
        overflow_minutes=30.0,
        cutline_lead_minutes=30.0,
    )
    assert result.warning_type == "overflow"
    assert result.overflow_minutes == 30.0


def test_plan_result_holds_selected_machines():
    machine = CandidateMachine(
        equipment_code="zr03",
        process_code="ZR",
        target_product_code="HG182T",
        current_output_rate_per_hour=8000.0,
        contribution_capacity_per_hour=8000.0,
        reason="x",
    )
    plan = PlanResult(
        buffer_code="BUF",
        product_code="HG182T",
        process_from="ZR",
        process_to="PK",
        warning_type="stockout",
        selected_machines=[machine],
        total_contribution_capacity=8000.0,
        remaining_capacity_gap=-4800.0,
    )
    assert plan.selected_machines[0].equipment_code == "zr03"
    assert plan.requires_silk_screen_clear is False


def test_manual_intervention_result_required_capacity():
    result = ManualInterventionResult(
        buffer_code="BUF",
        product_code="HG182N",
        process_from="ZR",
        process_to="PK",
        warning_type="stockout",
        required_capacity=4000.0,
        reason="no_compatible_running_upstream_machine",
        candidates=[],
    )
    assert result.required_capacity == 4000.0


def test_return_result_triggered_flag():
    result = ReturnResult(
        equipment_code="zr03",
        product_code="HG182T",
        original_product_code="HG182R",
        buffer_code="BUF",
        process_from="ZR",
        process_to="PK",
        net_rate_per_hour=-4800.0,
        inventory_quantity=3200.0,
        negative_start_time=datetime(2026, 6, 20, 9, 35, 0),
        negative_duration_minutes=25.0,
        safety_inventory_quantity=2400.0,
        triggered=True,
    )
    assert result.triggered is True


def test_response_has_tracked_events_default_empty():
    response = CutlineEvaluateResponse()
    assert response.tracked_events == []
