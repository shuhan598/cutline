from datetime import datetime, timedelta

from app.mappers.algorithm_response_mapper import AlgorithmResponseMapper
from app.schemas import result_schema as result
from app.schemas.response_schema import (
    AutomaticCutlineDecisionResponse,
    CutlineAlgorithmResponse,
    CutlineEvaluateResponse,
    ManualCutlineDecisionResponse,
    MixingTraceErrorResponse,
)
from tests.core.cutline_confirmation.helpers import (
    CREATED_AT,
    MONITORED_ORDER,
    SOURCE_ORDER,
    make_active_event,
    make_stockout_plan,
)
from tests.schemas import test_algorithm_evaluate_result_schema as helpers


NOW = datetime(2026, 7, 17, 8, 0)


def selected_machine(*, capacity_kind: str = "stockout"):
    values = {
        "machine_code": "EA004",
        "source_order_code": "ORD-S2-002",
        "target_order_code": "ORD-S2-001",
        "source_buffer_code": "310110302",
        "target_buffer_code": "310110303",
        "process_code": "制绒",
        "workshop_code": "S2",
        "wafer_size": "182",
        "source_wafer_spec": "N",
        "target_wafer_spec": "N",
        "contribution_capacity": 600.0 if capacity_kind == "stockout" else None,
        "reduced_capacity": 600.0 if capacity_kind == "overflow" else None,
        "utilization_rate": 1.25,
        "idle_rate": -0.25,
        "source_net_rate_before": -400.0,
        "source_net_rate_after": 200.0,
        "source_depletion_minutes_after": 600.0,
        "target_net_rate_before": 400.0,
        "target_net_rate_after": -200.0,
        "target_overflow_minutes_after": None,
    }
    return result.AlgorithmSelectedMachineEvaluation(**values)


def stockout_warning():
    return result.AlgorithmStockoutWarningResult(
        warning_time=NOW,
        main_id="MAIN-310110302",
        buffer_code="310110302",
        buffer_codes=["310110302"],
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


def overflow_warning():
    return result.AlgorithmOverflowWarningResult(
        warning_time=NOW,
        main_id="MAIN-310110302",
        buffer_code="310110302",
        buffer_codes=["310110302"],
        workshop_code="S2",
        upstream_process_code="制绒",
        downstream_process_code="碱抛",
        max_capacity=1000.0,
        total_inventory=900.0,
        remaining_capacity=100.0,
        buffer_growth_rate=300.0,
        overflow_minutes=20.0,
        overflow_warning_lead_minutes=30.0,
        order_growth_details=[
            result.AlgorithmOrderGrowthDetail(
                order_code="ORD-S2-002",
                wafer_size="182",
                wafer_spec="N",
                current_quantity=750.0,
                upstream_output_rate=600.0,
                downstream_input_rate=200.0,
                net_consumption_rate=-400.0,
                growth_rate=400.0,
            )
        ],
    )


def automatic_decision():
    plan = result.AlgorithmStockoutCutlinePlan(
        plan_id="PLAN-STOCKOUT-1",
        calculation_time=NOW,
        workshop_code="S2",
        buffer_code="310110302",
        order_code="ORD-S2-001",
        wafer_size="182",
        wafer_spec="N",
        upstream_process_code="制绒",
        downstream_process_code="碱抛",
        initial_capacity_gap=400.0,
        total_contribution_capacity=600.0,
        remaining_capacity_gap=0.0,
        selected_machines=[selected_machine()],
    )
    return result.AlgorithmCutlineDecisionResult(
        plan=plan,
        manual_intervention=None,
    )


def automatic_overflow_decision():
    plan = result.AlgorithmOverflowCutlinePlan(
        plan_id="PLAN-OVERFLOW-1",
        calculation_time=NOW,
        workshop_code="S2",
        buffer_code="310110302",
        source_order_code="ORD-S2-002",
        source_wafer_size="182",
        source_wafer_spec="N",
        upstream_process_code="制绒",
        downstream_process_code="碱抛",
        initial_growth_rate=300.0,
        total_reduced_capacity=600.0,
        remaining_growth_rate=-300.0,
        updated_overflow_minutes=None,
        selected_machines=[selected_machine(capacity_kind="overflow")],
    )
    return result.AlgorithmCutlineDecisionResult(
        plan=plan,
        manual_intervention=None,
    )


def manual_decision(reason: str = "no_candidate_machine"):
    manual = result.AlgorithmManualInterventionResult(
        warning_type="stockout",
        warning_time=NOW,
        workshop_code="S2",
        buffer_code="310110302",
        order_code="ORD-S2-001",
        wafer_size="182",
        wafer_spec="N",
        upstream_process_code="制绒",
        downstream_process_code="碱抛",
        reason=reason,
        initial_risk_value=400.0,
        remaining_risk_value=400.0,
        evaluated_candidate_count=0,
        passed_candidate_count=0,
        rejected_candidate_count=0,
    )
    return result.AlgorithmCutlineDecisionResult(
        plan=None,
        manual_intervention=manual,
    )


def return_result(**updates):
    values = helpers.return_result().model_dump()
    values.update(
        {
            "event_id": "CUT-001",
            "machine_code": "EA004",
            "source_order_code": "ORD-S2-002",
            "target_order_code": "ORD-S2-001",
            "current_time": NOW,
            "cutline_start_time": NOW - timedelta(hours=1),
        }
    )
    values.update(updates)
    return result.AlgorithmReturnResult(**values)


def evaluate_result(**updates):
    values = {"calculation_time": NOW}
    values.update(updates)
    return result.AlgorithmEvaluateResult(**values)


def test_mapper_generates_stable_stockout_and_overflow_warning_ids():
    source = evaluate_result(
        stockout_warnings=[stockout_warning()],
        overflow_warnings=[overflow_warning()],
    )

    first = AlgorithmResponseMapper().to_response(source)
    second = AlgorithmResponseMapper().to_response(source)

    assert first.stockout_warnings[0].warning_id == (
        "stockout:2026-07-17T08:00:00:310110302:ORD-S2-001"
    )
    assert first.overflow_warnings[0].warning_id == (
        "overflow:2026-07-17T08:00:00:310110302"
    )
    assert first.model_dump() == second.model_dump()


def test_mapper_removes_overflow_order_growth_details_from_public_warning():
    source = evaluate_result(overflow_warnings=[overflow_warning()])

    response = AlgorithmResponseMapper().to_response(source)

    assert "order_growth_details" not in response.overflow_warnings[0].model_dump()
    assert source.overflow_warnings[0].order_growth_details


def test_mapper_projects_automatic_plan_and_machine_without_diagnostics():
    source = evaluate_result(
        stockout_warnings=[stockout_warning()],
        cutline_decisions=[automatic_decision()],
    )

    response = AlgorithmResponseMapper().to_response(source)

    decision = response.cutline_decisions[0]
    assert isinstance(decision, AutomaticCutlineDecisionResponse)
    assert decision.warning_id == response.stockout_warnings[0].warning_id
    serialized = decision.model_dump(mode="json")
    assert "manual_intervention" not in serialized
    assert "risk_resolved" not in serialized["plan"]
    machine = serialized["plan"]["selected_machines"][0]
    assert machine["contribution_capacity"] == 600.0
    assert "reduced_capacity" not in machine
    assert "idle_rate" not in machine
    assert "source_net_rate_before" not in machine


def test_mapper_projects_overflow_plan_with_only_reduced_capacity_kind():
    source = evaluate_result(
        overflow_warnings=[overflow_warning()],
        cutline_decisions=[automatic_overflow_decision()],
    )

    response = AlgorithmResponseMapper().to_response(source)

    decision = response.cutline_decisions[0]
    assert isinstance(decision, AutomaticCutlineDecisionResponse)
    assert decision.warning_id == response.overflow_warnings[0].warning_id
    serialized = decision.model_dump(mode="json")
    assert serialized["plan"]["warning_type"] == "overflow"
    machine = serialized["plan"]["selected_machines"][0]
    assert machine["reduced_capacity"] == 600.0
    assert "contribution_capacity" not in machine


def test_mapper_projects_manual_intervention_to_warning_id_and_reason_only():
    source = evaluate_result(
        stockout_warnings=[stockout_warning()],
        cutline_decisions=[manual_decision()],
    )

    response = AlgorithmResponseMapper().to_response(source)

    decision = response.cutline_decisions[0]
    assert isinstance(decision, ManualCutlineDecisionResponse)
    assert decision.warning_id == response.stockout_warnings[0].warning_id
    assert decision.model_dump(mode="json") == {
        "warning_id": response.stockout_warnings[0].warning_id,
        "manual_intervention": {"reason": "no_candidate_machine"},
    }


def test_mapper_normalizes_internal_insufficient_capacity_reason_codes():
    for internal_reason in (
        "insufficient_contribution_capacity",
        "insufficient_reduced_capacity",
    ):
        source = evaluate_result(
            cutline_decisions=[manual_decision(reason=internal_reason)]
        )

        response = AlgorithmResponseMapper().to_response(source)

        assert response.cutline_decisions[0].model_dump(mode="json")[
            "manual_intervention"
        ] == {"reason": "insufficient_capacity"}


def test_mapper_omits_unchanged_active_return_result_from_public_response():
    source = evaluate_result(
        return_results=[
            return_result(
                previous_negative_start_time=None,
                updated_negative_start_time=None,
                return_recommended=False,
                updated_status="active",
            )
        ]
    )

    response = AlgorithmResponseMapper().to_response(source)

    assert response.return_recommendations == []
    assert response.updated_active_cutline_events == []
    assert response.closed_active_cutline_event_ids == []


def test_mapper_first_negative_rate_creates_only_timer_update():
    source = evaluate_result(
        return_results=[
            return_result(
                previous_negative_start_time=None,
                updated_negative_start_time=NOW,
                net_consumption_rate=-400.0,
                condition_net_rate_met=True,
                condition_stability_met=False,
                return_recommended=False,
                updated_status="active",
                reason="stability_window_not_met",
            )
        ]
    )

    response = AlgorithmResponseMapper().to_response(source)

    assert response.updated_active_cutline_events[0].model_dump() == {
        "event_id": "CUT-001",
        "negative_start_time": NOW,
    }
    assert response.return_recommendations == []
    assert response.closed_active_cutline_event_ids == []


def test_mapper_carries_new_event_timer_without_redundant_update():
    new_event = helpers.active_cutline_event().model_copy(
        update={"negative_start_time": NOW},
        deep=True,
    )
    source = evaluate_result(
        new_active_cutline_events=[new_event],
        return_results=[
            return_result(
                event_id=new_event.event_id,
                previous_negative_start_time=None,
                updated_negative_start_time=NOW,
                net_consumption_rate=-400.0,
                condition_net_rate_met=True,
                condition_stability_met=False,
                return_recommended=False,
                updated_status="active",
                reason="stability_window_not_met",
            )
        ],
    )

    response = AlgorithmResponseMapper().to_response(source)

    assert response.new_active_cutline_events[0].event_id == new_event.event_id
    assert response.new_active_cutline_events[0].negative_start_time == NOW
    assert response.updated_active_cutline_events == []
    assert set(response.model_dump()) == set(CutlineAlgorithmResponse.model_fields)


def test_mapper_nonnegative_recovery_serializes_explicit_null_timer_update():
    source = evaluate_result(
        return_results=[
            return_result(
                previous_negative_start_time=NOW - timedelta(minutes=5),
                updated_negative_start_time=None,
                net_consumption_rate=0.0,
                return_recommended=False,
                updated_status="active",
                reason="net_rate_not_negative",
            )
        ]
    )

    response = AlgorithmResponseMapper().to_response(source)

    assert response.updated_active_cutline_events[0].model_dump(mode="json") == {
        "event_id": "CUT-001",
        "negative_start_time": None,
    }


def test_mapper_recommendation_closes_event_without_returning_event_update():
    source = evaluate_result(
        return_results=[
            return_result(
                previous_negative_start_time=NOW - timedelta(minutes=21),
                updated_negative_start_time=NOW - timedelta(minutes=21),
                net_consumption_rate=-400.0,
                condition_net_rate_met=True,
                condition_stability_met=True,
                condition_inventory_met=True,
                return_recommended=True,
                updated_status="return_recommended",
                reason="all_return_conditions_met",
            )
        ]
    )

    response = AlgorithmResponseMapper().to_response(source)

    assert response.return_recommendations[0].model_dump() == {
        "event_id": "CUT-001",
        "machine_code": "EA004",
        "source_order_code": "ORD-S2-002",
        "target_order_code": "ORD-S2-001",
        "return_recommended_time": NOW,
    }
    assert response.closed_active_cutline_event_ids == ["CUT-001"]
    assert response.updated_active_cutline_events == []


def test_mapper_projects_new_event_to_backend_persistence_fields_only():
    source = evaluate_result(new_active_cutline_events=[helpers.active_cutline_event()])

    response = AlgorithmResponseMapper().to_response(source)

    serialized = response.new_active_cutline_events[0].model_dump(mode="json")
    assert "plan_id" not in serialized
    assert "status" not in serialized
    assert "source_buffer_code" not in serialized
    assert serialized["negative_start_time"] is None


def test_mapper_projects_silk_result_to_customer_clearance_fields():
    source = evaluate_result(silk_screen_results=[helpers.silk_screen_result()])

    response = AlgorithmResponseMapper().to_response(source)

    serialized = response.silk_screen_results[0].model_dump()
    assert serialized["calculation_time"] == NOW
    assert serialized["workshop_code"] == "S1"
    assert "current_time" not in serialized
    assert "next_order_code" not in serialized
    assert "estimated_finish_time" not in serialized


def test_mapper_keeps_mixing_success_and_converts_each_failure_once_to_errors():
    pipeline_error = result.AlgorithmPipelineError(
        stage="return_evaluation",
        warning_key="CUT-002",
        reason="target_interval_not_found",
        message="missing interval",
    )
    source = evaluate_result(
        mixing_trace_records=[helpers.mixing_record()],
        mixing_trace_failures=[helpers.mixing_failure()],
        errors=[pipeline_error],
    )

    response = AlgorithmResponseMapper().to_response(source)

    assert len(response.mixing_trace_records) == 1
    assert len(response.errors) == 2
    assert response.errors[0].reason == "target_interval_not_found"
    assert response.errors[0].message == (
        "排产/定线-CUT-002：活跃事件找不到唯一的目标净速率区间"
    )
    assert isinstance(response.errors[1], MixingTraceErrorResponse)
    assert response.errors[1].machine_code == "M2"
    assert response.errors[1].reason == "machine_runtime_not_found"
    assert response.errors[1].message == "混料-M2：机台实时记录缺失"
    assert "mixing_trace_failures" not in response.model_fields


def test_mapper_does_not_modify_internal_source_and_preserves_list_order():
    first_warning = stockout_warning().model_copy(
        update={"buffer_code": "BUF-2", "order_code": "ORD-B"}
    )
    second_warning = stockout_warning()
    source = evaluate_result(stockout_warnings=[first_warning, second_warning])
    before = source.model_dump()

    response = AlgorithmResponseMapper().to_response(source)

    assert isinstance(response, CutlineAlgorithmResponse)
    assert [item.buffer_code for item in response.stockout_warnings] == [
        "BUF-2",
        "310110302",
    ]
    assert source.model_dump() == before


def test_evaluate_mapper_adds_full_persistence_state_without_changing_base_fields():
    plan = make_stockout_plan()
    active = make_active_event(
        plan_id=plan.plan_id,
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=CREATED_AT,
    ).model_copy(update={"warning_id": plan.warning_id})
    source = evaluate_result(
        stockout_warnings=[stockout_warning()],
        persistence_state=result.AlgorithmPersistenceState(
            pending_cutline_plans=[plan],
            active_cutline_events=[active],
            completed_pending_plan_ids=[plan.plan_id],
            return_suggested_event_ids=[active.event_id],
            mixed_cutline_event_ids=["CUT-MIXED-OLDER"],
            new_mixing_trace_records=[helpers.mixing_record()],
        ),
    )
    mapper = AlgorithmResponseMapper()

    base = mapper.to_response(source)
    enhanced = mapper.to_evaluate_response(source)

    assert isinstance(base, CutlineAlgorithmResponse)
    assert not isinstance(base, CutlineEvaluateResponse)
    assert isinstance(enhanced, CutlineEvaluateResponse)
    assert enhanced.model_dump(exclude={"persistence_state"}) == base.model_dump()
    state = enhanced.persistence_state
    assert state.pending_cutline_plans == [plan]
    assert state.completed_pending_plan_ids == [plan.plan_id]
    assert state.return_suggested_event_ids == [active.event_id]
    assert state.mixed_cutline_event_ids == ["CUT-MIXED-OLDER"]
    assert len(state.new_mixing_trace_records) == 1
    persisted = state.active_cutline_events[0]
    assert persisted.event_id == active.event_id
    assert persisted.plan_id == plan.plan_id
    assert persisted.warning_id == plan.warning_id
    assert persisted.status == active.status
    assert persisted.source_buffer_code == active.source_buffer_code
    assert persisted.is_recommended_candidate is True
