from __future__ import annotations

from copy import deepcopy

import pytest

from app.adapters.backend_request_loader import BackendRequestLoader
from app.adapters.backend_request_validator import (
    BackendRequestCompletenessValidator,
)
from app.adapters.snapshot_adapter import SnapshotAdapter, SnapshotConversionError
from tests.fixtures.v3_full_route_factory import build_base_request_payload


def _product_by_order(payload: dict, order_code: str) -> dict:
    order = next(
        item for item in payload["orders"] if item["order_code"] == order_code
    )
    product = next(
        item
        for item in payload["products"]
        if item["product_code"] == order["product_code"]
    )
    return {**product, "order_code": order_code}


def _machine(payload: dict, machine_code: str) -> dict:
    return next(
        item
        for item in payload["machine_master"]
        if item["machine_code"] == machine_code
    )


def _agv_record(
    payload: dict,
    machine_code: str,
    order_code: str,
    binding_time: str,
    *,
    previous_product_name: str | None = None,
) -> dict:
    machine = _machine(payload, machine_code)
    product = _product_by_order(payload, order_code)
    return {
        "equipmentid": machine_code,
        "equipmentname": machine["machine_name"],
        "linename": product["product_name"],
        "lastlinename": previous_product_name,
        "waferspec": "N",
        "createtime": binding_time,
    }


def _baseline(
    payload: dict,
    machine_code: str,
    order_code: str,
) -> dict:
    machine = _machine(payload, machine_code)
    product = _product_by_order(payload, order_code)
    agv_record = next(
        (
            item
            for item in payload["agv_relations"]
            if item["equipmentid"] == machine_code
        ),
        None,
    )
    wafer_spec = (
        agv_record["waferspec"]
        if agv_record is not None
        else next(
            item["wafer_spec"]
            for item in payload["machine_lines"]
            if item["machine_code"] == machine_code
        )
    )
    return {
        "machine_code": machine_code,
        "order_code": order_code,
        "product_code": product["product_code"],
        "product_name": product["product_name"],
        "wafer_size": product["wafer_size"],
        "wafer_spec": wafer_spec,
        "source_grade": product["source_grade"],
        "process_code": machine["process_code"],
        "workshop_code": "S2",
        "machine_status": "running",
        "observed_at": "2026-07-17T07:55:00+08:00",
    }


def _stockout_plan(payload: dict, *, plan_id: str = "PLAN-PENDING-1") -> dict:
    monitored = _product_by_order(payload, "ORD-S2-001")
    support = _product_by_order(payload, "ORD-S2-002")
    warning_buffer = payload["buffer_master"][1]
    upstream, downstream = warning_buffer["served_process_codes"]
    candidate_machine = _machine(payload, "EA004")
    return {
        "plan_id": plan_id,
        "warning_id": f"WARNING-{plan_id}",
        "warning_type": "stockout",
        "warning_time": "2026-07-17T07:59:00+08:00",
        "created_at": "2026-07-17T08:00:00+08:00",
        "expire_at": "2026-07-17T08:30:00+08:00",
        "status": "PENDING",
        "workshop_code": "S2",
        "buffer_code": warning_buffer["buffer_code"],
        "upstream_process_code": upstream,
        "downstream_process_code": downstream,
        "monitored_order_code": monitored["order_code"],
        "process_code": candidate_machine["process_code"],
        "source_order_code": support["order_code"],
        "target_order_code": monitored["order_code"],
        "source_product_code": support["product_code"],
        "target_product_code": monitored["product_code"],
        "before_machine_count": 1,
        "before_machine_codes": ["EA003"],
        "expected_machine_count": 2,
        "expected_delta_direction": "increase",
        "candidate_machines": [
            {
                "machine_code": "EA004",
                "baseline_order_code": support["order_code"],
                "baseline_product_code": support["product_code"],
                "baseline_product_name": support["product_name"],
                "baseline_wafer_size": support["wafer_size"],
                "baseline_wafer_spec": "N",
                "baseline_source_grade": support["source_grade"],
                "expected_target_order_code": monitored["order_code"],
                "expected_target_product_code": monitored["product_code"],
                "expected_target_product_name": monitored["product_name"],
                "expected_target_wafer_size": monitored["wafer_size"],
                "expected_target_wafer_spec": "N",
                "expected_target_source_grade": monitored["source_grade"],
                "process_code": candidate_machine["process_code"],
                "workshop_code": "S2",
                "source_buffer_code": None,
                "target_buffer_code": warning_buffer["buffer_code"],
                "target_upstream_process_code": upstream,
                "target_downstream_process_code": downstream,
            }
        ],
        "baseline_machine_bindings": [
            _baseline(payload, "EA003", "ORD-S2-001"),
            _baseline(payload, "EA004", "ORD-S2-002"),
            _baseline(payload, "EA023", "ORD-S2-003"),
            _baseline(payload, "EA024", "ORD-S2-004"),
        ],
        "confirmed_machine_codes": [],
    }


def _active_event_for_plan(plan: dict, *, observed_minute: int = 10) -> dict:
    candidate = plan["candidate_machines"][0]
    return {
        "event_id": f"CUT-{plan['plan_id']}-{candidate['machine_code']}",
        "plan_id": plan["plan_id"],
        "warning_id": plan["warning_id"],
        "machine_code": candidate["machine_code"],
        "source_order_code": candidate["baseline_order_code"],
        "target_order_code": candidate["expected_target_order_code"],
        "workshop_code": plan["workshop_code"],
        "source_buffer_code": candidate["source_buffer_code"],
        "target_buffer_code": candidate["target_buffer_code"],
        "upstream_process_code": candidate["target_upstream_process_code"],
        "downstream_process_code": candidate[
            "target_downstream_process_code"
        ],
        "source_wafer_size": candidate["baseline_wafer_size"],
        "source_wafer_spec": candidate["baseline_wafer_spec"],
        "target_wafer_size": candidate["expected_target_wafer_size"],
        "target_wafer_spec": candidate["expected_target_wafer_spec"],
        "cutline_start_time": (
            f"2026-07-17T08:{observed_minute:02d}:00+08:00"
        ),
        "negative_start_time": None,
        "status": (
            "return_recommended"
            if plan["status"] == "RETURN_SUGGESTED"
            else "active"
        ),
        "contribution_capacity": None,
        "warning_type": plan["warning_type"],
        "process_code": plan["process_code"],
        "warning_buffer_code": plan["buffer_code"],
        "warning_upstream_process_code": plan["upstream_process_code"],
        "warning_downstream_process_code": plan["downstream_process_code"],
        "is_recommended_candidate": True,
    }


def _payload_with_plan() -> dict:
    payload = build_base_request_payload()
    payload["snapshot_meta"]["snapshot_time"] = (
        "2026-07-17T08:20:00+08:00"
    )
    payload["pending_cutline_plans"] = [_stockout_plan(payload)]
    payload["agv_relations"].extend(
        [
            _agv_record(
                payload,
                "EA004",
                "ORD-S2-002",
                "2026-07-17T07:55:00+08:00",
            ),
            _agv_record(
                payload,
                "EA004",
                "ORD-S2-001",
                "2026-07-17T08:10:00+08:00",
                previous_product_name=_product_by_order(
                    payload, "ORD-S2-002"
                )["product_name"],
            ),
        ]
    )
    return payload


def _overflow_plan(payload: dict) -> dict:
    plan = _stockout_plan(payload, plan_id="PLAN-OVERFLOW-1")
    monitored = _product_by_order(payload, "ORD-S2-001")
    support = _product_by_order(payload, "ORD-S2-002")
    warning_buffer = payload["buffer_master"][1]
    target_buffer = deepcopy(warning_buffer)
    target_buffer["buffer_code"] = "310110302-ALT"
    payload["buffer_master"].append(target_buffer)
    candidate = plan["candidate_machines"][0]
    candidate.update(
        {
            "machine_code": "EA003",
            "baseline_order_code": monitored["order_code"],
            "baseline_product_code": monitored["product_code"],
            "baseline_product_name": monitored["product_name"],
            "baseline_wafer_size": monitored["wafer_size"],
            "baseline_source_grade": monitored["source_grade"],
            "expected_target_order_code": support["order_code"],
            "expected_target_product_code": support["product_code"],
            "expected_target_product_name": support["product_name"],
            "expected_target_wafer_size": support["wafer_size"],
            "expected_target_source_grade": support["source_grade"],
            "source_buffer_code": warning_buffer["buffer_code"],
            "target_buffer_code": target_buffer["buffer_code"],
        }
    )
    plan.update(
        {
            "warning_type": "overflow",
            "expected_machine_count": 0,
            "expected_delta_direction": "decrease",
            "source_order_code": monitored["order_code"],
            "target_order_code": support["order_code"],
            "source_product_code": monitored["product_code"],
            "target_product_code": support["product_code"],
            "candidate_machines": [candidate],
        }
    )
    return plan


def _snapshot(payload: dict):
    request = BackendRequestLoader().load_cutline_dict(payload)
    return SnapshotAdapter().to_algorithm_snapshot(request)


def _assert_conversion_error(payload: dict, pattern: str) -> None:
    with pytest.raises(SnapshotConversionError, match=pattern):
        _snapshot(payload)


def test_pending_plan_and_windowed_history_are_normalized_without_mutation():
    payload = _payload_with_plan()
    original = deepcopy(payload)

    snapshot = _snapshot(payload)

    assert payload == original
    assert snapshot.pending_cutline_plans[0].plan_id == "PLAN-PENDING-1"
    assert snapshot.pending_cutline_plans[0] is not (
        BackendRequestLoader().load_cutline_dict(payload).pending_cutline_plans[0]
    )
    assert [item.machine_code for item in snapshot.agv_binding_history] == [
        "EA004"
    ]
    history = snapshot.agv_binding_history[0]
    assert history.order_code == "ORD-S2-001"
    assert history.product_code == "PROD-S2-N-TARGET"
    assert history.previous_product_code == "PROD-S2-N-SUPPORT"
    assert history.previous_product_name == _product_by_order(
        payload, "ORD-S2-002"
    )["product_name"]
    assert history.binding_time.isoformat() == "2026-07-17T08:10:00+08:00"


@pytest.mark.parametrize(
    ("mutate", "pattern"),
    [
        (
            lambda plan: plan.update(
                {"expire_at": "2026-07-17T08:29:59+08:00"}
            ),
            "PLAN-PENDING-1.*confirmation window.*30",
        ),
        (
            lambda plan: plan["baseline_machine_bindings"][1].update(
                {"process_code": "UNKNOWN-PROCESS"}
            ),
            "PLAN-PENDING-1.*EA004.*process_code.*UNKNOWN-PROCESS",
        ),
        (
            lambda plan: plan["candidate_machines"][0].update(
                {"workshop_code": "UNKNOWN-WORKSHOP"}
            ),
            "PLAN-PENDING-1.*EA004.*workshop_code.*UNKNOWN-WORKSHOP",
        ),
            (
                lambda plan: plan["candidate_machines"][0].update(
                    {
                        "expected_target_order_code": "ORD-S2-002",
                        "expected_target_product_code": "PROD-S2-N-SUPPORT",
                        "expected_target_product_name": "182N支援产品",
                    }
                ),
            "PLAN-PENDING-1.*EA004.*stockout.*target.*ORD-S2-001",
        ),
    ],
)
def test_pending_plan_relational_conflicts_are_rejected(mutate, pattern):
    payload = _payload_with_plan()
    mutate(payload["pending_cutline_plans"][0])

    _assert_conversion_error(payload, pattern)


def test_pending_plan_duplicate_id_and_business_key_are_not_overwritten():
    payload = _payload_with_plan()
    duplicate = deepcopy(payload["pending_cutline_plans"][0])
    duplicate["warning_id"] = "WARNING-OTHER"
    payload["pending_cutline_plans"].append(duplicate)

    _assert_conversion_error(
        payload,
        "duplicate plan_id.*PLAN-PENDING-1.*conflicting",
    )

    duplicate["plan_id"] = "PLAN-PENDING-2"
    _assert_conversion_error(
        payload,
        "business key.*PLAN-PENDING-1.*PLAN-PENDING-2",
    )


@pytest.mark.parametrize(
    "status",
    ["CONFIRMED", "EXPIRED", "RETURN_SUGGESTED"],
)
def test_terminal_plans_do_not_conflict_on_open_business_key(status: str):
    payload = _payload_with_plan()
    first = payload["pending_cutline_plans"][0]
    second = deepcopy(first)
    second["plan_id"] = "PLAN-TERMINAL-2"
    second["warning_id"] = "WARNING-TERMINAL-2"
    for plan in (first, second):
        plan["status"] = status
        plan["confirmed_machine_codes"] = (
            [] if status == "EXPIRED" else ["EA004"]
        )
    payload["pending_cutline_plans"] = [first, second]
    if status != "EXPIRED":
        payload["active_cutline_events"] = [
            _active_event_for_plan(first, observed_minute=10),
            _active_event_for_plan(second, observed_minute=11),
        ]

    snapshot = _snapshot(payload)
    request = BackendRequestLoader().load_dict(payload)
    validation = BackendRequestCompletenessValidator().validate(request)

    assert len(snapshot.pending_cutline_plans) == 2
    assert not any(
        issue.dataset == "pending_cutline_plans"
        and issue.field == "business_key"
        for issue in validation.issues
    )


def test_legacy_none_plan_process_is_normalized_to_machine_process():
    payload = _payload_with_plan()
    payload["pending_cutline_plans"][0]["process_code"] = None

    plan = _snapshot(payload).pending_cutline_plans[0]

    assert plan.process_code == _machine(payload, "EA004")["process_code"]


def test_nonempty_plan_process_must_match_authoritative_machine_process():
    payload = _payload_with_plan()
    payload["pending_cutline_plans"][0]["process_code"] = "UNKNOWN-PROCESS"

    _assert_conversion_error(
        payload,
        "PLAN-PENDING-1.*process_code.*UNKNOWN-PROCESS",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_order_code", "ORD-S2-004"),
        ("target_order_code", "ORD-S2-004"),
        ("source_product_code", "PROD-S2-N-ALT"),
        ("target_product_code", "PROD-S2-N-ALT"),
    ],
)
def test_top_level_candidate_summary_must_match_unique_candidate_value(
    field, value
):
    payload = _payload_with_plan()
    payload["pending_cutline_plans"][0][field] = value

    _assert_conversion_error(payload, f"PLAN-PENDING-1.*{field}")


def test_blank_baseline_machine_status_is_rejected():
    payload = _payload_with_plan()
    payload["pending_cutline_plans"][0]["baseline_machine_bindings"][0][
        "machine_status"
    ] = "   "

    _assert_conversion_error(payload, "PLAN-PENDING-1.*EA003.*machine_status")


def test_candidate_must_copy_a_known_baseline_and_known_catalog_values():
    payload = _payload_with_plan()
    candidate = payload["pending_cutline_plans"][0]["candidate_machines"][0]
    candidate["baseline_product_code"] = "UNKNOWN-PRODUCT"

    _assert_conversion_error(
        payload,
        "PLAN-PENDING-1.*EA004.*baseline_product_code.*UNKNOWN-PRODUCT",
    )


def test_before_machine_codes_may_be_a_running_subset_of_monitored_baselines():
    payload = _payload_with_plan()
    plan = payload["pending_cutline_plans"][0]
    plan["before_machine_count"] = 0
    plan["before_machine_codes"] = []
    plan["expected_machine_count"] = 1

    snapshot = _snapshot(payload)

    assert snapshot.pending_cutline_plans[0].before_machine_codes == []


def test_each_before_machine_must_have_monitored_baseline_order():
    payload = _payload_with_plan()
    plan = payload["pending_cutline_plans"][0]
    plan["before_machine_codes"] = ["EA004"]

    _assert_conversion_error(
        payload,
        "PLAN-PENDING-1.*before_machine_codes.*EA004.*ORD-S2-002.*ORD-S2-001",
    )


def test_overflow_candidate_must_be_in_warning_time_before_machine_codes():
    payload = _payload_with_plan()
    plan = _overflow_plan(payload)
    baseline_by_machine = {
        item["machine_code"]: item
        for item in plan["baseline_machine_bindings"]
    }
    for field in (
        "order_code",
        "product_code",
        "product_name",
        "wafer_size",
        "wafer_spec",
        "source_grade",
    ):
        baseline_by_machine["EA004"][field] = baseline_by_machine["EA003"][
            field
        ]
    plan["before_machine_codes"] = ["EA004"]
    payload["pending_cutline_plans"] = [plan]

    _assert_conversion_error(
        payload,
        "PLAN-OVERFLOW-1.*EA003.*overflow candidate.*before_machine_codes",
    )


def test_pending_created_at_cannot_be_after_snapshot_time():
    payload = _payload_with_plan()
    payload["snapshot_meta"]["snapshot_time"] = (
        "2026-07-17T07:59:59+08:00"
    )

    _assert_conversion_error(
        payload,
        "PLAN-PENDING-1.*created_at.*snapshot_time",
    )


def test_observable_scope_machine_missing_from_baseline_is_explicit():
    payload = _payload_with_plan()
    plan = payload["pending_cutline_plans"][0]
    plan["baseline_machine_bindings"] = [
        item
        for item in plan["baseline_machine_bindings"]
        if item["machine_code"] != "EA023"
    ]

    _assert_conversion_error(
        payload,
        "PLAN-PENDING-1.*EA023.*07:55:00.*baseline",
    )


def test_window_observation_missing_from_baseline_is_not_silently_filtered():
    payload = _payload_with_plan()
    plan = payload["pending_cutline_plans"][0]
    plan["baseline_machine_bindings"] = [
        item
        for item in plan["baseline_machine_bindings"]
        if item["machine_code"] != "EA023"
    ]
    payload["agv_relations"] = [
        item
        for item in payload["agv_relations"]
        if item["equipmentid"] != "EA023"
    ]
    payload["agv_relations"].append(
        _agv_record(
            payload,
            "EA023",
            "ORD-S2-003",
            "2026-07-17T08:15:00+08:00",
        )
    )

    _assert_conversion_error(
        payload,
        "PLAN-PENDING-1.*EA023.*08:15:00.*baseline",
    )


def test_persisted_baseline_is_accepted_when_old_agv_record_is_not_replayed():
    payload = _payload_with_plan()
    payload["agv_relations"] = [
        item
        for item in payload["agv_relations"]
        if not (
            item["equipmentid"] == "EA004"
            and item["createtime"] == "2026-07-17T07:55:00+08:00"
        )
    ]

    snapshot = _snapshot(payload)

    saved = next(
        item
        for item in snapshot.pending_cutline_plans[0].baseline_machine_bindings
        if item.machine_code == "EA004"
    )
    assert saved.order_code == "ORD-S2-002"
    assert any(
        item.machine_code == "EA004"
        and item.order_code == "ORD-S2-001"
        for item in snapshot.agv_binding_history
    )


def test_saved_baseline_observed_at_must_not_be_after_created_at():
    payload = _payload_with_plan()
    plan = payload["pending_cutline_plans"][0]
    baseline = next(
        item
        for item in plan["baseline_machine_bindings"]
        if item["machine_code"] == "EA004"
    )
    baseline["observed_at"] = "2026-07-17T08:00:01+08:00"
    payload["agv_relations"] = [
        item
        for item in payload["agv_relations"]
        if not (
            item["equipmentid"] == "EA004"
            and item["createtime"] == "2026-07-17T07:55:00+08:00"
        )
    ]

    _assert_conversion_error(
        payload,
        (
            "PLAN-PENDING-1.*EA004.*observed_at.*08:00:01"
            ".*created_at.*08:00:00"
        ),
    )


def test_raw_binding_exactly_at_created_at_is_a_valid_baseline_boundary():
    payload = _payload_with_plan()
    plan = payload["pending_cutline_plans"][0]
    baseline = next(
        item
        for item in plan["baseline_machine_bindings"]
        if item["machine_code"] == "EA004"
    )
    baseline["observed_at"] = "2026-07-17T08:00:00+08:00"
    payload["agv_relations"] = [
        item
        for item in payload["agv_relations"]
        if not (
            item["equipmentid"] == "EA004"
            and item["createtime"] == "2026-07-17T07:55:00+08:00"
        )
    ]
    payload["agv_relations"].append(
        _agv_record(
            payload,
            "EA004",
            "ORD-S2-002",
            "2026-07-17T08:00:00+08:00",
        )
    )

    snapshot = _snapshot(payload)

    assert [
        item.binding_time.isoformat()
        for item in snapshot.agv_binding_history
        if item.machine_code == "EA004"
    ] == ["2026-07-17T08:10:00+08:00"]


def test_warning_to_creation_agv_record_updates_created_at_baseline_without_gap():
    payload = _payload_with_plan()
    plan = payload["pending_cutline_plans"][0]
    baseline = next(
        item
        for item in plan["baseline_machine_bindings"]
        if item["machine_code"] == "EA004"
    )
    baseline["observed_at"] = "2026-07-17T07:59:30+08:00"
    payload["agv_relations"].append(
        _agv_record(
            payload,
            "EA004",
            "ORD-S2-002",
            "2026-07-17T07:59:30+08:00",
        )
    )

    snapshot = _snapshot(payload)

    saved = next(
        item
        for item in snapshot.pending_cutline_plans[0].baseline_machine_bindings
        if item.machine_code == "EA004"
    )
    assert saved.observed_at.isoformat() == "2026-07-17T07:59:30+08:00"


def test_agv_record_exactly_at_created_at_belongs_to_baseline_not_history():
    payload = _payload_with_plan()
    baseline = next(
        item
        for item in payload["pending_cutline_plans"][0][
            "baseline_machine_bindings"
        ]
        if item["machine_code"] == "EA004"
    )
    baseline["observed_at"] = "2026-07-17T08:00:00+08:00"
    payload["agv_relations"].append(
        _agv_record(
            payload,
            "EA004",
            "ORD-S2-002",
            "2026-07-17T08:00:00+08:00",
        )
    )

    snapshot = _snapshot(payload)

    assert all(
        item.binding_time.isoformat() != "2026-07-17T08:00:00+08:00"
        for item in snapshot.agv_binding_history
    )


@pytest.mark.parametrize(
    "status",
    ["CONFIRMED", "EXPIRED", "RETURN_SUGGESTED"],
)
def test_terminal_plan_ignores_later_agv_and_missing_baseline_machine(status):
    payload = _payload_with_plan()
    plan = payload["pending_cutline_plans"][0]
    plan["status"] = status
    plan["confirmed_machine_codes"] = (
        [] if status == "EXPIRED" else ["EA004"]
    )
    plan["baseline_machine_bindings"] = [
        item
        for item in plan["baseline_machine_bindings"]
        if item["machine_code"] != "EA023"
    ]
    if status != "EXPIRED":
        payload["active_cutline_events"] = [_active_event_for_plan(plan)]

    snapshot = _snapshot(payload)

    assert snapshot.agv_binding_history == []


def test_latest_observable_pre_warning_binding_must_match_saved_baseline():
    payload = _payload_with_plan()
    plan = payload["pending_cutline_plans"][0]
    baseline = next(
        item
        for item in plan["baseline_machine_bindings"]
        if item["machine_code"] == "EA023"
    )
    other = _product_by_order(payload, "ORD-S2-004")
    baseline.update(
        {
            "order_code": other["order_code"],
            "product_code": other["product_code"],
            "product_name": other["product_name"],
            "wafer_size": other["wafer_size"],
            "source_grade": other["source_grade"],
        }
    )

    _assert_conversion_error(
        payload,
        "PLAN-PENDING-1.*EA023.*saved baseline.*ORD-S2-004.*observable.*ORD-S2-003",
    )


def test_pre_warning_same_time_binding_conflict_is_not_hidden_by_later_record():
    payload = _payload_with_plan()
    payload["agv_relations"].extend(
        [
            _agv_record(
                payload,
                "EA023",
                "ORD-S2-004",
                "2026-07-17T07:55:00+08:00",
            ),
            _agv_record(
                payload,
                "EA023",
                "ORD-S2-003",
                "2026-07-17T08:15:00+08:00",
            ),
        ]
    )

    _assert_conversion_error(
        payload,
        "PLAN-PENDING-1.*EA023.*07:55:00.*ORD-S2-003.*ORD-S2-004",
    )


@pytest.mark.parametrize(
    ("mutate", "pattern"),
    [
        (
            lambda plan: plan.update({"expected_machine_count": 99}),
            "PLAN-PENDING-1.*expected_machine_count.*99.*candidate_count",
        ),
        (
            lambda plan: plan.update({"buffer_code": "UNKNOWN-BUFFER"}),
            "PLAN-PENDING-1.*UNKNOWN-BUFFER.*does not exist",
        ),
        (
            lambda plan: plan["baseline_machine_bindings"][1].update(
                {"machine_code": "UNKNOWN-MACHINE"}
            )
            or plan["candidate_machines"][0].update(
                {"machine_code": "UNKNOWN-MACHINE"}
            ),
            "PLAN-PENDING-1.*UNKNOWN-MACHINE.*does not exist",
        ),
    ],
)
def test_pending_counts_and_unknown_references_are_rejected(mutate, pattern):
    payload = _payload_with_plan()
    mutate(payload["pending_cutline_plans"][0])

    _assert_conversion_error(payload, pattern)


def test_candidate_machine_must_belong_to_plan_output_side_process():
    payload = _payload_with_plan()
    plan = payload["pending_cutline_plans"][0]
    support = _product_by_order(payload, "ORD-S2-002")
    baseline = _baseline(payload, "EA005", "ORD-S2-002")
    plan["baseline_machine_bindings"][1] = baseline
    candidate = plan["candidate_machines"][0]
    candidate.update(
        {
            "machine_code": "EA005",
            "process_code": _machine(payload, "EA005")["process_code"],
            "baseline_order_code": support["order_code"],
            "baseline_product_code": support["product_code"],
            "baseline_product_name": support["product_name"],
            "baseline_wafer_size": support["wafer_size"],
            "baseline_source_grade": support["source_grade"],
        }
    )

    _assert_conversion_error(
        payload,
        "PLAN-PENDING-1.*EA005.*process_code.*output-side",
    )


@pytest.mark.parametrize(
    ("mutate", "pattern"),
    [
        (
            lambda payload, candidate: candidate.update(
                {"baseline_wafer_spec": "R"}
            )
            or payload["pending_cutline_plans"][0][
                "baseline_machine_bindings"
            ][1].update({"wafer_spec": "R"}),
            "PLAN-PENDING-1.*EA004.*wafer spec.*R.*N",
        ),
        (
            lambda payload, candidate: payload["products"][1].update(
                {"source_grade": "A-"}
            )
            or candidate.update(
                {"baseline_source_grade": "A-"}
            )
            or payload["pending_cutline_plans"][0][
                "baseline_machine_bindings"
            ][1].update({"source_grade": "A-"}),
            "PLAN-PENDING-1.*EA004.*source grade.*A-.*A",
        ),
    ],
)
def test_candidate_product_compatibility_is_revalidated(mutate, pattern):
    payload = _payload_with_plan()
    candidate = payload["pending_cutline_plans"][0]["candidate_machines"][0]
    mutate(payload, candidate)

    _assert_conversion_error(payload, pattern)


def test_stockout_source_buffer_when_present_must_use_output_side_process():
    payload = _payload_with_plan()
    candidate = payload["pending_cutline_plans"][0]["candidate_machines"][0]
    candidate["source_buffer_code"] = payload["buffer_master"][0][
        "buffer_code"
    ]

    _assert_conversion_error(
        payload,
        "PLAN-PENDING-1.*EA004.*source_buffer_code.*output-side",
    )


@pytest.mark.parametrize(
    "snapshot_time",
    ["2026-07-17T08:30:00+08:00", "2026-07-17T09:00:00+08:00"],
)
def test_expired_duplicate_business_keys_do_not_block_snapshot_conversion(
    snapshot_time,
):
    payload = _payload_with_plan()
    payload["snapshot_meta"]["snapshot_time"] = snapshot_time
    duplicate = deepcopy(payload["pending_cutline_plans"][0])
    duplicate["plan_id"] = "PLAN-PENDING-EXPIRED-2"
    duplicate["warning_id"] = "WARNING-EXPIRED-2"
    payload["pending_cutline_plans"].append(duplicate)

    snapshot = _snapshot(payload)

    assert [plan.plan_id for plan in snapshot.pending_cutline_plans] == [
        "PLAN-PENDING-1",
        "PLAN-PENDING-EXPIRED-2",
    ]


@pytest.mark.parametrize(
    "snapshot_time",
    ["2026-07-17T08:30:00+08:00", "2026-07-17T09:00:00+08:00"],
)
def test_backend_validator_ignores_expired_duplicate_business_keys(
    snapshot_time,
):
    payload = _payload_with_plan()
    payload.pop("active_cutline_events")
    payload["snapshot_meta"]["snapshot_time"] = snapshot_time
    duplicate = deepcopy(payload["pending_cutline_plans"][0])
    duplicate["plan_id"] = "PLAN-PENDING-EXPIRED-2"
    duplicate["warning_id"] = "WARNING-EXPIRED-2"
    payload["pending_cutline_plans"].append(duplicate)
    request = BackendRequestLoader().load_dict(payload)

    result = BackendRequestCompletenessValidator().validate(request)

    assert not any(
        issue.dataset == "pending_cutline_plans"
        and issue.field == "business_key"
        for issue in result.issues
    )


def test_overflow_direction_and_distinct_target_interval_are_accepted():
    payload = _payload_with_plan()
    payload["pending_cutline_plans"] = [_overflow_plan(payload)]

    snapshot = _snapshot(payload)

    candidate = snapshot.pending_cutline_plans[0].candidate_machines[0]
    assert candidate.source_buffer_code == "310110302"
    assert candidate.target_buffer_code == "310110302-ALT"


@pytest.mark.parametrize(
    ("field", "value", "pattern"),
    [
        (
            "source_buffer_code",
            None,
            "PLAN-OVERFLOW-1.*EA003.*overflow.*source_buffer_code",
        ),
        (
            "target_buffer_code",
            "310110302",
            "PLAN-OVERFLOW-1.*EA003.*overflow.*target_buffer_code",
        ),
        (
            "expected_target_order_code",
            "ORD-S2-001",
            "PLAN-OVERFLOW-1.*EA003.*overflow.*target.*different",
        ),
    ],
)
def test_overflow_invalid_direction_is_rejected(field, value, pattern):
    payload = _payload_with_plan()
    plan = _overflow_plan(payload)
    plan["candidate_machines"][0][field] = value
    if field == "expected_target_order_code":
        monitored = _product_by_order(payload, "ORD-S2-001")
        plan["candidate_machines"][0].update(
            {
                "expected_target_product_code": monitored["product_code"],
                "expected_target_product_name": monitored["product_name"],
            }
        )
    payload["pending_cutline_plans"] = [plan]

    _assert_conversion_error(payload, pattern)


def test_history_window_is_open_at_created_closed_at_expire_and_snapshot_bounded():
    payload = _payload_with_plan()
    payload["snapshot_meta"]["snapshot_time"] = (
        "2026-07-17T08:40:00+08:00"
    )
    payload["agv_relations"] = [
        item
        for item in payload["agv_relations"]
        if item["equipmentid"] != "EA004"
    ]
    plan = payload["pending_cutline_plans"][0]
    plan["warning_time"] = plan["created_at"]
    next(
        item
        for item in plan["baseline_machine_bindings"]
        if item["machine_code"] == "EA004"
    )["observed_at"] = "2026-07-17T08:00:00+08:00"
    for binding_time in (
        "2026-07-17T08:00:00+08:00",
        "2026-07-17T08:00:01+08:00",
        "2026-07-17T08:30:00+08:00",
        "2026-07-17T08:30:01+08:00",
        "2026-07-17T08:41:00+08:00",
    ):
        order_code = (
            "ORD-S2-002"
            if binding_time == "2026-07-17T08:00:00+08:00"
            else "ORD-S2-001"
        )
        payload["agv_relations"].append(
            _agv_record(
                payload,
                "EA004",
                order_code,
                binding_time,
            )
        )

    snapshot = _snapshot(payload)

    assert [
        item.binding_time.isoformat()
        for item in snapshot.agv_binding_history
        if item.machine_code == "EA004"
    ] == [
        "2026-07-17T08:00:01+08:00",
        "2026-07-17T08:30:00+08:00",
    ]


def test_history_excludes_future_record_even_when_it_is_inside_plan_window():
    payload = _payload_with_plan()
    payload["snapshot_meta"]["snapshot_time"] = (
        "2026-07-17T08:10:00+08:00"
    )
    payload["agv_relations"].append(
        _agv_record(
            payload,
            "EA004",
            "ORD-S2-001",
            "2026-07-17T08:15:00+08:00",
        )
    )

    snapshot = _snapshot(payload)

    assert all(
        item.binding_time.isoformat() != "2026-07-17T08:15:00+08:00"
        for item in snapshot.agv_binding_history
    )


def test_history_exact_duplicate_collapses_and_blank_previous_is_none():
    payload = _payload_with_plan()
    matching = next(
        item
        for item in payload["agv_relations"]
        if item["equipmentid"] == "EA004"
        and item["createtime"] == "2026-07-17T08:10:00+08:00"
    )
    matching["lastlinename"] = "   "
    payload["agv_relations"].append(deepcopy(matching))

    snapshot = _snapshot(payload)

    matches = [
        item
        for item in snapshot.agv_binding_history
        if item.machine_code == "EA004"
        and item.binding_time.isoformat() == "2026-07-17T08:10:00+08:00"
    ]
    assert len(matches) == 1
    assert matches[0].previous_product_code is None
    assert matches[0].previous_product_name is None


def test_history_null_previous_product_stays_none():
    payload = _payload_with_plan()
    transition = next(
        item
        for item in payload["agv_relations"]
        if item["equipmentid"] == "EA004"
        and item["createtime"] == "2026-07-17T08:10:00+08:00"
    )
    transition["lastlinename"] = None

    history = _snapshot(payload).agv_binding_history

    observed = next(item for item in history if item.machine_code == "EA004")
    assert observed.previous_product_code is None
    assert observed.previous_product_name is None


def test_pre_warning_current_product_not_last_product_defines_baseline():
    payload = _payload_with_plan()
    old_binding = next(
        item
        for item in payload["agv_relations"]
        if item["equipmentid"] == "EA004"
        and item["createtime"] == "2026-07-17T07:55:00+08:00"
    )
    old_binding["lastlinename"] = _product_by_order(
        payload, "ORD-S2-001"
    )["product_name"]

    snapshot = _snapshot(payload)

    saved = next(
        item
        for item in snapshot.pending_cutline_plans[0].baseline_machine_bindings
        if item.machine_code == "EA004"
    )
    assert saved.order_code == "ORD-S2-002"


def test_equivalent_timezone_offsets_share_the_same_confirmation_window():
    payload = _payload_with_plan()
    plan = payload["pending_cutline_plans"][0]
    plan.update(
        {
            "warning_time": "2026-07-16T23:59:00Z",
            "created_at": "2026-07-17T00:00:00Z",
            "expire_at": "2026-07-17T00:30:00Z",
        }
    )
    payload["snapshot_meta"]["snapshot_time"] = "2026-07-17T00:20:00Z"
    transition = next(
        item
        for item in payload["agv_relations"]
        if item["equipmentid"] == "EA004"
        and item["createtime"] == "2026-07-17T08:10:00+08:00"
    )
    transition["createtime"] = "2026-07-17T09:10:00+09:00"

    snapshot = _snapshot(payload)

    observed = next(
        item
        for item in snapshot.agv_binding_history
        if item.machine_code == "EA004"
    )
    assert observed.binding_time.isoformat() == "2026-07-17T08:10:00+08:00"


def test_relevant_agv_wafer_spec_must_not_be_blank():
    payload = _payload_with_plan()
    latest = next(
        item
        for item in payload["agv_relations"]
        if item["equipmentid"] == "EA004"
        and item["createtime"] == "2026-07-17T08:10:00+08:00"
    )
    latest["waferspec"] = "   "

    _assert_conversion_error(
        payload,
        "EA004.*wafer_spec.*blank",
    )


def test_history_same_machine_time_business_conflict_names_all_context():
    payload = _payload_with_plan()
    payload["snapshot_meta"]["snapshot_time"] = (
        "2026-07-17T08:20:00+08:00"
    )
    payload["agv_relations"].extend(
        [
            _agv_record(
                payload,
                "EA004",
                "ORD-S2-002",
                "2026-07-17T08:12:00+08:00",
            ),
            _agv_record(
                payload,
                "EA004",
                "ORD-S2-001",
                "2026-07-17T08:12:00+08:00",
            ),
            _agv_record(
                payload,
                "EA004",
                "ORD-S2-001",
                "2026-07-17T08:20:00+08:00",
            ),
        ]
    )

    _assert_conversion_error(
        payload,
        "PLAN-PENDING-1.*EA004.*08:12:00.*ORD-S2-001.*ORD-S2-002",
    )


def _active_event(payload: dict) -> dict:
    plan = payload["pending_cutline_plans"][0]
    return {
        "event_id": "CUT-PLAN-PENDING-1-EA004",
        "plan_id": "PLAN-PENDING-1",
        "machine_code": "EA004",
        "source_order_code": "ORD-S2-002",
        "target_order_code": "ORD-S2-001",
        "workshop_code": "S2",
        "source_buffer_code": None,
        "target_buffer_code": plan["buffer_code"],
        "upstream_process_code": plan["upstream_process_code"],
        "downstream_process_code": plan["downstream_process_code"],
        "source_wafer_size": "182",
        "source_wafer_spec": "N",
        "target_wafer_size": "182",
        "target_wafer_spec": "N",
        "cutline_start_time": "2026-07-17T08:10:00+08:00",
        "negative_start_time": None,
        "contribution_capacity": 200.0,
        "warning_type": "stockout",
        "process_code": plan["upstream_process_code"],
        "warning_buffer_code": plan["buffer_code"],
        "warning_upstream_process_code": plan["upstream_process_code"],
        "warning_downstream_process_code": plan[
            "downstream_process_code"
        ],
        "is_recommended_candidate": True,
    }


def test_active_event_hidden_confirmation_metadata_is_preserved():
    payload = _payload_with_plan()
    payload["active_cutline_events"] = [_active_event(payload)]

    event = _snapshot(payload).active_cutline_events[0]

    assert event.plan_id == "PLAN-PENDING-1"
    assert event.source_buffer_code is None
    assert event.source_wafer_size == "182"
    assert event.source_wafer_spec == "N"
    assert event.contribution_capacity == 200.0
    assert event.warning_type == "stockout"
    assert event.process_code == event.upstream_process_code
    assert event.warning_buffer_code == event.target_buffer_code
    assert event.warning_upstream_process_code == event.upstream_process_code
    assert event.warning_downstream_process_code == event.downstream_process_code
    assert event.is_recommended_candidate is True


@pytest.mark.parametrize(
    ("field", "value", "pattern"),
    [
        (
            "warning_buffer_code",
            "UNKNOWN-BUFFER",
            "warning_buffer_code.*UNKNOWN-BUFFER.*does not exist",
        ),
        (
            "process_code",
            "UNKNOWN-PROCESS",
            "process_code.*UNKNOWN-PROCESS.*process route does not exist",
        ),
    ],
)
def test_active_event_hidden_references_are_strict(field, value, pattern):
    payload = _payload_with_plan()
    event = _active_event(payload)
    event[field] = value
    payload["active_cutline_events"] = [event]

    _assert_conversion_error(payload, pattern)


def test_backend_validator_reports_duplicate_pending_id_and_business_key():
    payload = _payload_with_plan()
    payload.pop("active_cutline_events")
    duplicate = deepcopy(payload["pending_cutline_plans"][0])
    payload["pending_cutline_plans"].append(duplicate)
    request = BackendRequestLoader().load_dict(payload)

    result = BackendRequestCompletenessValidator().validate(request)

    assert any(
        issue.code == "duplicate_key"
        and issue.dataset == "pending_cutline_plans"
        and issue.field == "plan_id"
        and issue.message.startswith("切线/混料-")
        and issue.message.endswith("字段存在重复值")
        for issue in result.issues
    )
    duplicate["plan_id"] = "PLAN-PENDING-2"
    request = BackendRequestLoader().load_dict(payload)
    result = BackendRequestCompletenessValidator().validate(request)
    assert any(
        issue.code == "duplicate_key"
        and issue.dataset == "pending_cutline_plans"
        and issue.field == "business_key"
        and issue.message.startswith("切线/混料-")
        and issue.message.endswith("字段存在重复值")
        for issue in result.issues
    )


def test_backend_validator_locates_nested_pending_blank_code():
    payload = _payload_with_plan()
    payload.pop("active_cutline_events")
    payload["pending_cutline_plans"][0]["candidate_machines"][0][
        "baseline_product_code"
    ] = "   "
    request = BackendRequestLoader().load_dict(payload)

    result = BackendRequestCompletenessValidator().validate(request)

    assert any(
        issue.code == "empty_code"
        and issue.dataset == "pending_cutline_plans"
        and issue.field
        == "candidate_machines[0].baseline_product_code"
        and issue.record_key == "PLAN-PENDING-1"
        for issue in result.issues
    )
