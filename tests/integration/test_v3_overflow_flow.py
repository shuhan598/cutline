from app.service.cutline_pipeline import CutlinePipeline
from tests.fixtures.v3_full_route_factory import (
    SUPPORT_BUFFER_CODE,
    SUPPORT_ORDER_CODE,
    TARGET_BUFFER_CODE,
    _set_runtime,
    build_overflow_manual_payload,
    build_overflow_warning_payload,
)
from tests.integration.helpers import evaluate, response_buffer_codes, snapshot


def _internal_result(payload):
    return CutlinePipeline().evaluate_algorithm(snapshot(payload))


def _group_overflow_payload():
    payload = build_overflow_manual_payload()
    source_inventory = next(
        item
        for item in payload["buffer_realtime"]
        if item["buffer_code"] == SUPPORT_BUFFER_CODE
    )
    source_inventory["current_quantity"] = 850.0
    source_inventory["current_utilization_rate"] = 0.85
    target_inventory = next(
        item
        for item in payload["buffer_realtime"]
        if item["buffer_code"] == TARGET_BUFFER_CODE
    )
    target_inventory["current_quantity"] = 200.0
    target_inventory["current_utilization_rate"] = 0.2
    return payload


def test_v3_overflow_risk_does_not_aggregate_across_group_keys():
    payload = build_overflow_warning_payload()
    response = evaluate(payload)
    internal = _internal_result(payload)

    assert response.overflow_warnings == []
    assert internal.overflow_warnings == []
    physical_rates = {
        item.buffer_code: item.inventory_change_rate
        for item in internal.net_rate_results
        if item.buffer_code in {TARGET_BUFFER_CODE, SUPPORT_BUFFER_CODE}
    }
    assert physical_rates == {
        TARGET_BUFFER_CODE: 100,
        SUPPORT_BUFFER_CODE: 200,
    }


def test_v3_overflow_group_selects_distinct_target_and_creates_plan():
    payload = _group_overflow_payload()
    response = evaluate(payload)

    warning = response.overflow_warnings[0]
    assert warning.buffer_code == SUPPORT_BUFFER_CODE
    assert warning.total_inventory == 850
    assert warning.remaining_capacity == 150
    assert warning.buffer_growth_rate == 400
    assert warning.overflow_minutes == 22.5
    decision = response.cutline_decisions[0]
    assert "manual_intervention" not in decision.model_dump()
    plan = decision.plan
    assert plan is not None
    assert plan.source_order_code == SUPPORT_ORDER_CODE
    assert [item.machine_code for item in plan.selected_machines] == ["EA004"]
    selected = plan.selected_machines[0]
    assert selected.source_buffer_code == SUPPORT_BUFFER_CODE
    assert selected.target_buffer_code == TARGET_BUFFER_CODE
    assert response.new_active_cutline_events == []
    assert response.mixing_trace_records == []
    assert response.errors == []


def test_v3_overflow_internal_selection_keeps_distinct_group_keys():
    result = _internal_result(_group_overflow_payload())

    plan = result.cutline_decisions[0].plan
    assert plan is not None
    selected = plan.selected_machines[0]
    assert selected.source_group_key is not None
    assert selected.target_group_key is not None
    assert selected.source_group_key != selected.target_group_key
    assert selected.source_buffer_code == SUPPORT_BUFFER_CODE
    assert selected.target_buffer_code == TARGET_BUFFER_CODE


def test_v3_overflow_response_preserves_input_numeric_buffer_codes():
    payload = _group_overflow_payload()
    input_codes = {item["buffer_code"] for item in payload["buffer_master"]}

    output_codes = response_buffer_codes(evaluate(payload))

    assert output_codes
    assert all(code in input_codes and code.isdigit() for code in output_codes)


def test_v3_overflow_partial_improvement_stays_manual_without_pending():
    payload = build_overflow_manual_payload()
    _set_runtime(
        payload,
        "EA003",
        status="\u8fd0\u884c",
        order_code=SUPPORT_ORDER_CODE,
        input_quantity=300,
        output_quantity=300,
    )
    source_inventory = next(
        item
        for item in payload["buffer_realtime"]
        if item["buffer_code"] == SUPPORT_BUFFER_CODE
    )
    source_inventory["current_quantity"] = 950.0
    source_inventory["current_utilization_rate"] = 0.95
    target_inventory = next(
        item
        for item in payload["buffer_realtime"]
        if item["buffer_code"] == TARGET_BUFFER_CODE
    )
    target_inventory["current_quantity"] = 700.0
    target_inventory["current_utilization_rate"] = 0.7

    result = _internal_result(payload)

    assert len(result.overflow_warnings) == 1
    decision = result.cutline_decisions[0]
    assert decision.plan is None
    assert decision.manual_intervention is not None
    assert decision.manual_intervention.reason == "insufficient_reduced_capacity"
    assert decision.manual_intervention.passed_candidate_count == 1
    assert result.persistence_state.pending_cutline_plans == []
