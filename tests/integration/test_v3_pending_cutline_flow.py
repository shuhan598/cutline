from __future__ import annotations

from copy import deepcopy
from datetime import datetime

import pytest

from app.schemas.response_schema import AutomaticCutlineDecisionResponse
from app.service.cutline_pipeline import CutlinePipeline
from tests.fixtures.v3_full_route_factory import (
    SUPPORT_ORDER_CODE,
    TARGET_BUFFER_CODE,
    TARGET_ORDER_CODE,
    build_return_recommended_payload,
    build_return_round_1_payload,
    build_return_round_2_payload,
)
from tests.integration.helpers import evaluate, snapshot


def _internal_result(payload: dict):
    return CutlinePipeline().evaluate_algorithm(snapshot(payload))


def _product_for_order(payload: dict, order_code: str) -> dict:
    order = next(
        item for item in payload["orders"] if item["order_code"] == order_code
    )
    return next(
        item
        for item in payload["products"]
        if item["product_code"] == order["product_code"]
    )


def _machine(payload: dict, machine_code: str) -> dict:
    return next(
        item
        for item in payload["machine_master"]
        if item["machine_code"] == machine_code
    )


def _append_binding(
    payload: dict,
    *,
    machine_code: str,
    order_code: str,
    binding_time: str,
    previous_order_code: str,
    wafer_spec: str = "N",
) -> None:
    product = _product_for_order(payload, order_code)
    previous_product = _product_for_order(payload, previous_order_code)
    payload["agv_relations"].append(
        {
            "equipmentid": machine_code,
            "equipmentname": _machine(payload, machine_code)["machine_name"],
            "linename": product["product_name"],
            "lastlinename": previous_product["product_name"],
            "waferspec": wafer_spec,
            "createtime": binding_time,
        }
    )


def _remove_post_warning_binding(payload: dict, machine_code: str) -> None:
    payload["agv_relations"] = [
        item
        for item in payload["agv_relations"]
        if not (
            item["equipmentid"] == machine_code
            and item["createtime"] > "2026-07-17 08:00:00"
        )
    ]


def _set_scope_machine_baseline_to_support(
    payload: dict,
    machine_code: str,
) -> None:
    plan = payload["pending_cutline_plans"][0]
    support = _product_for_order(payload, SUPPORT_ORDER_CODE)
    baseline = next(
        item
        for item in plan["baseline_machine_bindings"]
        if item["machine_code"] == machine_code
    )
    baseline.update(
        {
            "order_code": SUPPORT_ORDER_CODE,
            "product_code": support["product_code"],
            "product_name": support["product_name"],
            "wafer_size": support["wafer_size"],
            "wafer_spec": "N",
            "source_grade": support["source_grade"],
        }
    )
    old_relation = next(
        item
        for item in payload["agv_relations"]
        if item["equipmentid"] == machine_code
        and item["createtime"] <= "2026-07-17 08:00:00"
    )
    old_relation.update(
        {
            "linename": support["product_name"],
            "lastlinename": None,
            "waferspec": "N",
        }
    )


def _add_recommended_candidate(payload: dict, machine_code: str) -> None:
    plan = payload["pending_cutline_plans"][0]
    baseline = next(
        item
        for item in plan["baseline_machine_bindings"]
        if item["machine_code"] == machine_code
    )
    candidate = deepcopy(plan["candidate_machines"][0])
    candidate.update(
        {
            "machine_code": machine_code,
            "baseline_order_code": baseline["order_code"],
            "baseline_product_code": baseline["product_code"],
            "baseline_product_name": baseline["product_name"],
            "baseline_wafer_size": baseline["wafer_size"],
            "baseline_wafer_spec": baseline["wafer_spec"],
            "baseline_source_grade": baseline["source_grade"],
        }
    )
    plan["candidate_machines"].append(candidate)
    plan["expected_machine_count"] += 1


def test_first_round_plan_is_pending_without_future_mixing_record():
    response = evaluate(build_return_round_1_payload())

    decision = response.cutline_decisions[0]
    assert isinstance(decision, AutomaticCutlineDecisionResponse)
    assert response.new_active_cutline_events == []
    assert response.return_recommendations == []
    assert response.updated_active_cutline_events == []
    assert response.closed_active_cutline_event_ids == []
    assert response.mixing_trace_records == []


def test_real_pending_roundtrip_confirms_active_event_and_mixes_once():
    round_one_payload = build_return_round_1_payload()
    round_one = evaluate(round_one_payload)

    assert len(round_one.persistence_state.pending_cutline_plans) == 1
    pending = round_one.persistence_state.pending_cutline_plans[0]
    assert pending.status.value == "PENDING"
    assert len(pending.candidate_machines) == 1
    assert round_one.mixing_trace_records == []
    assert round_one.persistence_state.new_mixing_trace_records == []
    assert round_one.persistence_state.mixed_cutline_event_ids == []
    candidate = pending.candidate_machines[0]

    round_two_payload = deepcopy(round_one_payload)
    round_two_payload["snapshot_meta"]["snapshot_time"] = (
        "2026-07-17T08:05:00+08:00"
    )
    round_two_payload["pending_cutline_plans"] = [
        item.model_dump(mode="json")
        for item in round_one.persistence_state.pending_cutline_plans
    ]
    _append_binding(
        round_two_payload,
        machine_code=candidate.machine_code,
        order_code=candidate.expected_target_order_code,
        previous_order_code=candidate.baseline_order_code,
        binding_time="2026-07-17 08:03:00",
        wafer_spec=candidate.expected_target_wafer_spec,
    )

    round_two = evaluate(round_two_payload)

    persisted_pending = next(
        item
        for item in round_two.persistence_state.pending_cutline_plans
        if item.plan_id == pending.plan_id
    )
    assert persisted_pending.status.value == "CONFIRMED"
    assert persisted_pending.confirmed_machine_codes == [
        candidate.machine_code
    ]
    assert round_two.persistence_state.completed_pending_plan_ids == [
        pending.plan_id
    ]

    assert len(round_two.new_active_cutline_events) == 1
    new_event = round_two.new_active_cutline_events[0]
    assert new_event.event_id == (
        f"CUT-{pending.plan_id}-{candidate.machine_code}"
    )
    assert new_event.machine_code == candidate.machine_code
    assert new_event.source_order_code == candidate.baseline_order_code
    assert new_event.target_order_code == (
        candidate.expected_target_order_code
    )

    assert len(round_two.persistence_state.active_cutline_events) == 1
    persisted_event = round_two.persistence_state.active_cutline_events[0]
    assert persisted_event.event_id == new_event.event_id
    assert persisted_event.plan_id == pending.plan_id
    assert persisted_event.warning_id == pending.warning_id
    assert persisted_event.machine_code == candidate.machine_code
    assert persisted_event.target_order_code == (
        candidate.expected_target_order_code
    )
    assert persisted_event.is_recommended_candidate is True

    assert len(round_two.mixing_trace_records) == 1
    mixing_record = round_two.mixing_trace_records[0]
    assert mixing_record.plan_id == pending.plan_id
    assert mixing_record.cutline_event_id == new_event.event_id
    assert round_two.persistence_state.new_mixing_trace_records == [
        mixing_record
    ]
    assert round_two.persistence_state.mixed_cutline_event_ids == [
        new_event.event_id
    ]


def test_naive_snapshot_time_is_normalized_before_pending_creation():
    payload = build_return_round_1_payload()
    payload["snapshot_meta"]["snapshot_time"] = "2026-07-17 08:00:00"

    response = evaluate(payload)

    assert len(response.cutline_decisions) == 1
    assert len(response.persistence_state.pending_cutline_plans) == 1
    pending = response.persistence_state.pending_cutline_plans[0]
    assert pending.created_at.utcoffset() is not None
    assert pending.created_at.utcoffset().total_seconds() == 8 * 60 * 60
    assert response.errors == []


def test_round_two_fixture_confirms_recommended_machine_from_real_agv_time():
    payload = build_return_round_2_payload()

    assert payload["active_cutline_events"] == []
    assert len(payload["pending_cutline_plans"]) == 1
    pending = payload["pending_cutline_plans"][0]
    assert pending["status"] == "PENDING"
    assert pending["expire_at"] == "2026-07-17T08:30:00+08:00"
    assert {
        item["machine_code"] for item in pending["baseline_machine_bindings"]
    } == {"EA003", "EA004", "EA023", "EA024"}
    assert [
        item["createtime"]
        for item in payload["agv_relations"]
        if item["equipmentid"] == "EA004"
    ] == ["2026-07-17 07:55:00", "2026-07-17 08:03:00"]

    internal = _internal_result(payload)
    response = evaluate(payload)

    assert len(internal.new_active_cutline_events) == 1
    internal_event = internal.new_active_cutline_events[0]
    assert internal_event.plan_id == pending["plan_id"]
    assert internal_event.is_recommended_candidate is True
    assert [item.event_id for item in internal.return_results] == [
        internal_event.event_id
    ]
    assert len(response.new_active_cutline_events) == 1
    event = response.new_active_cutline_events[0]
    assert event.event_id == f"CUT-{pending['plan_id']}-EA004"
    assert event.machine_code == "EA004"
    assert event.source_order_code == SUPPORT_ORDER_CODE
    assert event.target_order_code == TARGET_ORDER_CODE
    assert event.cutline_start_time == datetime.fromisoformat(
        "2026-07-17T08:03:00+08:00"
    )
    assert event.negative_start_time == datetime.fromisoformat(
        "2026-07-17T08:05:00+08:00"
    )
    assert response.updated_active_cutline_events == []


def test_customer_noncandidate_machine_can_confirm_remaining_stockout_slot():
    payload = build_return_round_2_payload()
    _remove_post_warning_binding(payload, "EA004")
    _set_scope_machine_baseline_to_support(payload, "EA023")
    _append_binding(
        payload,
        machine_code="EA023",
        order_code=TARGET_ORDER_CODE,
        previous_order_code=SUPPORT_ORDER_CODE,
        binding_time="2026-07-17 08:04:00",
    )

    result = _internal_result(payload)

    assert len(result.new_active_cutline_events) == 1
    event = result.new_active_cutline_events[0]
    assert event.machine_code == "EA023"
    assert event.source_order_code == SUPPORT_ORDER_CODE
    assert event.target_order_code == TARGET_ORDER_CODE
    assert event.is_recommended_candidate is False
    assert event.cutline_start_time == datetime.fromisoformat(
        "2026-07-17T08:04:00+08:00"
    )


def test_partial_confirmation_is_persisted_then_second_machine_confirms_once():
    first_payload = build_return_round_2_payload()
    _set_scope_machine_baseline_to_support(first_payload, "EA023")
    _add_recommended_candidate(first_payload, "EA023")

    first = evaluate(first_payload)

    assert [item.machine_code for item in first.new_active_cutline_events] == [
        "EA004"
    ]

    second_payload = deepcopy(first_payload)
    second_payload["snapshot_meta"]["snapshot_time"] = (
        "2026-07-17T08:07:00+08:00"
    )
    pending = second_payload["pending_cutline_plans"][0]
    pending["status"] = "PARTIALLY_CONFIRMED"
    pending["confirmed_machine_codes"] = ["EA004"]
    second_payload["active_cutline_events"] = [
        first.new_active_cutline_events[0].model_dump(mode="json")
    ]
    _append_binding(
        second_payload,
        machine_code="EA023",
        order_code=TARGET_ORDER_CODE,
        previous_order_code=SUPPORT_ORDER_CODE,
        binding_time="2026-07-17 08:06:00",
    )

    second = evaluate(second_payload)

    assert [item.machine_code for item in second.new_active_cutline_events] == [
        "EA023"
    ]
    assert second.new_active_cutline_events[0].event_id == (
        f"CUT-{pending['plan_id']}-EA023"
    )


@pytest.mark.parametrize(
    ("transition_time", "snapshot_time", "expected_count"),
    [
        (None, "2026-07-17T08:00:00+08:00", 0),
        ("2026-07-17 08:30:00", "2026-07-17T08:30:00+08:00", 1),
    ],
)
def test_confirmation_window_excludes_creation_and_includes_expiry(
    transition_time: str | None,
    snapshot_time: str,
    expected_count: int,
):
    payload = build_return_round_2_payload()
    _remove_post_warning_binding(payload, "EA004")
    payload["snapshot_meta"]["snapshot_time"] = snapshot_time
    if transition_time is None:
        baseline = next(
            item
            for item in payload["pending_cutline_plans"][0][
                "baseline_machine_bindings"
            ]
            if item["machine_code"] == "EA004"
        )
        baseline["agv_record_time"] = "2026-07-17T08:00:00+08:00"
        relation = next(
            item
            for item in payload["agv_relations"]
            if item["equipmentid"] == "EA004"
        )
        relation["createtime"] = "2026-07-17 08:00:00"
    else:
        _append_binding(
            payload,
            machine_code="EA004",
            order_code=TARGET_ORDER_CODE,
            previous_order_code=SUPPORT_ORDER_CODE,
            binding_time=transition_time,
        )

    response = evaluate(payload)

    assert len(response.new_active_cutline_events) == expected_count
    if expected_count:
        assert response.new_active_cutline_events[0].cutline_start_time == (
            datetime.fromisoformat("2026-07-17T08:30:00+08:00")
        )


def test_unchanged_pending_plan_expires_without_creating_real_event():
    payload = build_return_round_2_payload()
    _remove_post_warning_binding(payload, "EA004")
    payload["snapshot_meta"]["snapshot_time"] = (
        "2026-07-17T08:31:00+08:00"
    )

    response = evaluate(payload)

    assert response.new_active_cutline_events == []
    assert response.return_recommendations == []


def test_overflow_confirmation_reduces_monitored_machine_count_and_routes_out():
    payload = build_return_round_2_payload()
    _remove_post_warning_binding(payload, "EA004")
    plan = payload["pending_cutline_plans"][0]
    monitored = _product_for_order(payload, TARGET_ORDER_CODE)
    support = _product_for_order(payload, SUPPORT_ORDER_CODE)
    warning_buffer = next(
        item
        for item in payload["buffer_master"]
        if item["buffer_code"] == TARGET_BUFFER_CODE
    )
    alternate_buffer = deepcopy(warning_buffer)
    alternate_buffer["buffer_code"] = "310112803"
    alternate_buffer["buffer_name"] = "制绒-碱抛备用Buffer"
    payload["buffer_master"].append(alternate_buffer)
    payload["buffer_realtime"].append(
        {
            "main_id": "MAIN-310112803",
            "buffer_code": "310112803",
            "bound_source_name": support["product_name"],
            "current_quantity": 1000.0,
            "current_utilization_rate": 0.01,
        }
    )
    baseline = next(
        item
        for item in plan["baseline_machine_bindings"]
        if item["machine_code"] == "EA003"
    )
    candidate = deepcopy(plan["candidate_machines"][0])
    candidate.update(
        {
            "machine_code": "EA003",
            "baseline_order_code": TARGET_ORDER_CODE,
            "baseline_product_code": monitored["product_code"],
            "baseline_product_name": monitored["product_name"],
            "baseline_wafer_size": monitored["wafer_size"],
            "baseline_wafer_spec": baseline["wafer_spec"],
            "baseline_source_grade": monitored["source_grade"],
            "expected_target_order_code": SUPPORT_ORDER_CODE,
            "expected_target_product_code": support["product_code"],
            "expected_target_product_name": support["product_name"],
            "expected_target_wafer_size": support["wafer_size"],
            "expected_target_wafer_spec": "N",
            "expected_target_source_grade": support["source_grade"],
            "source_buffer_code": TARGET_BUFFER_CODE,
            "target_buffer_code": "310112803",
        }
    )
    plan.update(
        {
            "warning_type": "overflow",
            "before_machine_count": 1,
            "before_machine_codes": ["EA003"],
            "expected_machine_count": 0,
            "expected_delta_direction": "decrease",
            "candidate_machines": [candidate],
        }
    )
    _append_binding(
        payload,
        machine_code="EA003",
        order_code=SUPPORT_ORDER_CODE,
        previous_order_code=TARGET_ORDER_CODE,
        binding_time="2026-07-17 08:03:00",
    )

    result = _internal_result(payload)

    assert len(result.new_active_cutline_events) == 1
    event = result.new_active_cutline_events[0]
    assert event.warning_type == "overflow"
    assert event.machine_code == "EA003"
    assert event.source_order_code == TARGET_ORDER_CODE
    assert event.target_order_code == SUPPORT_ORDER_CODE
    assert event.source_buffer_code == TARGET_BUFFER_CODE
    assert event.target_buffer_code == "310112803"
    assert event.cutline_start_time == datetime.fromisoformat(
        "2026-07-17T08:03:00+08:00"
    )


def test_return_followup_uses_persisted_active_event_without_live_pending_plan():
    payload = build_return_recommended_payload()

    assert payload["pending_cutline_plans"] == []
    assert len(payload["active_cutline_events"]) == 1
    assert payload["active_cutline_events"][0]["cutline_start_time"] == (
        "2026-07-17T08:03:00+08:00"
    )

    response = evaluate(payload)

    event_id = payload["active_cutline_events"][0]["event_id"]
    assert [item.event_id for item in response.return_recommendations] == [
        event_id
    ]
    assert response.closed_active_cutline_event_ids == [event_id]
    assert response.updated_active_cutline_events == []


def test_naive_followup_time_compares_with_persisted_active_event() -> None:
    payload = build_return_recommended_payload()
    payload["snapshot_meta"]["snapshot_time"] = "2026-07-17 08:26:00"

    response = evaluate(payload)

    event_id = payload["active_cutline_events"][0]["event_id"]
    assert [item.event_id for item in response.return_recommendations] == [
        event_id
    ]
    assert response.persistence_state.return_suggested_event_ids == [event_id]
