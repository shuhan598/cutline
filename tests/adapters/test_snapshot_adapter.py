from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

import app.adapters.snapshot_adapter as snapshot_adapter_module
from app.schemas.request_schema import AlgorithmSnapshot, CutlineAlgorithmRequest


def _payload() -> dict:
    return {
        "snapshot_meta": {
            "run_id": "run-1",
            "trigger_type": "manual",
            "workshop_id": "S1",
            "snapshot_time": "2026-07-15T08:30:00Z",
            "params_version": 1,
            "catalog_version": "catalog-1",
            "catalog_loaded_at": "2026-07-15T08:00:00Z",
            "degraded_flags": [],
        },
        "machine_realtime": [
            {
                "machine_code": "MC-001",
                "status": "RUNNING",
                "tangent_time": "2026-07-15T07:30:00Z",
                "input_quantity": 11,
                "output_quantity": 12,
                "completed_quantity": 999,
                "period_quantity": 13,
                "out_time": "2026-07-15T08:20:00Z",
            }
        ],
        "machine_master": [
            {
                "machine_code": "MC-001",
                "machine_name": "机台一",
                "process_code": "PROC-01",
                "process_name": "工序一",
            }
        ],
        "machine_process_times": [
            {
                "machine_code": "MC-001",
                "machine_name": "机台一",
                "product_code": "PROD-001",
                "product_name": "产品一",
                "proc_seconds": 12.5,
                "actual_capacity": 288,
            }
        ],
        "workshops": [
            {"workshop_code": "S1", "workshop_name": "一车间"},
            {"workshop_code": "S2", "workshop_name": "二车间"},
        ],
        "lines": [
            {
                "line_code": "LINE-001",
                "line_name": "产线一",
                "wafer_spec": "N",
                "workshop_code": "S1",
                "workshop_name": "一车间",
            }
        ],
        "machine_lines": [
            {
                "machine_code": "MC-001",
                "machine_name": "机台一",
                "line_code": "LINE-001",
                "line_name": "产线一",
                "wafer_spec": "N",
            }
        ],
        "orders": [
            {
                "order_code": "ORD-001",
                "order_name": "至上",
                "order_status": "RUNNING",
                "total_quantity": 10000,
                "piece_source": "A",
                "estimated_yield": "99%",
                "product_code": "PROD-001",
                "product_name": "产品一",
                "workshop_code": "S1",
                "workshop_name": "一车间",
                "produced_quantity": 2000,
                "remaining_quantity": 8000,
            },
            {
                "order_code": "ORD-002",
                "order_name": "华晟",
                "order_status": "WAITING",
                "total_quantity": 5000,
                "piece_source": "B",
                "estimated_yield": "98.5%",
                "product_code": "PROD-001",
                "product_name": "产品一",
                "workshop_code": "S1",
                "workshop_name": "一车间",
                "produced_quantity": 1000,
                "remaining_quantity": 4000,
            },
        ],
        "products": [
            {
                "product_code": "PROD-001",
                "product_name": "产品一",
                "wafer_size": "182",
                "source_grade": "A",
                "material_code": "MAT-001",
                "material_name": "物料一",
            }
        ],
        "process_routes": [
            {
                "process_code": "PROC-01",
                "process_name": "工序一",
                "sequence": 1,
                "cache_type": "BUFFER",
                "workshop_code": "S1",
                "workshop_name": "一车间",
                "loop_code": "LOOP-1",
                "loop_name": "循环一",
                "upstream_process_code": None,
                "upstream_process_name": None,
                "downstream_process_code": "PROC-02",
                "downstream_process_name": "工序二",
            },
            {
                "process_code": "PROC-02",
                "process_name": "工序二",
                "sequence": 2,
                "cache_type": "BUFFER",
                "workshop_code": "S1",
                "workshop_name": "一车间",
                "loop_code": "LOOP-1",
                "loop_name": "循环一",
                "upstream_process_code": "PROC-01",
                "upstream_process_name": "工序一",
                "downstream_process_code": None,
                "downstream_process_name": None,
            },
        ],
        "buffer_realtime": [
            {
                "main_id": "MAIN-001",
                "buffer_code": "BUF-001",
                "bound_source_name": "至上",
                "current_quantity": 1200,
                "current_utilization_rate": 0.6,
            },
            {
                "main_id": "MAIN-001",
                "buffer_code": "BUF-001",
                "bound_source_name": "华晟",
                "current_quantity": 800,
                "current_utilization_rate": 0.4,
            },
            {
                "main_id": "MAIN-001",
                "buffer_code": "BUF-002",
                "bound_source_name": "至上",
                "current_quantity": 100,
                "current_utilization_rate": 0.2,
            },
        ],
        "buffer_master": [
            {
                "buffer_code": "BUF-001",
                "buffer_name": "缓存一",
                "buffer_type": "LINE",
                "buffer_type_title": "线边库",
                "max_capacity": 2000,
                "safety_low": 100,
                "served_process_codes": ["PROC-01", "PROC-02"],
                "served_process_names": ["工序一", "工序二"],
                "loop_code": "LOOP-1",
                "loop_name": "循环一",
            },
            {
                "buffer_code": "BUF-002",
                "buffer_name": "缓存二",
                "buffer_type": "LINE",
                "buffer_type_title": "线边库",
                "max_capacity": 500,
                "safety_low": 50,
                "served_process_codes": ["PROC-01", "PROC-02"],
                "served_process_names": ["工序一", "工序二"],
                "loop_code": "LOOP-1",
                "loop_name": "循环一",
            },
        ],
        "agv_relations": [
            {
                "machine_code": "MC-001",
                "machine_name": "机台一",
                "order_code": "ORD-001",
                "order_name": "至上",
                "binding_time": "2026-07-15 16:00:00",
            }
        ],
    }


def _convert(payload: dict | None = None) -> AlgorithmSnapshot:
    request = CutlineAlgorithmRequest.model_validate(payload or _payload())
    return snapshot_adapter_module.SnapshotAdapter().to_algorithm_snapshot(request)


def _assert_conversion_error(payload: dict, match: str | None = None) -> None:
    error_type = getattr(snapshot_adapter_module, "SnapshotConversionError", ValueError)
    with pytest.raises(error_type, match=match):
        _convert(payload)


def _append_process_route(
    payload: dict,
    *,
    process_code: str,
    sequence: int,
    workshop_code: str = "S1",
    loop_code: str = "LOOP-1",
) -> None:
    payload["process_routes"].append(
        {
            **deepcopy(payload["process_routes"][0]),
            "process_code": process_code,
            "process_name": process_code,
            "sequence": sequence,
            "workshop_code": workshop_code,
            "workshop_name": (
                "一车间" if workshop_code == "S1" else "二车间"
            ),
            "loop_code": loop_code,
            "loop_name": loop_code,
            "upstream_process_code": None,
            "upstream_process_name": None,
            "downstream_process_code": None,
            "downstream_process_name": None,
        }
    )


def _copy_process_pair_to_context(
    payload: dict,
    *,
    workshop_code: str,
    loop_code: str,
) -> None:
    payload["process_routes"].extend(
        [
            {
                **deepcopy(route),
                "workshop_code": workshop_code,
                "workshop_name": (
                    "一车间" if workshop_code == "S1" else "二车间"
                ),
                "loop_code": loop_code,
                "loop_name": loop_code,
            }
            for route in payload["process_routes"][:2]
        ]
    )


def test_minimal_complete_request_converts_to_algorithm_snapshot():
    snapshot = _convert()

    assert isinstance(snapshot, AlgorithmSnapshot)
    assert len(snapshot.workshops) == 2
    assert len(snapshot.buffer_order_inventories) == 3


def test_snapshot_time_is_used_as_current_time():
    snapshot = _convert()

    assert snapshot.current_time == datetime(2026, 7, 15, 8, 30, tzinfo=timezone.utc)


def test_machine_runtime_current_order_code_comes_from_agv_binding():
    assert _convert().machine_runtimes[0].current_order_code == "ORD-001"

@pytest.mark.parametrize("backend_status", ["运行", "running", "RUNNING", " Running "])
def test_running_backend_machine_status_maps_to_algorithm_running(backend_status):
    payload = _payload()
    payload["machine_realtime"][0]["status"] = backend_status

    assert _convert(payload).machine_runtimes[0].status == "running"


@pytest.mark.parametrize("backend_status", ["停机", "异常", "idle", ""])
def test_non_running_backend_machine_status_maps_to_algorithm_stopped(backend_status):
    payload = _payload()
    payload["machine_realtime"][0]["status"] = backend_status

    assert _convert(payload).machine_runtimes[0].status == "stopped"
def test_machine_process_still_comes_from_machine_master():
    machine = _convert().machine_masters[0]

    assert machine.process_code == "PROC-01"
    assert machine.process_name == "工序一"


def test_machine_runtime_quantities_are_raw_30_minute_values():
    runtime = _convert().machine_runtimes[0]

    assert runtime.input_quantity_30m == 11
    assert runtime.output_quantity_30m == 12
    assert runtime.period_quantity_30m == 13


def test_machine_runtime_does_not_include_request_completed_quantity():
    runtime = _convert().machine_runtimes[0]

    assert "completed_quantity" not in runtime.model_dump()
    assert 999 not in runtime.model_dump().values()


def test_machine_runtime_preserves_out_time():
    assert _convert().machine_runtimes[0].out_time == datetime(
        2026, 7, 15, 8, 20, tzinfo=timezone.utc
    )


def test_machine_runtime_does_not_double_quantities():
    runtime = _convert().machine_runtimes[0]

    assert runtime.input_quantity_30m != 22
    assert runtime.output_quantity_30m != 24


def test_machine_line_relation_contains_only_codes():
    relation = _convert().machine_lines[0]

    assert relation.model_dump() == {"machine_code": "MC-001", "line_code": "LINE-001"}


def test_line_wafer_spec_is_preserved():
    assert _convert().lines[0].wafer_spec == "N"


def test_order_remaining_quantity_is_computed_internally():
    order = _convert().orders[0]

    assert order.remaining_quantity == 8000
    assert "remaining_quantity" not in order.__class__.model_fields


def test_backend_remaining_quantity_mismatch_fails():
    payload = _payload()
    payload["orders"][0]["remaining_quantity"] = 7999

    _assert_conversion_error(payload, "ORD-001.*remaining")


def test_backend_remaining_quantity_tolerance_is_one_micro_unit():
    payload = _payload()
    payload["orders"][0]["remaining_quantity"] += 0.000001

    assert _convert(payload).orders[0].remaining_quantity == 8000


def test_backend_remaining_quantity_just_above_tolerance_fails():
    payload = _payload()
    payload["orders"][0].update(
        total_quantity=10,
        produced_quantity=2,
        remaining_quantity=8.0000010000005,
    )

    _assert_conversion_error(payload, "ORD-001.*remaining")


@pytest.mark.parametrize("order_name", ["", "   "])
def test_blank_order_name_fails_in_adapter(order_name):
    payload = _payload()
    payload["orders"][0]["order_name"] = order_name

    _assert_conversion_error(payload, "ORD-001.*name")


def test_buffer_source_name_matches_order_and_sets_order_code():
    inventories = _convert().buffer_order_inventories

    assert [
        (item.main_id, item.buffer_code, item.order_code, item.current_quantity)
        for item in inventories
    ] == [
        ("MAIN-001", "BUF-001", "ORD-001", 1200),
        ("MAIN-001", "BUF-001", "ORD-002", 800),
        ("MAIN-001", "BUF-002", "ORD-001", 100),
    ]


def test_snapshot_adapter_preserves_main_id_on_each_physical_inventory():
    inventories = _convert().buffer_order_inventories

    assert [item.main_id for item in inventories] == [
        "MAIN-001",
        "MAIN-001",
        "MAIN-001",
    ]


def test_same_buffer_can_contain_multiple_orders():
    assert [
        item.order_code
        for item in _convert().buffer_order_inventories
        if item.buffer_code == "BUF-001"
    ] == ["ORD-001", "ORD-002"]


def test_same_order_can_exist_in_multiple_buffers():
    assert [
        item.buffer_code
        for item in _convert().buffer_order_inventories
        if item.order_code == "ORD-001"
    ] == ["BUF-001", "BUF-002"]


def test_same_order_name_is_matched_within_buffer_workshop():
    payload = _payload()
    payload["orders"].append({**deepcopy(payload["orders"][0]), "order_code": "ORD-S2", "workshop_code": "S2", "workshop_name": "二车间"})
    payload["process_routes"].extend([
        {**deepcopy(payload["process_routes"][0]), "workshop_code": "S2", "workshop_name": "二车间", "loop_code": "LOOP-2"},
        {**deepcopy(payload["process_routes"][1]), "workshop_code": "S2", "workshop_name": "二车间", "loop_code": "LOOP-2"},
    ])
    payload["buffer_master"].append({
        **deepcopy(payload["buffer_master"][0]),
        "buffer_code": "BUF-S2",
        "loop_code": "LOOP-2",
    })
    payload["buffer_realtime"].append({
        "main_id": "MAIN-S2",
        "buffer_code": "BUF-S2",
        "bound_source_name": "至上",
        "current_quantity": 10,
        "current_utilization_rate": 0.01,
    })

    inventory = _convert(payload).buffer_order_inventories[-1]
    assert inventory.order_code == "ORD-S2"


def test_duplicate_order_name_in_same_workshop_fails_inventory_match():
    payload = _payload()
    payload["orders"].append({**deepcopy(payload["orders"][0]), "order_code": "ORD-003"})

    _assert_conversion_error(payload, "BUF-001.*至上.*multiple")


def test_missing_buffer_order_name_match_fails():
    payload = _payload()
    payload["buffer_realtime"][0]["bound_source_name"] = "不存在"

    _assert_conversion_error(payload, "BUF-001.*不存在")


def test_blank_buffer_bound_source_name_fails():
    payload = _payload()
    payload["buffer_realtime"][0]["bound_source_name"] = "   "

    _assert_conversion_error(payload, "BUF-001.*name")


def test_duplicate_buffer_order_inventory_fails():
    payload = _payload()
    payload["buffer_realtime"].append(deepcopy(payload["buffer_realtime"][0]))

    _assert_conversion_error(
        payload,
        "MAIN-001.*BUF-001.*ORD-001.*duplicate",
    )


@pytest.mark.parametrize("main_id", [None, "", "   "])
def test_buffer_main_id_must_not_be_null_or_blank(main_id):
    payload = _payload()
    payload["buffer_realtime"][0]["main_id"] = main_id

    _assert_conversion_error(payload, "BUF-001.*main_id.*blank")


def test_one_physical_buffer_cannot_belong_to_different_main_ids():
    payload = _payload()
    payload["buffer_realtime"][1]["main_id"] = "MAIN-OTHER"

    _assert_conversion_error(
        payload,
        "BUF-001.*MAIN-001.*MAIN-OTHER.*ORD-002",
    )


def test_same_main_different_buffers_same_order_is_not_duplicate():
    inventories = [
        item
        for item in _convert().buffer_order_inventories
        if item.order_code == "ORD-001"
    ]

    assert [(item.main_id, item.buffer_code) for item in inventories] == [
        ("MAIN-001", "BUF-001"),
        ("MAIN-001", "BUF-002"),
    ]


def test_same_main_with_different_workshops_fails_with_both_contexts():
    payload = _payload()
    _copy_process_pair_to_context(
        payload,
        workshop_code="S2",
        loop_code="LOOP-2",
    )
    payload["buffer_master"][1]["loop_code"] = "LOOP-2"

    _assert_conversion_error(
        payload,
        "MAIN-001.*workshop_code.*BUF-001.*S1.*BUF-002.*S2",
    )


def test_same_main_with_different_upstream_processes_fails():
    payload = _payload()
    payload["process_routes"][0]["sequence"] = 2
    payload["process_routes"][1]["sequence"] = 3
    _append_process_route(
        payload,
        process_code="PROC-00",
        sequence=1,
    )
    payload["buffer_master"][1]["served_process_codes"] = [
        "PROC-00",
        "PROC-01",
    ]
    payload["buffer_master"][1]["served_process_names"] = [
        "PROC-00",
        "PROC-01",
    ]

    _assert_conversion_error(
        payload,
        "MAIN-001.*upstream_process_code.*BUF-001.*PROC-01.*BUF-002.*PROC-00",
    )


def test_same_main_with_different_downstream_processes_fails():
    payload = _payload()
    _append_process_route(
        payload,
        process_code="PROC-03",
        sequence=2,
    )
    payload["buffer_master"][1]["served_process_codes"] = [
        "PROC-01",
        "PROC-03",
    ]
    payload["buffer_master"][1]["served_process_names"] = [
        "PROC-01",
        "PROC-03",
    ]

    _assert_conversion_error(
        payload,
        "MAIN-001.*downstream_process_code.*BUF-001.*PROC-02.*BUF-002.*PROC-03",
    )


def test_same_main_with_different_loop_codes_fails():
    payload = _payload()
    _copy_process_pair_to_context(
        payload,
        workshop_code="S1",
        loop_code="LOOP-2",
    )
    payload["buffer_master"][1]["loop_code"] = "LOOP-2"

    _assert_conversion_error(
        payload,
        "MAIN-001.*loop_code.*BUF-001.*LOOP-1.*BUF-002.*LOOP-2",
    )


def test_buffer_served_code_and_name_lengths_must_match():
    payload = _payload()
    payload["buffer_master"][0]["served_process_names"] = ["工序一"]

    _assert_conversion_error(payload, "BUF-001.*length")


def test_buffer_must_serve_exactly_two_processes():
    payload = _payload()
    payload["buffer_master"][0]["served_process_codes"] = ["PROC-01"]
    payload["buffer_master"][0]["served_process_names"] = ["工序一"]

    _assert_conversion_error(payload, "BUF-001.*exactly two")


def test_buffer_process_route_must_exist():
    payload = _payload()
    payload["buffer_master"][0]["served_process_codes"][1] = "UNKNOWN"

    _assert_conversion_error(payload, "BUF-001.*UNKNOWN")


def test_buffer_processes_must_be_in_same_workshop():
    payload = _payload()
    payload["process_routes"][1]["workshop_code"] = "S2"
    payload["process_routes"][1]["workshop_name"] = "二车间"

    _assert_conversion_error(payload, "BUF-001.*workshop")


def test_buffer_processes_must_be_in_buffer_loop():
    payload = _payload()
    payload["process_routes"][1]["loop_code"] = "OTHER-LOOP"

    _assert_conversion_error(payload, "BUF-001.*LOOP-1")


def test_buffer_upstream_sequence_must_precede_downstream():
    payload = _payload()
    payload["process_routes"][0]["sequence"] = 2
    payload["process_routes"][1]["sequence"] = 1

    _assert_conversion_error(payload, "BUF-001.*sequence")


def test_buffer_consecutive_process_sequences_convert_relation():
    relation = _convert().buffer_process_relations[0]

    assert relation.upstream_process_code == "PROC-01"
    assert relation.downstream_process_code == "PROC-02"


def test_buffer_processes_must_be_adjacent():
    payload = _payload()
    payload["process_routes"][1]["sequence"] = 3

    _assert_conversion_error(payload, "BUF-001.*adjacent")


def test_buffer_inventory_over_capacity_still_converts():
    payload = _payload()
    payload["buffer_realtime"][1]["current_quantity"] = 801

    snapshot = _convert(payload)

    assert isinstance(snapshot, AlgorithmSnapshot)


def test_buffer_inventory_over_capacity_preserves_original_quantities():
    payload = _payload()
    payload["buffer_realtime"][1]["current_quantity"] = 801

    inventories = [
        inventory
        for inventory in _convert(payload).buffer_order_inventories
        if inventory.buffer_code == "BUF-001"
    ]

    assert [inventory.current_quantity for inventory in inventories] == [1200, 801]
    assert sum(inventory.current_quantity for inventory in inventories) == 2001


def test_buffer_realtime_transport_fields_are_excluded():
    inventory_fields = set(_convert().buffer_order_inventories[0].model_dump())

    assert "main_id" in inventory_fields
    assert "current_utilization_rate" not in inventory_fields


def test_selected_agv_relation_is_converted_to_internal_binding():
    relation = _convert().agv_relations[0]

    assert relation.model_dump() == {
        "machine_code": "MC-001",
        "machine_name": "机台一",
        "order_code": "ORD-001",
        "order_name": "至上",
        "binding_time": datetime(
            2026,
            7,
            15,
            16,
            0,
            tzinfo=timezone(timedelta(hours=8)),
        ),
    }


def test_latest_effective_agv_record_wins_regardless_of_input_order():
    payload = _payload()
    payload["agv_relations"] = [
        {
            "machine_code": "MC-001",
            "machine_name": "机台一",
            "order_code": "ORD-002",
            "order_name": "华晟",
            "binding_time": "2026-07-15T16:20:00+08:00",
        },
        {
            "machine_code": "MC-001",
            "machine_name": "机台一",
            "order_code": "ORD-001",
            "order_name": "至上",
            "binding_time": "2026-07-15T16:10:00+08:00",
        },
    ]

    snapshot = _convert(payload)

    assert snapshot.machine_runtimes[0].current_order_code == "ORD-002"
    assert snapshot.agv_relations[0].order_code == "ORD-002"


def test_future_agv_record_does_not_participate():
    payload = _payload()
    payload["agv_relations"].insert(
        0,
        {
            "machine_code": "MC-001",
            "machine_name": "机台一",
            "order_code": "ORD-002",
            "order_name": "华晟",
            "binding_time": "2026-07-15T16:40:00+08:00",
        },
    )

    snapshot = _convert(payload)

    assert snapshot.machine_runtimes[0].current_order_code == "ORD-001"
    assert [relation.order_code for relation in snapshot.agv_relations] == [
        "ORD-001"
    ]


def test_exact_latest_agv_duplicates_are_deduplicated():
    payload = _payload()
    payload["agv_relations"].append(deepcopy(payload["agv_relations"][0]))

    snapshot = _convert(payload)

    assert len(snapshot.agv_relations) == 1
    assert snapshot.machine_runtimes[0].current_order_code == "ORD-001"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("order_code", "ORD-002"),
        ("order_name", "华晟"),
    ],
)
def test_latest_agv_order_identity_conflict_fails(field, value):
    payload = _payload()
    conflicting = deepcopy(payload["agv_relations"][0])
    conflicting[field] = value
    payload["agv_relations"].append(conflicting)

    _assert_conversion_error(payload, f"MC-001.*latest.*{field}.*conflict")


def test_naive_binding_time_is_interpreted_as_utc_plus_eight():
    payload = _payload()
    payload["agv_relations"][0]["binding_time"] = "2026-07-15 16:20:00"

    relation = _convert(payload).agv_relations[0]

    assert relation.binding_time.utcoffset() == timedelta(hours=8)


def test_future_unknown_agv_references_are_not_validated():
    payload = _payload()
    payload["agv_relations"].append(
        {
            "machine_code": "UNKNOWN-MACHINE",
            "machine_name": "未知机台",
            "order_code": "UNKNOWN-ORDER",
            "order_name": "未知订单",
            "binding_time": "2026-07-15T16:40:00+08:00",
        }
    )

    assert _convert(payload).machine_runtimes[0].current_order_code == "ORD-001"


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("machine_code", "UNKNOWN", "UNKNOWN.*machine"),
        ("machine_name", "错误机台名", "MC-001.*machine_name.*错误机台名.*机台一"),
        ("order_code", "UNKNOWN", "UNKNOWN.*order"),
        ("order_name", "错误订单名", "ORD-001.*order_name.*错误订单名.*至上"),
    ],
)
def test_selected_agv_binding_references_and_names_must_match(
    field,
    value,
    match,
):
    payload = _payload()
    payload["agv_relations"][0][field] = value

    _assert_conversion_error(payload, match)


def test_active_events_and_config_use_algorithm_defaults():
    snapshot = _convert()

    assert snapshot.active_cutline_events == []
    assert snapshot.config.schedule_interval_minutes == 5


def test_machine_runtime_requires_known_machine():
    payload = _payload()
    payload["machine_realtime"][0]["machine_code"] = "UNKNOWN"

    _assert_conversion_error(payload, "UNKNOWN.*machine")


def test_running_machine_without_effective_agv_binding_fails():
    payload = _payload()
    payload["agv_relations"] = []

    _assert_conversion_error(payload, "MC-001.*running.*AGV")


def test_stopped_machine_without_agv_binding_has_no_current_order():
    payload = _payload()
    payload["machine_realtime"][0]["status"] = "停机"
    payload["agv_relations"] = []

    runtime = _convert(payload).machine_runtimes[0]

    assert runtime.status == "stopped"
    assert runtime.current_order_code is None


def test_stopped_machine_with_effective_agv_binding_keeps_current_order():
    payload = _payload()
    payload["machine_realtime"][0]["status"] = "异常"

    runtime = _convert(payload).machine_runtimes[0]

    assert runtime.status == "stopped"
    assert runtime.current_order_code == "ORD-001"


def test_snapshot_adapter_does_not_mutate_request():
    request = CutlineAlgorithmRequest.model_validate(_payload())
    before = request.model_dump()

    snapshot_adapter_module.SnapshotAdapter().to_algorithm_snapshot(request)

    assert request.model_dump() == before


def test_machine_line_requires_known_machine_and_line():
    payload = _payload()
    payload["machine_lines"][0]["line_code"] = "UNKNOWN"

    _assert_conversion_error(payload, "UNKNOWN.*line")


def test_duplicate_machine_line_relation_fails():
    payload = _payload()
    payload["machine_lines"].append(deepcopy(payload["machine_lines"][0]))

    _assert_conversion_error(
        payload,
        "Duplicate machine-line relation: MC-001 -> LINE-001",
    )


def test_machine_cannot_bind_multiple_different_lines():
    payload = _payload()
    payload["lines"].append({**deepcopy(payload["lines"][0]), "line_code": "LINE-002"})
    payload["machine_lines"].append({**deepcopy(payload["machine_lines"][0]), "line_code": "LINE-002"})

    _assert_conversion_error(payload, "MC-001.*multiple.*line")


def test_duplicate_machine_runtime_fails():
    payload = _payload()
    payload["machine_realtime"].append(deepcopy(payload["machine_realtime"][0]))

    _assert_conversion_error(payload, "Duplicate machine runtime: MC-001")


def test_runtime_machine_without_machine_line_relation_fails():
    payload = _payload()
    payload["machine_lines"] = []

    _assert_conversion_error(
        payload,
        "Machine MC-001 has no machine-line relation",
    )


def test_runtime_machine_with_machine_line_relation_converts():
    snapshot = _convert()

    assert snapshot.machine_runtimes[0].machine_code == "MC-001"
    assert snapshot.machine_lines[0].machine_code == "MC-001"


def test_machine_product_capacity_requires_known_references():
    payload = _payload()
    payload["machine_process_times"][0]["product_code"] = "UNKNOWN"

    _assert_conversion_error(payload, "UNKNOWN.*product")


def test_duplicate_machine_product_capacity_fails():
    payload = _payload()
    payload["machine_process_times"].append(deepcopy(payload["machine_process_times"][0]))

    _assert_conversion_error(payload, "MC-001.*PROD-001.*duplicate")


def test_order_requires_known_product_and_workshop():
    payload = _payload()
    payload["orders"][0]["workshop_code"] = "UNKNOWN"

    _assert_conversion_error(payload, "UNKNOWN.*workshop")


def test_duplicate_order_code_fails():
    payload = _payload()
    payload["orders"].append(deepcopy(payload["orders"][0]))

    _assert_conversion_error(payload, "ORD-001.*duplicate")


def test_process_route_requires_known_workshop_and_unique_key():
    payload = _payload()
    payload["process_routes"].append(deepcopy(payload["process_routes"][0]))

    _assert_conversion_error(payload, "S1.*LOOP-1.*PROC-01.*duplicate")


def test_process_route_sequence_must_start_at_one():
    payload = _payload()
    payload["process_routes"][0]["sequence"] = 0

    _assert_conversion_error(payload, "PROC-01.*sequence")


def test_duplicate_master_codes_fail():
    payload = _payload()
    payload["machine_master"].append(deepcopy(payload["machine_master"][0]))

    _assert_conversion_error(payload, "MC-001.*duplicate")


def _active_cutline_event(**overrides) -> dict:
    event = {
        "event_id": "EVENT-001",
        "machine_code": "MC-001",
        "source_order_code": "ORD-001",
        "target_order_code": "ORD-002",
        "workshop_code": "S1",
        "target_buffer_code": "BUF-002",
        "upstream_process_code": "PROC-01",
        "downstream_process_code": "PROC-02",
        "target_wafer_size": "182",
        "target_wafer_spec": "N",
        "cutline_start_time": "2026-07-15T08:00:00Z",
        "negative_start_time": "2026-07-15T08:10:00Z",
    }
    event.update(overrides)
    return event


def test_active_cutline_event_is_deep_copied_without_mutating_request():
    payload = _payload()
    payload["active_cutline_events"] = [_active_cutline_event()]
    request = CutlineAlgorithmRequest.model_validate(payload)
    request_event_before = request.active_cutline_events[0].model_dump()

    snapshot = snapshot_adapter_module.SnapshotAdapter().to_algorithm_snapshot(request)

    assert request.active_cutline_events[0].model_dump() == request_event_before
    internal_event = snapshot.active_cutline_events[0]
    assert internal_event.event_id == request.active_cutline_events[0].event_id
    assert internal_event.machine_code == request.active_cutline_events[0].machine_code
    assert internal_event.negative_start_time == (
        request.active_cutline_events[0].negative_start_time
    )
    assert internal_event.status == "active"
    assert internal_event.plan_id is None
    assert internal_event.source_buffer_code is None
    assert internal_event.source_wafer_size is None
    assert internal_event.source_wafer_spec is None
    assert internal_event.contribution_capacity is None
    assert internal_event.warning_type is None
    assert internal_event is not request.active_cutline_events[0]
    assert snapshot.config.cutline_execution_delay_minutes == 0


def test_active_cutline_event_ids_must_be_unique_within_request():
    payload = _payload()
    payload["active_cutline_events"] = [
        _active_cutline_event(),
        _active_cutline_event(),
    ]

    _assert_conversion_error(payload, "EVENT-001.*event_id.*duplicate")


@pytest.mark.parametrize(
    ("field", "missing_code", "reason"),
    [
        ("machine_code", "MISSING-MACHINE", "machine"),
        ("source_order_code", "MISSING-SOURCE-ORDER", "order"),
        ("target_order_code", "MISSING-TARGET-ORDER", "order"),
        ("workshop_code", "MISSING-WORKSHOP", "workshop"),
        ("target_buffer_code", "MISSING-TARGET-BUFFER", "buffer"),
        ("upstream_process_code", "MISSING-UPSTREAM", "process route"),
        ("downstream_process_code", "MISSING-DOWNSTREAM", "process route"),
    ],
)
def test_active_cutline_event_references_must_exist(
    field, missing_code, reason
):
    payload = _payload()
    payload["active_cutline_events"] = [
        _active_cutline_event(**{field: missing_code})
    ]

    _assert_conversion_error(
        payload,
        f"EVENT-001.*{field}.*{missing_code}.*{reason}",
    )


@pytest.mark.parametrize(
    "field",
    ["upstream_process_code", "downstream_process_code"],
)
def test_active_cutline_event_process_routes_must_belong_to_event_workshop(field):
    payload = _payload()
    valid_other_route_index = 1 if field == "upstream_process_code" else 0
    payload["process_routes"].append(
        {
            **deepcopy(payload["process_routes"][valid_other_route_index]),
            "workshop_code": "S2",
            "workshop_name": payload["workshops"][1]["workshop_name"],
            "loop_code": "LOOP-S2",
        }
    )
    payload["active_cutline_events"] = [
        _active_cutline_event(workshop_code="S2")
    ]

    _assert_conversion_error(
        payload,
        f"EVENT-001.*{field}.*S2.*process route",
    )


@pytest.mark.parametrize(
    "field",
    ["negative_start_time", "cutline_start_time"],
)
def test_active_cutline_event_times_cannot_be_later_than_snapshot_time(field):
    payload = _payload()
    payload["active_cutline_events"] = [
        _active_cutline_event(**{field: "2026-07-15T08:30:01Z"})
    ]

    _assert_conversion_error(
        payload,
        f"EVENT-001.*{field}.*snapshot_time",
    )


def test_active_cutline_event_time_awareness_mismatch_is_a_conversion_error():
    payload = _payload()
    payload["active_cutline_events"] = [
        _active_cutline_event(cutline_start_time="2026-07-15T08:30:01")
    ]

    _assert_conversion_error(
        payload,
        "EVENT-001.*cutline_start_time.*snapshot_time.*timezone",
    )
