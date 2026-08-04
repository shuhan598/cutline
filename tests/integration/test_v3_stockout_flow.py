from dataclasses import replace

from app.core.buffer_aggregation.models import MainBufferAggregationIssue
from tests.fixtures.v3_full_route_factory import (
    SUPPORT_BUFFER_CODE,
    TARGET_BUFFER_CODE,
    build_stockout_auto_payload,
    build_stockout_manual_payload,
)
from tests.integration.helpers import (
    evaluate,
    response_buffer_codes,
    runtime,
    snapshot,
)
from app.service.cutline_pipeline import CutlinePipeline


def _internal_result(payload):
    return CutlinePipeline().evaluate_algorithm(snapshot(payload))


def test_v3_stockout_auto_generates_pending_plan_without_future_mixing():
    payload = build_stockout_auto_payload()

    response = evaluate(payload)

    assert len(response.stockout_warnings) == 1
    warning = response.stockout_warnings[0]
    assert warning.buffer_code == TARGET_BUFFER_CODE
    assert warning.order_code == "ORD-S2-001"
    assert warning.net_consumption_rate == 400
    assert warning.depletion_minutes == 15
    assert response.overflow_warnings == []

    decision = response.cutline_decisions[0]
    assert "manual_intervention" not in decision.model_dump()
    plan = decision.plan
    assert plan is not None
    assert plan.buffer_code == TARGET_BUFFER_CODE
    assert plan.initial_capacity_gap == 400
    assert plan.total_contribution_capacity == 600
    assert plan.remaining_capacity_gap == 0
    assert "risk_resolved" not in plan.model_dump()
    assert [item.machine_code for item in plan.selected_machines] == ["EA004"]
    selected = plan.selected_machines[0]
    assert selected.source_buffer_code == SUPPORT_BUFFER_CODE
    assert selected.target_buffer_code == TARGET_BUFFER_CODE

    internal_plan = _internal_result(payload).cutline_decisions[0].plan
    assert internal_plan is not None
    assert internal_plan.risk_resolved is True
    internal_selected = internal_plan.selected_machines[0]
    assert internal_selected.donor_group_key is not None
    assert internal_selected.receiver_group_key is not None
    assert internal_selected.donor_group_key != internal_selected.receiver_group_key

    assert response.new_active_cutline_events == []
    assert response.mixing_trace_records == []
    assert response.persistence_state.new_mixing_trace_records == []
    assert response.persistence_state.mixed_cutline_event_ids == []
    assert "mixing_trace_failures" not in response.__class__.model_fields
    assert response.errors == []


def test_capacity_unavailable_receiver_warns_but_forces_manual_without_pending():
    snapshot_value = snapshot(build_stockout_auto_payload())
    batch = snapshot_value.main_buffer_batch
    receiver_key = batch.group_key_by_buffer_code[TARGET_BUFFER_CODE]
    receiver = batch.groups_by_group_key[receiver_key]
    unavailable = replace(
        receiver,
        total_capacity=None,
        remaining_capacity=None,
        overflow_eligible=False,
        overflow_warning_eligible=False,
        auto_receive_eligible=False,
    )
    groups_by_key = dict(batch.groups_by_group_key)
    groups_by_key[receiver_key] = unavailable
    snapshot_value.main_buffer_batch = replace(
        batch,
        groups=tuple(
            unavailable if group.group_key == receiver_key else group
            for group in batch.groups
        ),
        groups_by_group_key=groups_by_key,
        issues=batch.issues
        + (
            MainBufferAggregationIssue(
                code="capacity_unavailable",
                main_id=receiver.main_id,
                representative_buffer_code=receiver.representative_buffer_code,
                message="Capacity unavailable for target receiver",
                affected_capabilities=(
                    "overflow_eligible",
                    "overflow_warning_eligible",
                    "auto_receive_eligible",
                ),
            ),
        ),
    )

    result = CutlinePipeline().evaluate_algorithm(snapshot_value)

    assert len(result.stockout_warnings) == 1
    assert result.cutline_decisions[0].plan is None
    manual = result.cutline_decisions[0].manual_intervention
    assert manual is not None
    assert manual.reason == "target_capacity_unavailable"
    assert manual.evaluated_candidate_count > 0
    assert manual.passed_candidate_count == 0
    assert manual.rejected_candidate_count == manual.evaluated_candidate_count
    assert {
        rejected.reason for rejected in manual.rejected_machines
    } == {"target_capacity_unavailable"}
    assert result.persistence_state.pending_cutline_plans == []
    assert any(error.reason == "capacity_unavailable" for error in result.errors)


def test_v3_stockout_without_running_candidate_requires_manual_intervention():
    response = evaluate(build_stockout_manual_payload())

    assert len(response.stockout_warnings) == 1
    decision = response.cutline_decisions[0]
    assert "plan" not in decision.model_dump()
    manual = decision.manual_intervention
    assert manual is not None
    assert manual.reason == "no_candidate_machine"
    assert manual.model_dump() == {"reason": "no_candidate_machine"}

    internal_manual = _internal_result(
        build_stockout_manual_payload()
    ).cutline_decisions[0].manual_intervention
    assert internal_manual is not None
    assert internal_manual.buffer_code == TARGET_BUFFER_CODE
    assert internal_manual.evaluated_candidate_count == 0
    assert response.new_active_cutline_events == []
    assert response.mixing_trace_records == []
    assert response.errors == []


def test_v3_stockout_candidate_at_exact_depletion_lead_boundary_requires_manual():
    payload = build_stockout_auto_payload()
    candidate = runtime(payload, "EA004")
    candidate["input_quantity"] = 100.0
    candidate["output_quantity"] = 100.0

    response = evaluate(payload)

    decision = response.cutline_decisions[0]
    assert "plan" not in decision.model_dump()
    manual = decision.manual_intervention
    assert manual is not None
    assert manual.reason == "insufficient_capacity"

    internal_manual = _internal_result(
        payload
    ).cutline_decisions[0].manual_intervention
    assert internal_manual is not None
    assert internal_manual.risk_resolved is False
    assert internal_manual.remaining_risk_value == 200
    assert [item.machine_code for item in internal_manual.passed_machines] == [
        "EA004"
    ]
    assert _internal_result(payload).persistence_state.pending_cutline_plans == []
    assert response.new_active_cutline_events == []
    assert response.mixing_trace_records == []


def test_v3_stockout_response_preserves_input_numeric_buffer_codes():
    payload = build_stockout_auto_payload()
    input_codes = {item["buffer_code"] for item in payload["buffer_master"]}

    output_codes = response_buffer_codes(evaluate(payload))

    assert output_codes
    assert all(code in input_codes and code.isdigit() for code in output_codes)
    assert TARGET_BUFFER_CODE in output_codes
    assert "BUF-ZR-PK" not in output_codes
