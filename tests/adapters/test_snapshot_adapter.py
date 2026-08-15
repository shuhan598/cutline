from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

import app.adapters.snapshot_adapter as snapshot_adapter_module
from app.core.buffer_aggregation.main_buffer_aggregator import (
    MainBufferAggregator,
)
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
                "machine_code": "P166-MC-001",
                "status": "RUNNING",
                "tangent_time": "2026-07-15T07:30:00Z",
                "input_quantity": 11,
                "output_quantity": 12,
                "out_time": "2026-07-15T08:20:00Z",
            }
        ],
        "machine_master": [
            {
                "machine_code": "MC-001",
                "p166_jt_group": "P166-MC-001",
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
                "order_status": "OPEN",
                "total_quantity": 5000,
                "piece_source": "B",
                "estimated_yield": "98.5%",
                "product_code": "PROD-002",
                "product_name": "产品二",
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
            },
            {
                "product_code": "PROD-002",
                "product_name": "产品二",
                "wafer_size": "210",
                "source_grade": "B",
                "material_code": "MAT-002",
                "material_name": "物料二",
            },
        ],
        "process_routes": [
            {
                "process_code": "PROC-01",
                "process_name": "制绒",
                "sequence": 1,
                "cache_type": "BUFFER",
                "workshop_code": "S1",
                "workshop_name": "一车间",
                "loop_code": "LOOP2",
                "loop_name": "二循环",
                "upstream_process_code": None,
                "upstream_process_name": None,
                "downstream_process_code": "PROC-02",
                "downstream_process_name": "氧化",
            },
            {
                "process_code": "PROC-02",
                "process_name": "氧化",
                "sequence": 2,
                "cache_type": "BUFFER",
                "workshop_code": "S1",
                "workshop_name": "一车间",
                "loop_code": "LOOP2",
                "loop_name": "二循环",
                "upstream_process_code": "PROC-01",
                "upstream_process_name": "制绒",
                "downstream_process_code": None,
                "downstream_process_name": None,
            },
        ],
        "buffer_realtime": [
            {
                "main_id": "MAIN-001",
                "buffer_code": "BUF-001",
                "bound_source_name": "产品一",
                "current_quantity": 1200,
                "current_utilization_rate": 0.6,
            },
            {
                "main_id": "MAIN-001",
                "buffer_code": "BUF-001",
                "bound_source_name": "产品二",
                "current_quantity": 800,
                "current_utilization_rate": 0.4,
            },
            {
                "main_id": "MAIN-001",
                "buffer_code": "BUF-002",
                "bound_source_name": "产品一",
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
                "served_process_names": ["制绒", "氧化"],
                "loop_code": "LOOP2",
                "loop_name": "二循环",
            },
            {
                "buffer_code": "BUF-002",
                "buffer_name": "缓存二",
                "buffer_type": "LINE",
                "buffer_type_title": "线边库",
                "max_capacity": 500,
                "safety_low": 50,
                "served_process_codes": ["PROC-01", "PROC-02"],
                "served_process_names": ["制绒", "氧化"],
                "loop_code": "LOOP2",
                "loop_name": "二循环",
            },
        ],
        "agv_relations": [
            {
                "machine_code": "MC-001",
                "machine_name": "机台一",
                "product_name": "产品一",
                "previous_product_name": "产品二",
                "wafer_spec": "N",
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


def _assert_aggregation_issue(payload: dict, code: str):
    snapshot = _convert(payload)
    matching = [
        issue for issue in snapshot.main_buffer_batch.issues if issue.code == code
    ]
    assert matching
    return snapshot, matching


def test_snapshot_adapter_builds_main_buffer_batch_exactly_once(monkeypatch):
    calls = []
    original = MainBufferAggregator.aggregate

    def counting_aggregate(self, **kwargs):
        calls.append(kwargs)
        return original(self, **kwargs)

    monkeypatch.setattr(MainBufferAggregator, "aggregate", counting_aggregate)

    snapshot = _convert()

    assert len(calls) == 1
    assert snapshot.main_buffer_batch.groups_by_group_key
    assert snapshot.main_buffer_batch.issues
    assert any(
        issue.code == "multiple_orders_in_main"
        for issue in snapshot.main_buffer_batch.issues
    )


def _append_process_route(
    payload: dict,
    *,
    process_code: str,
    sequence: int,
    process_name: str = "退火",
    workshop_code: str = "S1",
    loop_code: str = "LOOP-1",
) -> None:
    payload["process_routes"].append(
        {
            **deepcopy(payload["process_routes"][0]),
            "process_code": process_code,
            "process_name": process_name,
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
    process_prefix: str = "",
) -> list[str]:
    source_routes = payload["process_routes"][:2]
    code_by_source = {
        route["process_code"]: f"{process_prefix}{route['process_code']}"
        for route in source_routes
    }
    copied_routes = []
    for route in source_routes:
        copied = {
            **deepcopy(route),
            "process_code": code_by_source[route["process_code"]],
            "workshop_code": workshop_code,
            "workshop_name": (
                "一车间" if workshop_code == "S1" else "二车间"
            ),
            "loop_code": loop_code,
            "loop_name": loop_code,
        }
        for field in (
            "upstream_process_code",
            "downstream_process_code",
        ):
            if copied[field] is not None:
                copied[field] = code_by_source[copied[field]]
        copied_routes.append(copied)
    payload["process_routes"].extend(copied_routes)
    return [route["process_code"] for route in copied_routes]


def test_minimal_complete_request_converts_to_algorithm_snapshot():
    snapshot = _convert()

    assert isinstance(snapshot, AlgorithmSnapshot)
    assert len(snapshot.workshops) == 2
    assert len(snapshot.buffer_order_inventories) == 3


@pytest.mark.parametrize(
    ("process_name", "expected_loop_code", "expected_loop_name"),
    [
        ("发料机", "LOOP1", "一循环"),
        ("制绒", "LOOP2", "二循环"),
        ("硼扩", "LOOP2", "二循环"),
        ("氧化", "LOOP2", "二循环"),
        ("碱抛", "LOOP3", "三循环"),
        ("POLY", "LOOP3", "三循环"),
        ("退火", "LOOP3", "三循环"),
        ("RCA", "LOOP4", "四循环"),
        ("ALD", "LOOP5", "五循环"),
        ("正膜", "LOOP5", "五循环"),
        ("背膜", "LOOP5", "五循环"),
        ("丝网", "LOOP5", "五循环"),
    ],
)
def test_snapshot_derives_all_process_route_loops_from_process_names(
    process_name,
    expected_loop_code,
    expected_loop_name,
):
    payload = _payload()
    process_code = f"CATALOG-{process_name}"
    _append_process_route(
        payload,
        process_code=process_code,
        process_name=process_name,
        sequence=100,
        loop_code="LEGACY-WRONG-LOOP",
    )

    route = next(
        route
        for route in _convert(payload).process_routes
        if route.process_code == process_code
    )

    assert route.process_code == process_code
    assert route.process_name == process_name
    assert route.loop_code == expected_loop_code
    assert route.loop_name == expected_loop_name


def test_snapshot_allows_omitted_external_route_loop_fields():
    payload = _payload()
    for route in payload["process_routes"]:
        route.pop("loop_code")
        route.pop("loop_name")

    routes = _convert(payload).process_routes

    assert [(route.loop_code, route.loop_name) for route in routes] == [
        ("LOOP2", "二循环"),
        ("LOOP2", "二循环"),
    ]


def test_snapshot_preserves_nonconsecutive_backend_sequences():
    payload = _payload()
    payload["process_routes"][0]["sequence"] = 100
    payload["process_routes"][1]["sequence"] = 200
    _append_process_route(
        payload,
        process_code="PROC-03",
        sequence=300,
        process_name="退火",
        loop_code="LOOP3",
    )

    sequence_by_code = {
        route.process_code: route.sequence
        for route in _convert(payload).process_routes
    }

    assert sequence_by_code == {
        "PROC-01": 100,
        "PROC-02": 200,
        "PROC-03": 300,
    }


def test_snapshot_reports_process_code_raw_name_and_reason_for_unknown_name():
    payload = _payload()
    payload["process_routes"][0]["process_name"] = " 未知工序 "

    with pytest.raises(
        snapshot_adapter_module.SnapshotConversionError
    ) as exc_info:
        _convert(payload)

    message = str(exc_info.value)
    assert "PROC-01" in message
    assert " 未知工序 " in message
    assert "cannot be mapped to an internal loop" in message


def test_snapshot_rejects_duplicate_process_code_in_same_workshop_even_with_different_external_loops():
    payload = _payload()
    _append_process_route(
        payload,
        process_code="PROC-01",
        process_name="退火",
        sequence=3,
        loop_code="LEGACY-LOOP3",
    )

    _assert_conversion_error(
        payload,
        r"S1.*PROC-01.*duplicate process route",
    )


def test_snapshot_allows_same_process_code_in_different_workshops():
    payload = _payload()
    _append_process_route(
        payload,
        process_code="SHARED-PROCESS",
        sequence=3,
        workshop_code="S1",
    )
    _append_process_route(
        payload,
        process_code="SHARED-PROCESS",
        sequence=3,
        workshop_code="S2",
    )

    shared_routes = [
        route
        for route in _convert(payload).process_routes
        if route.process_code == "SHARED-PROCESS"
    ]

    assert {route.workshop_code for route in shared_routes} == {"S1", "S2"}


def test_snapshot_time_is_used_as_current_time():
    snapshot = _convert()

    assert snapshot.current_time == datetime(2026, 7, 15, 8, 30, tzinfo=timezone.utc)


def test_machine_runtime_current_order_code_comes_from_agv_binding():
    assert _convert().machine_runtimes[0].current_order_code == "ORD-001"


def test_realtime_machine_code_is_normalized_to_static_standard_code():
    snapshot = _convert()

    assert snapshot.machine_runtimes[0].machine_code == "MC-001"
    assert snapshot.agv_relations[0].machine_code == "MC-001"
    assert snapshot.machine_masters[0].machine_code == "MC-001"
    assert "P166-MC-001" not in snapshot.model_dump_json()


def test_unknown_realtime_p166_code_fails_with_mapping_field():
    payload = _payload()
    payload["machine_realtime"][0]["machine_code"] = "P166-UNKNOWN"

    _assert_conversion_error(
        payload,
        r"machine_realtime\.machine_code.*P166-UNKNOWN.*p166_jt_group",
    )


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


def test_runtime_machine_process_must_have_a_process_route():
    payload = _payload()
    payload["machine_master"][0]["process_code"] = "UNKNOWN"
    payload["machine_master"][0]["process_name"] = "未知工序"

    _assert_conversion_error(
        payload,
        r"Machine MC-001 process UNKNOWN has no process route",
    )


def test_runtime_machine_process_cannot_belong_to_multiple_workshops():
    payload = _payload()
    _append_process_route(
        payload,
        process_code="PROC-01",
        sequence=1,
        workshop_code="S2",
        loop_code="LOOP-2",
    )

    _assert_conversion_error(
        payload,
        (
            r"Machine MC-001 process PROC-01 belongs to multiple "
            r"workshops: S1, S2"
        ),
    )


def test_runtime_machine_process_cannot_repeat_in_same_workshop_across_loops():
    payload = _payload()
    _append_process_route(
        payload,
        process_code="PROC-01",
        sequence=1,
        workshop_code="S1",
        loop_code="LOOP-2",
    )

    _assert_conversion_error(
        payload,
        r"S1.*PROC-01.*duplicate process route",
    )


def test_unused_static_machine_does_not_require_route_in_current_snapshot():
    payload = _payload()
    payload["machine_master"].append(
        {
            "machine_code": "MC-UNUSED",
            "p166_jt_group": "P166-MC-UNUSED",
            "machine_name": "未参与机台",
            "process_code": "UNUSED-PROCESS",
            "process_name": "未参与工序",
        }
    )

    snapshot = _convert(payload)

    assert {item.machine_code for item in snapshot.machine_masters} == {
        "MC-001",
        "MC-UNUSED",
    }


def test_machine_runtime_quantities_are_raw_30_minute_values():
    runtime = _convert().machine_runtimes[0]

    assert runtime.input_quantity_30m == 11
    assert runtime.output_quantity_30m == 12


def test_machine_runtime_only_contains_sourced_quantity_fields():
    runtime = _convert().machine_runtimes[0]

    fields = type(runtime).model_fields
    assert {"input_quantity_30m", "output_quantity_30m"} <= fields.keys()
    assert "period_quantity_30m" not in fields


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


def test_order_product_name_must_match_product_catalog():
    payload = _payload()
    payload["orders"][0]["product_name"] = "错误产品名"

    _assert_conversion_error(
        payload,
        "ORD-001.*PROD-001.*产品一.*错误产品名",
    )


def test_blank_product_code_fails_before_order_lookup():
    payload = _payload()
    payload["products"][0]["product_code"] = "   "

    _assert_conversion_error(
        payload,
        r"products\.product_code.*blank.*index 0",
    )


def test_duplicate_product_code_fails_without_overwriting_first_product():
    payload = _payload()
    duplicate = deepcopy(payload["products"][0])
    duplicate["product_name"] = "另一产品"
    payload["products"].append(duplicate)

    _assert_conversion_error(
        payload,
        r"products\.product_code duplicate.*PROD-001",
    )


def test_blank_product_name_fails_before_product_name_lookup():
    payload = _payload()
    payload["products"][0]["product_name"] = "   "

    _assert_conversion_error(
        payload,
        r"products\.product_name.*blank.*PROD-001",
    )


def test_duplicate_product_name_fails_without_overwriting_first_product():
    payload = _payload()
    duplicate = deepcopy(payload["products"][0])
    duplicate["product_code"] = "PROD-003"
    payload["products"].append(duplicate)

    _assert_conversion_error(
        payload,
        r"products\.product_name duplicate.*产品一.*PROD-001.*PROD-003",
    )


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


def test_product_name_cannot_map_to_multiple_current_orders_across_workshops():
    payload = _payload()
    payload["orders"].append(
        {
            **deepcopy(payload["orders"][0]),
            "order_code": "ORD-S2",
            "workshop_code": "S2",
            "workshop_name": "二车间",
        }
    )

    _assert_conversion_error(payload, "产品一.*multiple current orders")


def test_duplicate_product_name_current_orders_fail_before_inventory_match():
    payload = _payload()
    payload["orders"].append({**deepcopy(payload["orders"][0]), "order_code": "ORD-003"})

    _assert_conversion_error(payload, "产品一.*multiple current orders")


def test_missing_buffer_product_name_match_is_isolated():
    payload = _payload()
    payload["buffer_realtime"][0]["bound_source_name"] = "不存在"

    _, issues = _assert_aggregation_issue(payload, "order_mapping_unresolved")
    assert "不存在" in issues[0].message


def test_blank_buffer_bound_source_name_is_isolated():
    payload = _payload()
    payload["buffer_realtime"][0]["bound_source_name"] = "   "

    _assert_aggregation_issue(payload, "order_mapping_unresolved")


def test_buffer_product_order_workshop_conflict_is_isolated():
    payload = _payload()
    payload["orders"][0]["workshop_code"] = "S2"
    payload["orders"][0]["workshop_name"] = "二车间"
    payload["agv_relations"][0]["product_name"] = "产品二"
    payload["agv_relations"][0]["previous_product_name"] = "产品一"

    _assert_aggregation_issue(payload, "workshop_conflict")


def test_duplicate_buffer_order_inventory_is_isolated_without_double_counting():
    payload = _payload()
    payload["buffer_realtime"].append(deepcopy(payload["buffer_realtime"][0]))

    snapshot, issues = _assert_aggregation_issue(payload, "duplicate_buffer_id")
    assert len(issues) == 1
    assert sum(
        item.current_quantity
        for item in snapshot.buffer_order_inventories
        if item.order_code == "ORD-001" and item.buffer_code == "BUF-001"
    ) == 1200


@pytest.mark.parametrize("main_id", [None, "", "   "])
def test_buffer_main_id_null_or_blank_is_isolated(main_id):
    payload = _payload()
    payload["buffer_realtime"][0]["main_id"] = main_id

    _assert_aggregation_issue(payload, "main_id_unavailable")


def test_one_real_buffer_mapped_to_different_main_ids_is_isolated():
    payload = _payload()
    payload["buffer_realtime"][1]["main_id"] = "MAIN-OTHER"

    snapshot, issues = _assert_aggregation_issue(
        payload,
        "buffer_code_index_conflict",
    )
    assert {issue.main_id for issue in issues} == {"MAIN-001", "MAIN-OTHER"}
    assert "BUF-001" not in snapshot.main_buffer_batch.group_key_by_buffer_code


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


def test_same_main_with_different_workshops_is_isolated():
    payload = _payload()
    s2_process_codes = _copy_process_pair_to_context(
        payload,
        workshop_code="S2",
        loop_code="LOOP-2",
        process_prefix="S2-",
    )
    payload["buffer_master"][1]["loop_code"] = "LOOP2"
    payload["buffer_master"][1]["served_process_codes"] = s2_process_codes
    payload["buffer_master"][1]["served_process_names"] = s2_process_codes

    _, issues = _assert_aggregation_issue(payload, "workshop_conflict")
    assert "S1" in issues[0].message
    assert "S2" in issues[0].message


def test_same_main_with_different_upstream_processes_is_isolated():
    payload = _payload()
    payload["process_routes"][0]["sequence"] = 2
    payload["process_routes"][1]["sequence"] = 3
    _append_process_route(
        payload,
        process_code="PROC-00",
        process_name="硼扩",
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

    _assert_aggregation_issue(payload, "service_process_conflict")


def test_same_main_with_different_downstream_processes_is_isolated():
    payload = _payload()
    _append_process_route(
        payload,
        process_code="PROC-03",
        process_name="硼扩",
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

    _assert_aggregation_issue(payload, "service_process_conflict")


def test_wrong_external_route_loop_keeps_physical_key_definition():
    payload = _payload()
    payload["process_routes"][0]["loop_code"] = "LEGACY-WRONG-LOOP"
    payload["process_routes"][0]["loop_name"] = "旧循环"

    snapshot = _convert(payload)
    group = next(iter(snapshot.main_buffer_batch.groups_by_group_key.values()))
    assert group.physical_buffer_key.workshop_code == "S1"
    assert group.physical_buffer_key.ordered_service_process_codes == (
        "PROC-01",
        "PROC-02",
    )
    assert not any(
        issue.code == "service_process_conflict"
        for issue in snapshot.main_buffer_batch.issues
    )


def test_buffer_served_code_and_name_lengths_must_match():
    payload = _payload()
    payload["buffer_master"][0]["served_process_names"] = ["制绒"]

    _assert_conversion_error(payload, "BUF-001.*length")


def test_buffer_must_serve_exactly_two_processes():
    payload = _payload()
    payload["buffer_master"][0]["served_process_codes"] = ["PROC-01"]
    payload["buffer_master"][0]["served_process_names"] = ["制绒"]

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


def test_snapshot_ignores_wrong_external_loop_for_oxidation():
    payload = _payload()
    payload["process_routes"][1]["loop_code"] = "S2-LOOP01"
    payload["process_routes"][1]["loop_name"] = "旧循环"

    route = _convert(payload).process_routes[1]

    assert route.process_name == "氧化"
    assert route.loop_code == "LOOP2"
    assert route.loop_name == "二循环"
    assert route.sequence == 2
    assert route.upstream_process_code == "PROC-01"
    assert route.upstream_process_name == "制绒"


def test_buffer_relation_is_ordered_by_route_sequence_not_served_input_order():
    payload = _payload()
    payload["process_routes"][0]["sequence"] = 2
    payload["process_routes"][1]["sequence"] = 1

    relation = _convert(payload).buffer_process_relations[0]

    assert relation.upstream_process_code == "PROC-02"
    assert relation.downstream_process_code == "PROC-01"


def test_buffer_consecutive_process_sequences_convert_relation():
    relation = _convert().buffer_process_relations[0]

    assert relation.upstream_process_code == "PROC-01"
    assert relation.downstream_process_code == "PROC-02"


def test_buffer_non_consecutive_process_sequences_convert_relation():
    payload = _payload()
    payload["process_routes"][0]["sequence"] = 10
    payload["process_routes"][1]["sequence"] = 20

    relation = _convert(payload).buffer_process_relations[0]

    assert relation.upstream_process_code == "PROC-01"
    assert relation.downstream_process_code == "PROC-02"


def test_buffer_intermediate_process_does_not_invalidate_relation():
    payload = _payload()
    payload["process_routes"][0]["sequence"] = 10
    payload["process_routes"][1]["sequence"] = 30
    _append_process_route(
        payload,
        process_code="PROC-MID",
        process_name="硼扩",
        sequence=20,
    )

    relation = _convert(payload).buffer_process_relations[0]

    assert relation.upstream_process_code == "PROC-01"
    assert relation.downstream_process_code == "PROC-02"


def test_cross_loop_reversed_served_codes_use_backend_sequence_direction():
    payload = _payload()
    payload["process_routes"][1]["sequence"] = 40
    _append_process_route(
        payload,
        process_code="PROC-ALKALI-POLISH",
        process_name="碱抛",
        sequence=50,
        loop_code="LEGACY-LOOP3",
    )
    for buffer_master in payload["buffer_master"]:
        buffer_master["served_process_codes"] = [
            "PROC-ALKALI-POLISH",
            "PROC-02",
        ]
        buffer_master["served_process_names"] = ["碱抛", "氧化"]

    snapshot = _convert(payload)
    relation = next(
        relation
        for relation in snapshot.buffer_process_relations
        if relation.buffer_code == "BUF-001"
    )
    group = next(iter(snapshot.main_buffer_batch.groups))

    assert relation.upstream_process_code == "PROC-02"
    assert relation.downstream_process_code == "PROC-ALKALI-POLISH"
    assert group.physical_buffer_key.ordered_service_process_codes == (
        "PROC-02",
        "PROC-ALKALI-POLISH",
    )
    assert not any(
        issue.code == "service_process_conflict"
        for issue in snapshot.main_buffer_batch.issues
    )


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
        "product_code": "PROD-001",
        "product_name": "产品一",
        "previous_product_code": "PROD-002",
        "previous_product_name": "产品二",
        "wafer_spec": "N",
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
            "product_name": "产品二",
            "previous_product_name": "产品一",
            "wafer_spec": "R",
            "binding_time": "2026-07-15T16:20:00+08:00",
        },
        {
            "machine_code": "MC-001",
            "machine_name": "机台一",
            "product_name": "产品一",
            "previous_product_name": "上一产品",
            "wafer_spec": "N",
            "binding_time": "2026-07-15T16:10:00+08:00",
        },
    ]

    snapshot = _convert(payload)

    assert snapshot.machine_runtimes[0].current_order_code == "ORD-002"
    assert snapshot.agv_relations[0].order_code == "ORD-002"
    assert snapshot.agv_relations[0].wafer_spec == "R"


def test_latest_agv_record_wins_after_machine_code_whitespace_normalization():
    payload = _payload()
    payload["agv_relations"] = [
        {
            "machine_code": "MC-001",
            "machine_name": "机台一",
            "product_name": "产品一",
            "previous_product_name": "上一产品",
            "wafer_spec": "N",
            "binding_time": "2026-07-15T16:10:00+08:00",
        },
        {
            "machine_code": " MC-001 ",
            "machine_name": "机台一",
            "product_name": "产品二",
            "previous_product_name": "产品一",
            "wafer_spec": "R",
            "binding_time": "2026-07-15T16:20:00+08:00",
        },
    ]

    snapshot = _convert(payload)

    assert len(snapshot.agv_relations) == 1
    assert snapshot.agv_relations[0].machine_code == "MC-001"
    assert snapshot.agv_relations[0].order_code == "ORD-002"
    assert snapshot.machine_runtimes[0].current_order_code == "ORD-002"


def test_future_agv_record_does_not_participate():
    payload = _payload()
    payload["agv_relations"].insert(
        0,
        {
            "machine_code": "MC-001",
            "machine_name": "机台一",
            "product_name": "产品二",
            "previous_product_name": "产品一",
            "wafer_spec": "R",
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


def test_latest_same_time_wafer_spec_conflict_fails():
    payload = _payload()
    tied = deepcopy(payload["agv_relations"][0])
    tied["wafer_spec"] = "R"
    payload["agv_relations"].append(tied)

    _assert_conversion_error(payload, "MC-001.*conflict.*waferspec")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("machine_name", "另一机台名"),
        ("product_name", "产品二"),
        ("previous_product_name", "另一上一产品"),
    ],
)
def test_latest_agv_business_field_conflict_fails(field, value):
    payload = _payload()
    conflicting = deepcopy(payload["agv_relations"][0])
    conflicting[field] = value
    payload["agv_relations"].append(conflicting)

    _assert_conversion_error(payload, f"MC-001.*latest.*conflict")


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
            "product_name": "未知产品",
            "previous_product_name": None,
            "wafer_spec": "N",
            "binding_time": "2026-07-15T16:40:00+08:00",
        }
    )

    assert _convert(payload).machine_runtimes[0].current_order_code == "ORD-001"


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("machine_code", "UNKNOWN", "UNKNOWN.*machine"),
        ("machine_name", "错误机台名", "MC-001.*equipmentname.*错误机台名.*机台一"),
        ("product_name", "UNKNOWN", "UNKNOWN.*product"),
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


def test_blank_agv_linename_product_name_fails_explicitly():
    payload = _payload()
    payload["agv_relations"][0]["product_name"] = "   "

    _assert_conversion_error(
        payload,
        r"AGV equipmentid 'MC-001' linename product_name.*blank",
    )


def test_last_product_name_never_overrides_current_product_binding():
    payload = _payload()
    payload["agv_relations"][0]["product_name"] = "产品一"
    payload["agv_relations"][0]["previous_product_name"] = "产品二"

    snapshot = _convert(payload)

    assert snapshot.machine_runtimes[0].current_order_code == "ORD-001"
    assert snapshot.agv_relations[0].product_name == "产品一"


@pytest.mark.parametrize("previous_name", [None, ""])
def test_empty_previous_product_name_does_not_affect_binding(previous_name):
    payload = _payload()
    payload["agv_relations"][0]["previous_product_name"] = previous_name

    assert _convert(payload).machine_runtimes[0].current_order_code == "ORD-001"


def test_agv_product_without_current_order_fails_explicitly():
    payload = _payload()
    payload["orders"] = [payload["orders"][1]]

    _assert_conversion_error(payload, "产品一.*current order")


def test_agv_machine_and_order_workshops_must_match():
    payload = _payload()
    payload["orders"][0]["workshop_code"] = "S2"
    payload["orders"][0]["workshop_name"] = "二车间"

    _assert_conversion_error(payload, "MC-001.*ORD-001.*S1.*S2")


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

    _assert_conversion_error(payload, "Running.*AGV.*P166-MC-001.*MC-001")


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

    _assert_conversion_error(
        payload,
        "Duplicate machine runtime.*P166-MC-001.*MC-001",
    )


def test_lines_without_machine_lines_convert_without_runtime_relation():
    payload = _payload()
    payload["machine_lines"] = []

    snapshot = _convert(payload)

    assert snapshot.lines
    assert snapshot.machine_lines == []
    assert snapshot.machine_runtimes[0].machine_code == "MC-001"


def test_empty_lines_and_machine_lines_convert():
    payload = _payload()
    payload["lines"] = []
    payload["machine_lines"] = []

    snapshot = _convert(payload)

    assert snapshot.lines == []
    assert snapshot.machine_lines == []
    assert snapshot.machine_runtimes[0].machine_code == "MC-001"


def test_machine_lines_without_lines_fail_explicitly():
    payload = _payload()
    payload["lines"] = []

    _assert_conversion_error(
        payload,
        "machine_lines were provided but lines are empty",
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

    _assert_conversion_error(payload, "order_code duplicate.*ORD-001")


def test_blank_order_code_fails_before_building_current_order_index():
    payload = _payload()
    payload["orders"][0]["order_code"] = "   "

    _assert_conversion_error(
        payload,
        r"orders\.order_code.*blank.*index 0",
    )


def test_process_route_requires_known_workshop_and_unique_key():
    payload = _payload()
    payload["process_routes"].append(deepcopy(payload["process_routes"][0]))

    _assert_conversion_error(payload, "S1.*PROC-01.*duplicate")


def test_process_route_sequence_must_start_at_one():
    payload = _payload()
    payload["process_routes"][0]["sequence"] = 0

    _assert_conversion_error(payload, "PROC-01.*sequence")


def test_duplicate_master_codes_fail():
    payload = _payload()
    duplicate = deepcopy(payload["machine_master"][0])
    duplicate["p166_jt_group"] = "P166-MC-SECOND"
    payload["machine_master"].append(duplicate)

    _assert_conversion_error(payload, "machine_code duplicate.*MC-001")


def test_blank_master_standard_code_fails_before_machine_mapping():
    payload = _payload()
    payload["machine_master"][0]["machine_code"] = "   "

    _assert_conversion_error(
        payload,
        r"machine_master\.machine_code.*blank.*index 0",
    )


def test_blank_master_p166_code_fails_with_standard_machine_context():
    payload = _payload()
    payload["machine_master"][0]["p166_jt_group"] = "   "

    _assert_conversion_error(
        payload,
        r"machine_master\.p166_jt_group.*blank.*MC-001",
    )


def test_duplicate_master_p166_code_fails_without_overwriting_mapping():
    payload = _payload()
    duplicate = deepcopy(payload["machine_master"][0])
    duplicate["machine_code"] = "MC-002"
    payload["machine_master"].append(duplicate)

    _assert_conversion_error(
        payload,
        (
            r"machine_master\.p166_jt_group duplicate.*P166-MC-001"
            r".*MC-001.*MC-002"
        ),
    )


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
    payload["active_cutline_events"] = [
        _active_cutline_event(
            plan_id="PLAN-001",
            warning_id="WARNING-001",
            status="return_recommended",
        )
    ]
    payload["return_suggested_event_ids"] = ["EVENT-001"]
    payload["mixed_cutline_event_ids"] = ["EVENT-OLDER"]
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
    assert internal_event.status == "return_recommended"
    assert internal_event.plan_id == "PLAN-001"
    assert internal_event.warning_id == "WARNING-001"
    assert internal_event.source_buffer_code is None
    assert internal_event.source_wafer_size is None
    assert internal_event.source_wafer_spec is None
    assert internal_event.contribution_capacity is None
    assert internal_event.warning_type is None
    assert internal_event is not request.active_cutline_events[0]
    assert snapshot.return_suggested_event_ids == ["EVENT-001"]
    assert snapshot.mixed_cutline_event_ids == ["EVENT-OLDER"]
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
    valid_other_field = (
        "downstream_process_code"
        if field == "upstream_process_code"
        else "upstream_process_code"
    )
    valid_other_process_code = (
        f"S2-{payload['process_routes'][valid_other_route_index]['process_code']}"
    )
    payload["process_routes"].append(
        {
            **deepcopy(payload["process_routes"][valid_other_route_index]),
            "process_code": valid_other_process_code,
            "workshop_code": "S2",
            "workshop_name": payload["workshops"][1]["workshop_name"],
            "loop_code": "LOOP-S2",
        }
    )
    payload["active_cutline_events"] = [
        _active_cutline_event(
            workshop_code="S2",
            **{valid_other_field: valid_other_process_code},
        )
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


def test_naive_active_cutline_event_time_is_interpreted_as_local_time():
    payload = _payload()
    payload["active_cutline_events"] = [
        _active_cutline_event(cutline_start_time="2026-07-15T08:30:01")
    ]

    snapshot = snapshot_adapter_module.SnapshotAdapter().to_algorithm_snapshot(
        CutlineAlgorithmRequest.model_validate(payload)
    )

    actual = snapshot.active_cutline_events[0].cutline_start_time
    assert actual == datetime(
        2026,
        7,
        15,
        8,
        30,
        1,
        tzinfo=timezone(timedelta(hours=8)),
    )


def _append_s2_process_interval(payload: dict) -> None:
    for index, process_code in enumerate(("S2-PROC-01", "S2-PROC-02")):
        route = deepcopy(payload["process_routes"][index])
        route.update(
            {
                "process_code": process_code,
                "process_name": ("制绒", "氧化")[index],
                "workshop_code": "S2",
                "workshop_name": "二车间",
                "loop_code": "S2-LOOP",
                "loop_name": "S2循环",
                "upstream_process_code": (
                    None if index == 0 else "S2-PROC-01"
                ),
                "upstream_process_name": (
                    None if index == 0 else "S2-PROC-01"
                ),
                "downstream_process_code": (
                    "S2-PROC-02" if index == 0 else None
                ),
                "downstream_process_name": (
                    "S2-PROC-02" if index == 0 else None
                ),
            }
        )
        payload["process_routes"].append(route)


def test_active_event_workshop_must_match_machine_resolver_workshop():
    payload = _payload()
    _append_s2_process_interval(payload)
    payload["active_cutline_events"] = [
        _active_cutline_event(
            workshop_code="S2",
            upstream_process_code="S2-PROC-01",
            downstream_process_code="S2-PROC-02",
        )
    ]

    _assert_conversion_error(
        payload,
        "EVENT-001.*machine.*MC-001.*workshop.*S1.*S2",
    )


def test_active_warning_buffer_workshop_must_match_event_workshop():
    payload = _payload()
    _append_s2_process_interval(payload)
    warning_buffer = deepcopy(payload["buffer_master"][0])
    warning_buffer.update(
        {
            "buffer_code": "BUF-S2",
            "served_process_codes": ["S2-PROC-01", "S2-PROC-02"],
            "served_process_names": ["S2-PROC-01", "S2-PROC-02"],
            "loop_code": "LOOP2",
            "loop_name": "二循环",
        }
    )
    payload["buffer_master"].append(warning_buffer)
    payload["active_cutline_events"] = [
        _active_cutline_event(warning_buffer_code="BUF-S2")
    ]

    _assert_conversion_error(
        payload,
        "EVENT-001.*warning_buffer_code.*BUF-S2.*workshop.*S2.*S1",
    )
