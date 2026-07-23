"""Deterministic V3 full-route request payloads for examples and tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable


PROCESS_CODES = (
    "发料机",
    "制绒",
    "碱抛",
    "背膜",
    "硼扩",
    "POLY",
    "RCA",
    "退火",
    "氧化",
    "正膜",
    "丝网",
)

BUFFER_INTERVALS = (
    ("310110301", ("发料机", "制绒")),
    ("310110302", ("制绒", "碱抛")),
    ("310110303", ("碱抛", "背膜")),
    ("310110304", ("背膜", "硼扩")),
    ("310110305", ("硼扩", "POLY")),
    ("310110306", ("POLY", "RCA")),
    ("310110307", ("RCA", "退火")),
    ("310110308", ("退火", "氧化")),
    ("310110309", ("氧化", "正膜")),
    ("310110310", ("正膜", "丝网")),
)

MACHINE_CODES_BY_PROCESS = {
    process_code: (f"EA{index * 2 - 1:03d}", f"EA{index * 2:03d}")
    for index, process_code in enumerate(PROCESS_CODES, start=1)
}

SNAPSHOT_TIME = "2026-07-17T08:00:00+08:00"
CATALOG_TIME = "2026-07-17T07:55:00+08:00"
TARGET_BUFFER_CODE = "310110302"
TARGET_ORDER_CODE = "ORD-S2-001"
SUPPORT_ORDER_CODE = "ORD-S2-002"
MULTILAYER_MAIN_ID = "MAIN-31011280"
MULTILAYER_BUFFER_CODES = ("310112803", "310112804")


def _machine_name(machine_code: str, process_code: str) -> str:
    process_label = process_code if process_code.endswith("机") else f"{process_code}机"
    return f"{machine_code}{process_label}"


def _lines() -> list[dict[str, Any]]:
    return [
        {
            "line_code": "S2-SW1A",
            "line_name": "SW1A",
            "wafer_spec": "N",
            "workshop_code": "S2",
            "workshop_name": "S2车间",
        },
        {
            "line_code": "S2-SW1B",
            "line_name": "SW1B",
            "wafer_spec": "N",
            "workshop_code": "S2",
            "workshop_name": "S2车间",
        },
        {
            "line_code": "S2-SW2A",
            "line_name": "SW2A",
            "wafer_spec": "R",
            "workshop_code": "S2",
            "workshop_name": "S2车间",
        },
        {
            "line_code": "S2-SW2B",
            "line_name": "SW2B",
            "wafer_spec": "P",
            "workshop_code": "S2",
            "workshop_name": "S2车间",
        },
    ]


def _products() -> list[dict[str, Any]]:
    return [
        {
            "product_code": "PROD-S2-N-TARGET",
            "product_name": "182N至上产品",
            "wafer_size": "182",
            "source_grade": "A",
            "material_code": "MAT-S2-N-TARGET",
            "material_name": "182N硅片",
        },
        {
            "product_code": "PROD-S2-N-SUPPORT",
            "product_name": "182N支援产品",
            "wafer_size": "182",
            "source_grade": "A",
            "material_code": "MAT-S2-N-SUPPORT",
            "material_name": "182N支援硅片",
        },
        {
            "product_code": "PROD-S2-R",
            "product_name": "210R华晟产品",
            "wafer_size": "210",
            "source_grade": "A-",
            "material_code": "MAT-S2-R",
            "material_name": "210R硅片",
        },
        {
            "product_code": "PROD-S2-P",
            "product_name": "210P晶澳产品",
            "wafer_size": "210",
            "source_grade": "A",
            "material_code": "MAT-S2-P",
            "material_name": "210P硅片",
        },
    ]


def _orders() -> list[dict[str, Any]]:
    definitions = (
        (TARGET_ORDER_CODE, "至上", "PROD-S2-N-TARGET", "182N至上产品"),
        (SUPPORT_ORDER_CODE, "至上支援单", "PROD-S2-N-SUPPORT", "182N支援产品"),
        ("ORD-S2-003", "华晟", "PROD-S2-R", "210R华晟产品"),
        ("ORD-S2-004", "晶澳", "PROD-S2-P", "210P晶澳产品"),
    )
    return [
        {
            "order_code": order_code,
            "order_name": order_name,
            "order_status": "生产中",
            "total_quantity": 100000.0,
            "piece_source": "A",
            "estimated_yield": "98.5%",
            "product_code": product_code,
            "product_name": product_name,
            "workshop_code": "S2",
            "workshop_name": "S2车间",
            "produced_quantity": 0.0,
            "remaining_quantity": 100000.0,
        }
        for order_code, order_name, product_code, product_name in definitions
    ]


def _process_routes() -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    for index, process_code in enumerate(PROCESS_CODES):
        upstream = PROCESS_CODES[index - 1] if index else None
        downstream = PROCESS_CODES[index + 1] if index + 1 < len(PROCESS_CODES) else None
        routes.append(
            {
                "process_code": process_code,
                "process_name": process_code,
                "sequence": index + 1,
                "cache_type": "BUFFER",
                "workshop_code": "S2",
                "workshop_name": "S2车间",
                "loop_code": "S2-LOOP01",
                "loop_name": "S2主工艺循环",
                "upstream_process_code": upstream,
                "upstream_process_name": upstream,
                "downstream_process_code": downstream,
                "downstream_process_name": downstream,
            }
        )
    return routes


def _buffer_master() -> list[dict[str, Any]]:
    return [
        {
            "buffer_code": buffer_code,
            "buffer_name": f"{upstream}-{downstream}Buffer",
            "buffer_type": "PROCESS",
            "buffer_type_title": "工序缓存",
            "max_capacity": 100000.0,
            "safety_low": 100.0,
            "served_process_codes": [upstream, downstream],
            "served_process_names": [upstream, downstream],
            "loop_code": "S2-LOOP01",
            "loop_name": "S2主工艺循环",
        }
        for buffer_code, (upstream, downstream) in BUFFER_INTERVALS
    ]


def _machine_definitions() -> list[tuple[str, str, str, str, str]]:
    definitions: list[tuple[str, str, str, str, str]] = []
    for process_code in PROCESS_CODES:
        first, second = MACHINE_CODES_BY_PROCESS[process_code]
        definitions.extend(
            (
                (first, process_code, "S2-SW1A", "运行", TARGET_ORDER_CODE),
                (second, process_code, "S2-SW1B", "异常", ""),
            )
        )
    definitions.extend(
        (
            ("EA023", "制绒", "S2-SW2A", "运行", "ORD-S2-003"),
            ("EA024", "制绒", "S2-SW2B", "运行", "ORD-S2-004"),
        )
    )
    return definitions


def _machine_master() -> list[dict[str, Any]]:
    return [
        {
            "machine_code": machine_code,
            "machine_name": _machine_name(machine_code, process_code),
            "process_code": process_code,
            "process_name": process_code,
        }
        for machine_code, process_code, _, _, _ in _machine_definitions()
    ]


def _machine_realtime() -> list[dict[str, Any]]:
    return [
        {
            "machine_code": machine_code,
            "status": status,
            "tangent_time": None,
            "input_quantity": 100.0 if status == "运行" else 0.0,
            "output_quantity": 100.0 if status == "运行" else 0.0,
            "completed_quantity": 100.0 if status == "运行" else 0.0,
            "period_quantity": 100.0 if status == "运行" else 0.0,
            "out_time": "2026-07-17T07:55:00+08:00" if status == "运行" else None,
        }
        for machine_code, _, _, status, _ in _machine_definitions()
    ]


def _machine_lines() -> list[dict[str, Any]]:
    line_by_code = {line["line_code"]: line for line in _lines()}
    return [
        {
            "machine_code": machine_code,
            "machine_name": _machine_name(machine_code, process_code),
            "line_code": line_code,
            "line_name": line_by_code[line_code]["line_name"],
            "wafer_spec": line_by_code[line_code]["wafer_spec"],
        }
        for machine_code, process_code, line_code, _, _ in _machine_definitions()
    ]


def _machine_process_times() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for machine_code, process_code, _, _, _ in _machine_definitions():
        for product in _products():
            result.append(
                {
                    "machine_code": machine_code,
                    "machine_name": _machine_name(machine_code, process_code),
                    "product_code": product["product_code"],
                    "product_name": product["product_name"],
                    "proc_seconds": 120.0,
                    "actual_capacity": 200.0,
                }
            )
    return result


def _buffer_realtime() -> list[dict[str, Any]]:
    return [
        {
            "main_id": f"MAIN-{buffer_code}",
            "buffer_code": buffer_code,
            "bound_source_name": "至上",
            "current_quantity": 1000.0,
            "current_utilization_rate": 0.01,
        }
        for buffer_code, _ in BUFFER_INTERVALS
    ]


def _agv_relations() -> list[dict[str, Any]]:
    order_names = {
        order["order_code"]: order["order_name"] for order in _orders()
    }
    return [
        {
            "equipmentid": machine_code,
            "equipmentname": _machine_name(machine_code, process_code),
            "lastlinecode": order_code,
            "lastlinename": order_names[order_code],
            "createtime": "2026-07-17 07:55:00",
        }
        for machine_code, process_code, _, _, order_code in _machine_definitions()
        if order_code
    ]


def _build_base_template() -> dict[str, Any]:
    return {
        "snapshot_meta": {
            "run_id": "RUN-V3-BASE",
            "trigger_type": "manual_test",
            "workshop_id": "S2",
            "snapshot_time": SNAPSHOT_TIME,
            "params_version": 3,
            "catalog_version": "V3-FAKE-CATALOG-001",
            "catalog_loaded_at": CATALOG_TIME,
            "degraded_flags": [],
        },
        "machine_realtime": _machine_realtime(),
        "machine_master": _machine_master(),
        "machine_process_times": _machine_process_times(),
        "workshops": [{"workshop_code": "S2", "workshop_name": "S2车间"}],
        "lines": _lines(),
        "machine_lines": _machine_lines(),
        "orders": _orders(),
        "products": _products(),
        "process_routes": _process_routes(),
        "buffer_realtime": _buffer_realtime(),
        "buffer_master": _buffer_master(),
        "agv_relations": _agv_relations(),
        "active_cutline_events": [],
    }


_BASE_TEMPLATE = _build_base_template()


def build_base_request_payload() -> dict[str, Any]:
    """Return an independent complete V3 request payload."""

    return deepcopy(_BASE_TEMPLATE)


def _runtime(payload: dict[str, Any], machine_code: str) -> dict[str, Any]:
    return next(
        item
        for item in payload["machine_realtime"]
        if item["machine_code"] == machine_code
    )


def _set_agv_binding(
    payload: dict[str, Any],
    machine_code: str,
    order_code: str,
) -> None:
    payload["agv_relations"] = [
        relation
        for relation in payload["agv_relations"]
        if relation["equipmentid"] != machine_code
    ]
    if not order_code:
        return

    machine = next(
        item
        for item in payload["machine_master"]
        if item["machine_code"] == machine_code
    )
    order = next(
        item
        for item in payload["orders"]
        if item["order_code"] == order_code
    )
    payload["agv_relations"].append(
        {
            "equipmentid": machine_code,
            "equipmentname": machine["machine_name"],
            "lastlinecode": order_code,
            "lastlinename": order["order_name"],
            "createtime": "2026-07-17 07:55:00",
        }
    )


def _set_runtime(
    payload: dict[str, Any],
    machine_code: str,
    *,
    status: str,
    order_code: str,
    input_quantity: float,
    output_quantity: float,
) -> None:
    runtime = _runtime(payload, machine_code)
    runtime.update(
        {
            "status": status,
            "input_quantity": float(input_quantity),
            "output_quantity": float(output_quantity),
            "completed_quantity": float(output_quantity),
            "period_quantity": float(output_quantity),
            "out_time": (
                "2026-07-17T07:55:00+08:00" if status == "运行" else None
            ),
        }
    )
    _set_agv_binding(payload, machine_code, order_code)


def _buffer(payload: dict[str, Any], buffer_code: str) -> dict[str, Any]:
    return next(
        item
        for item in payload["buffer_master"]
        if item["buffer_code"] == buffer_code
    )


def _inventory(
    payload: dict[str, Any],
    buffer_code: str,
    order_name: str,
) -> dict[str, Any]:
    return next(
        item
        for item in payload["buffer_realtime"]
        if item["buffer_code"] == buffer_code
        and item["bound_source_name"] == order_name
    )


def _upsert_inventory(
    payload: dict[str, Any],
    *,
    buffer_code: str,
    order_code: str,
    order_name: str,
    quantity: float,
    capacity: float | None = None,
) -> None:
    matches = [
        item
        for item in payload["buffer_realtime"]
        if item["buffer_code"] == buffer_code
        and item["bound_source_name"] == order_name
    ]
    if matches:
        item = matches[0]
    else:
        item = {
            "main_id": f"MAIN-{buffer_code}",
            "buffer_code": buffer_code,
            "bound_source_name": order_name,
            "current_quantity": 0.0,
            "current_utilization_rate": 0.0,
        }
        payload["buffer_realtime"].append(item)
    max_capacity = capacity or _buffer(payload, buffer_code)["max_capacity"]
    item["current_quantity"] = float(quantity)
    item["current_utilization_rate"] = float(quantity) / max_capacity


def _scenario(name: str) -> dict[str, Any]:
    payload = build_base_request_payload()
    payload["snapshot_meta"]["run_id"] = f"RUN-V3-{name.upper().replace('_', '-')}"
    return payload


def build_no_warning_payload() -> dict[str, Any]:
    return _scenario("no_warning")


def build_multilayer_buffer_payload() -> dict[str, Any]:
    """Build two physical Buffer layers sharing one calculation main_id."""

    payload = _scenario("buffer_main_id_grouping")
    _set_runtime(
        payload,
        "EA004",
        status="\u8fd0\u884c",
        order_code=SUPPORT_ORDER_CODE,
        input_quantity=100,
        output_quantity=100,
    )
    template = _buffer(payload, TARGET_BUFFER_CODE)
    capacities = (10000.0, 20000.0)
    for buffer_code, capacity in zip(
        MULTILAYER_BUFFER_CODES,
        capacities,
        strict=True,
    ):
        layer = deepcopy(template)
        layer.update(
            {
                "buffer_code": buffer_code,
                "max_capacity": capacity,
            }
        )
        payload["buffer_master"].append(layer)

    order_names = {
        item["order_code"]: item["order_name"]
        for item in payload["orders"]
    }
    first_code, second_code = MULTILAYER_BUFFER_CODES
    payload["buffer_realtime"].extend(
        [
            {
                "main_id": MULTILAYER_MAIN_ID,
                "buffer_code": first_code,
                "bound_source_name": order_names[TARGET_ORDER_CODE],
                "current_quantity": 3600.0,
                "current_utilization_rate": 0.36,
            },
            {
                "main_id": MULTILAYER_MAIN_ID,
                "buffer_code": second_code,
                "bound_source_name": order_names[TARGET_ORDER_CODE],
                "current_quantity": 7200.0,
                "current_utilization_rate": 0.36,
            },
            {
                "main_id": MULTILAYER_MAIN_ID,
                "buffer_code": second_code,
                "bound_source_name": order_names[SUPPORT_ORDER_CODE],
                "current_quantity": 2000.0,
                "current_utilization_rate": 0.1,
            },
        ]
    )
    return payload


def _stockout_payload(name: str) -> dict[str, Any]:
    payload = _scenario(name)
    _set_runtime(
        payload,
        "EA003",
        status="运行",
        order_code=TARGET_ORDER_CODE,
        input_quantity=100,
        output_quantity=100,
    )
    _set_runtime(
        payload,
        "EA004",
        status="运行",
        order_code=SUPPORT_ORDER_CODE,
        input_quantity=300,
        output_quantity=300,
    )
    _set_runtime(
        payload,
        "EA005",
        status="运行",
        order_code=TARGET_ORDER_CODE,
        input_quantity=300,
        output_quantity=100,
    )
    _set_runtime(
        payload,
        "EA006",
        status="运行",
        order_code=SUPPORT_ORDER_CODE,
        input_quantity=100,
        output_quantity=100,
    )
    _upsert_inventory(
        payload,
        buffer_code=TARGET_BUFFER_CODE,
        order_code=TARGET_ORDER_CODE,
        order_name="至上",
        quantity=100,
    )
    _upsert_inventory(
        payload,
        buffer_code=TARGET_BUFFER_CODE,
        order_code=SUPPORT_ORDER_CODE,
        order_name="至上支援单",
        quantity=2000,
    )
    return payload


def build_stockout_auto_payload() -> dict[str, Any]:
    return _stockout_payload("stockout_auto")


def build_multilayer_stockout_payload() -> dict[str, Any]:
    """Build the automatic stockout case on two physical Buffer layers."""

    payload = _stockout_payload("buffer_main_id_stockout")
    template = _buffer(payload, TARGET_BUFFER_CODE)
    for buffer_code in MULTILAYER_BUFFER_CODES:
        layer = deepcopy(template)
        layer.update(
            {
                "buffer_code": buffer_code,
                "max_capacity": 50000.0,
            }
        )
        payload["buffer_master"].append(layer)

    payload["buffer_realtime"] = [
        item
        for item in payload["buffer_realtime"]
        if item["buffer_code"] != TARGET_BUFFER_CODE
    ]
    order_names = {
        item["order_code"]: item["order_name"]
        for item in payload["orders"]
    }
    first_code, second_code = MULTILAYER_BUFFER_CODES
    payload["buffer_realtime"].extend(
        [
            {
                "main_id": MULTILAYER_MAIN_ID,
                "buffer_code": first_code,
                "bound_source_name": order_names[TARGET_ORDER_CODE],
                "current_quantity": 40.0,
                "current_utilization_rate": 0.0008,
            },
            {
                "main_id": MULTILAYER_MAIN_ID,
                "buffer_code": second_code,
                "bound_source_name": order_names[TARGET_ORDER_CODE],
                "current_quantity": 60.0,
                "current_utilization_rate": 0.0012,
            },
            {
                "main_id": MULTILAYER_MAIN_ID,
                "buffer_code": second_code,
                "bound_source_name": order_names[SUPPORT_ORDER_CODE],
                "current_quantity": 2000.0,
                "current_utilization_rate": 0.04,
            },
        ]
    )
    return payload


def build_stockout_manual_payload() -> dict[str, Any]:
    payload = _stockout_payload("stockout_manual")
    _set_runtime(
        payload,
        "EA004",
        status="异常",
        order_code=SUPPORT_ORDER_CODE,
        input_quantity=0,
        output_quantity=0,
    )
    return payload


def build_stockout_manual_insufficient_payload() -> dict[str, Any]:
    payload = _stockout_payload("stockout_manual_insufficient")
    _set_runtime(
        payload,
        "EA004",
        status="运行",
        order_code=SUPPORT_ORDER_CODE,
        input_quantity=100,
        output_quantity=100,
    )
    return payload


def build_overflow_warning_payload() -> dict[str, Any]:
    payload = _scenario("overflow_warning")
    _buffer(payload, TARGET_BUFFER_CODE)["max_capacity"] = 1000.0
    _set_runtime(
        payload,
        "EA003",
        status="运行",
        order_code=TARGET_ORDER_CODE,
        input_quantity=100,
        output_quantity=150,
    )
    _set_runtime(
        payload,
        "EA004",
        status="运行",
        order_code=SUPPORT_ORDER_CODE,
        input_quantity=200,
        output_quantity=200,
    )
    _set_runtime(
        payload,
        "EA005",
        status="运行",
        order_code=TARGET_ORDER_CODE,
        input_quantity=100,
        output_quantity=100,
    )
    _set_runtime(
        payload,
        "EA006",
        status="运行",
        order_code=SUPPORT_ORDER_CODE,
        input_quantity=100,
        output_quantity=100,
    )
    _upsert_inventory(
        payload,
        buffer_code=TARGET_BUFFER_CODE,
        order_code=TARGET_ORDER_CODE,
        order_name="至上",
        quantity=450,
        capacity=1000,
    )
    _upsert_inventory(
        payload,
        buffer_code=TARGET_BUFFER_CODE,
        order_code=SUPPORT_ORDER_CODE,
        order_name="至上支援单",
        quantity=450,
        capacity=1000,
    )
    return payload


def build_overflow_manual_payload() -> dict[str, Any]:
    payload = _scenario("overflow_manual")
    _buffer(payload, TARGET_BUFFER_CODE)["max_capacity"] = 1000.0
    _set_runtime(
        payload,
        "EA003",
        status="运行",
        order_code=TARGET_ORDER_CODE,
        input_quantity=100,
        output_quantity=100,
    )
    _set_runtime(
        payload,
        "EA004",
        status="运行",
        order_code=SUPPORT_ORDER_CODE,
        input_quantity=300,
        output_quantity=300,
    )
    _set_runtime(
        payload,
        "EA005",
        status="运行",
        order_code=TARGET_ORDER_CODE,
        input_quantity=200,
        output_quantity=100,
    )
    _set_runtime(
        payload,
        "EA006",
        status="运行",
        order_code=SUPPORT_ORDER_CODE,
        input_quantity=100,
        output_quantity=100,
    )
    _upsert_inventory(
        payload,
        buffer_code=TARGET_BUFFER_CODE,
        order_code=TARGET_ORDER_CODE,
        order_name="至上",
        quantity=200,
        capacity=1000,
    )
    _upsert_inventory(
        payload,
        buffer_code=TARGET_BUFFER_CODE,
        order_code=SUPPORT_ORDER_CODE,
        order_name="至上支援单",
        quantity=750,
        capacity=1000,
    )
    return payload


def build_return_round_1_payload() -> dict[str, Any]:
    payload = _stockout_payload("return_round_1")
    return payload


def _round_one_plan_id() -> str:
    return (
        "stockout:2026-07-17T08:00:00+08:00:"
        f"{TARGET_BUFFER_CODE}:{TARGET_ORDER_CODE}"
    )


def build_return_round_2_payload() -> dict[str, Any]:
    payload = _stockout_payload("return_round_2")
    payload["snapshot_meta"]["snapshot_time"] = "2026-07-17T08:05:00+08:00"
    _set_runtime(
        payload,
        "EA003",
        status="运行",
        order_code=TARGET_ORDER_CODE,
        input_quantity=100,
        output_quantity=300,
    )
    _set_runtime(
        payload,
        "EA005",
        status="运行",
        order_code=TARGET_ORDER_CODE,
        input_quantity=100,
        output_quantity=100,
    )
    plan_id = _round_one_plan_id()
    payload["active_cutline_events"] = [
        {
            "event_id": f"CUT-{plan_id}-EA004",
            "machine_code": "EA004",
            "source_order_code": SUPPORT_ORDER_CODE,
            "target_order_code": TARGET_ORDER_CODE,
            "workshop_code": "S2",
            "target_buffer_code": TARGET_BUFFER_CODE,
            "upstream_process_code": "制绒",
            "downstream_process_code": "碱抛",
            "target_wafer_size": "182",
            "target_wafer_spec": "N",
            "cutline_start_time": SNAPSHOT_TIME,
            "negative_start_time": None,
        }
    ]
    return payload


def build_return_recommended_payload() -> dict[str, Any]:
    payload = build_return_round_2_payload()
    payload["snapshot_meta"]["snapshot_time"] = "2026-07-17T08:26:00+08:00"
    payload["active_cutline_events"][0]["negative_start_time"] = (
        "2026-07-17T08:05:00+08:00"
    )
    _inventory(
        payload,
        TARGET_BUFFER_CODE,
        "至上",
    )["current_quantity"] = 1000.0
    return payload


def build_silk_not_ready_payload() -> dict[str, Any]:
    return _scenario("silk_not_ready")


def build_silk_prepare_payload() -> dict[str, Any]:
    payload = _scenario("silk_prepare")
    target_order = next(
        order for order in payload["orders"] if order["order_code"] == TARGET_ORDER_CODE
    )
    target_order["produced_quantity"] = 99975.0
    target_order["remaining_quantity"] = 25.0
    _set_runtime(
        payload,
        "EA021",
        status="运行",
        order_code=TARGET_ORDER_CODE,
        input_quantity=100,
        output_quantity=50,
    )
    _set_runtime(
        payload,
        "EA022",
        status="异常",
        order_code=TARGET_ORDER_CODE,
        input_quantity=1000,
        output_quantity=1000,
    )
    return payload


def build_mixing_failure_payload() -> dict[str, Any]:
    payload = _stockout_payload("mixing_failure")
    _set_runtime(
        payload,
        "EA005",
        status="运行",
        order_code=TARGET_ORDER_CODE,
        input_quantity=600,
        output_quantity=100,
    )
    _set_runtime(
        payload,
        "EA023",
        status="运行",
        order_code=SUPPORT_ORDER_CODE,
        input_quantity=300,
        output_quantity=300,
    )
    ea023_line = next(
        item
        for item in payload["machine_lines"]
        if item["machine_code"] == "EA023"
    )
    ea023_line.update(
        {
            "line_code": "S2-SW1A",
            "line_name": "SW1A",
            "wafer_spec": "N",
        }
    )
    payload["machine_process_times"] = [
        item
        for item in payload["machine_process_times"]
        if not (
            item["machine_code"] == "EA004"
            and item["product_code"] == "PROD-S2-N-SUPPORT"
        )
    ]
    return payload


V3_SCENARIO_BUILDERS: dict[str, Callable[[], dict[str, Any]]] = {
    "v3_no_warning": build_no_warning_payload,
    "v3_buffer_main_id_grouping": build_multilayer_buffer_payload,
    "v3_stockout_auto": build_stockout_auto_payload,
    "v3_stockout_manual": build_stockout_manual_payload,
    "v3_stockout_manual_insufficient": build_stockout_manual_insufficient_payload,
    "v3_overflow_warning": build_overflow_warning_payload,
    "v3_overflow_manual": build_overflow_manual_payload,
    "v3_return_round_1": build_return_round_1_payload,
    "v3_return_round_2": build_return_round_2_payload,
    "v3_return_recommended": build_return_recommended_payload,
    "v3_silk_not_ready": build_silk_not_ready_payload,
    "v3_silk_prepare": build_silk_prepare_payload,
    "v3_mixing_failure": build_mixing_failure_payload,
}
