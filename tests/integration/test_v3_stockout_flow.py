from tests.fixtures.v3_full_route_factory import (
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

    internal_plan = _internal_result(payload).cutline_decisions[0].plan
    assert internal_plan is not None
    assert internal_plan.risk_resolved is True

    assert response.new_active_cutline_events == []
    assert response.mixing_trace_records == []
    assert response.persistence_state.new_mixing_trace_records == []
    assert response.persistence_state.mixed_cutline_event_ids == []
    assert "mixing_trace_failures" not in response.__class__.model_fields
    assert response.errors == []


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


def test_v3_stockout_insufficient_candidate_reports_remaining_risk_only():
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
    assert manual.model_dump() == {"reason": "insufficient_capacity"}

    internal_manual = _internal_result(
        payload
    ).cutline_decisions[0].manual_intervention
    assert internal_manual is not None
    assert internal_manual.reason == "insufficient_contribution_capacity"
    assert internal_manual.initial_risk_value == 400
    assert internal_manual.remaining_risk_value == 200
    assert internal_manual.passed_candidate_count == 1
    assert [item.machine_code for item in internal_manual.passed_machines] == [
        "EA004"
    ]
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
