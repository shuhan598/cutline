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
    "ALD",
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
    ("310110309", ("氧化", "ALD")),
    ("310110310", ("正膜", "丝网")),
    ("310110311", ("ALD", "正膜")),
)

MACHINE_CODES_BY_PROCESS = {
    "发料机": ("EA001", "EA002"),
    "制绒": ("EA003", "EA004"),
    "碱抛": ("EA005", "EA006"),
    "背膜": ("EA007", "EA008"),
    "硼扩": ("EA009", "EA010"),
    "POLY": ("EA011", "EA012"),
    "RCA": ("EA013", "EA014"),
    "退火": ("EA015", "EA016"),
    "氧化": ("EA017", "EA018"),
    "正膜": ("EA019", "EA020"),
    "丝网": ("EA021", "EA022"),
    "ALD": ("EA025", "EA026"),
}

SNAPSHOT_TIME = "2026-07-17T08:00:00+08:00"
CATALOG_TIME = "2026-07-17T07:55:00+08:00"
TARGET_BUFFER_CODE = "310110302"
SUPPORT_BUFFER_CODE = "310112802"
TARGET_ORDER_CODE = "ORD-S2-001"
SUPPORT_ORDER_CODE = "ORD-S2-002"
MULTILAYER_MAIN_ID = "MAIN-31011280"
MULTILAYER_BUFFER_CODES = ("310112803", "310112804")


def _machine_name(machine_code: str, process_code: str) -> str:
    process_label = process_code if process_code.endswith("机") else f"{process_code}机"
    return f"{machine_code}{process_label}"


def _p166_jt_group(machine_code: str) -> str:
    return f"P166-{machine_code}"


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
        (TARGET_ORDER_CODE, "PROD-S2-N-TARGET", "182N至上产品"),
        (SUPPORT_ORDER_CODE, "PROD-S2-N-SUPPORT", "182N支援产品"),
        ("ORD-S2-003", "PROD-S2-R", "210R华晟产品"),
        ("ORD-S2-004", "PROD-S2-P", "210P晶澳产品"),
    )
    return [
        {
            "order_code": order_code,
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
        for order_code, product_code, product_name in definitions
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
            "p166_jt_group": _p166_jt_group(machine_code),
            "machine_name": _machine_name(machine_code, process_code),
            "process_code": process_code,
            "process_name": process_code,
        }
        for machine_code, process_code, _, _, _ in _machine_definitions()
    ]


def _machine_realtime() -> list[dict[str, Any]]:
    return [
        {
            "machine_code": _p166_jt_group(machine_code),
            "status": status,
            "tangent_time": None,
            "input_quantity": 100.0 if status == "运行" else 0.0,
            "output_quantity": 100.0 if status == "运行" else 0.0,
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
            "bound_source_name": "182N至上产品",
            "current_quantity": 1000.0,
            "current_utilization_rate": 0.01,
        }
        for buffer_code, _ in BUFFER_INTERVALS
    ]


def _agv_relations() -> list[dict[str, Any]]:
    product_names = {
        order["order_code"]: order["product_name"] for order in _orders()
    }
    wafer_specs = {
        machine_code: next(
            line["wafer_spec"]
            for line in _lines()
            if line["line_code"] == line_code
        )
        for machine_code, _, line_code, _, _ in _machine_definitions()
    }
    return [
        {
            "equipmentid": machine_code,
            "equipmentname": _machine_name(machine_code, process_code),
            "linename": product_names[order_code],
            "lastlinename": None,
            "waferspec": wafer_specs[machine_code],
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
        "pending_cutline_plans": [],
        "active_cutline_events": [],
    }


_BASE_TEMPLATE = _build_base_template()


def build_base_request_payload() -> dict[str, Any]:
    """Return an independent complete V3 request payload."""

    return deepcopy(_BASE_TEMPLATE)


def _runtime(payload: dict[str, Any], machine_code: str) -> dict[str, Any]:
    machine = next(
        item
        for item in payload["machine_master"]
        if item["machine_code"] == machine_code
    )
    return next(
        item
        for item in payload["machine_realtime"]
        if item["machine_code"] == machine["p166_jt_group"]
    )


def _set_agv_binding(
    payload: dict[str, Any],
    machine_code: str,
    order_code: str,
    *,
    product_name: str | None = None,
    previous_product_name: str | None = None,
    wafer_spec: str | None = None,
    binding_time: str = "2026-07-17 07:55:00",
) -> None:
    """Replace a raw AGV binding, with line spec only as a fixture default."""

    payload["agv_relations"] = [
        relation
        for relation in payload["agv_relations"]
        if relation["equipmentid"] != machine_code
    ]
    if not order_code:
        return

    payload["agv_relations"].append(
        _agv_binding_record(
            payload,
            machine_code,
            order_code,
            product_name=product_name,
            previous_product_name=previous_product_name,
            wafer_spec=wafer_spec,
            binding_time=binding_time,
        )
    )


def _agv_binding_record(
    payload: dict[str, Any],
    machine_code: str,
    order_code: str,
    *,
    product_name: str | None = None,
    previous_product_name: str | None = None,
    wafer_spec: str | None = None,
    binding_time: str = "2026-07-17 07:55:00",
) -> dict[str, Any]:
    """Build one raw AGV history record without replacing earlier records."""

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
    if wafer_spec is None:
        machine_line = next(
            item
            for item in payload["machine_lines"]
            if item["machine_code"] == machine_code
        )
        wafer_spec = machine_line["wafer_spec"]
    return {
        "equipmentid": machine_code,
        "equipmentname": machine["machine_name"],
        "linename": (
            order["product_name"] if product_name is None else product_name
        ),
        "lastlinename": previous_product_name,
        "waferspec": wafer_spec,
        "createtime": binding_time,
    }


def _set_runtime(
    payload: dict[str, Any],
    machine_code: str,
    *,
    status: str,
    order_code: str,
    input_quantity: float,
    output_quantity: float,
    product_name: str | None = None,
    previous_product_name: str | None = None,
    wafer_spec: str | None = None,
    binding_time: str = "2026-07-17 07:55:00",
) -> None:
    runtime = _runtime(payload, machine_code)
    runtime.update(
        {
            "status": status,
            "input_quantity": float(input_quantity),
            "output_quantity": float(output_quantity),
            "out_time": (
                "2026-07-17T07:55:00+08:00" if status == "运行" else None
            ),
        }
    )
    _set_agv_binding(
        payload,
        machine_code,
        order_code,
        product_name=product_name,
        previous_product_name=previous_product_name,
        wafer_spec=wafer_spec,
        binding_time=binding_time,
    )


def _buffer(payload: dict[str, Any], buffer_code: str) -> dict[str, Any]:
    return next(
        item
        for item in payload["buffer_master"]
        if item["buffer_code"] == buffer_code
    )


def _inventory(
    payload: dict[str, Any],
    buffer_code: str,
    product_name: str,
) -> dict[str, Any]:
    return next(
        item
        for item in payload["buffer_realtime"]
        if item["buffer_code"] == buffer_code
        and item["bound_source_name"] == product_name
    )


def _upsert_inventory(
    payload: dict[str, Any],
    *,
    buffer_code: str,
    product_name: str,
    quantity: float,
    capacity: float | None = None,
) -> None:
    matches = [
        item
        for item in payload["buffer_realtime"]
        if item["buffer_code"] == buffer_code
        and item["bound_source_name"] == product_name
    ]
    if matches:
        item = matches[0]
    else:
        item = {
            "main_id": f"MAIN-{buffer_code}",
            "buffer_code": buffer_code,
            "bound_source_name": product_name,
            "current_quantity": 0.0,
            "current_utilization_rate": 0.0,
        }
        payload["buffer_realtime"].append(item)
    max_capacity = capacity or _buffer(payload, buffer_code)["max_capacity"]
    item["current_quantity"] = float(quantity)
    item["current_utilization_rate"] = float(quantity) / max_capacity


def _upsert_parallel_inventory(
    payload: dict[str, Any],
    *,
    template_buffer_code: str,
    buffer_code: str,
    product_name: str,
    quantity: float,
    capacity: float | None = None,
) -> None:
    if not any(
        item["buffer_code"] == buffer_code
        for item in payload["buffer_master"]
    ):
        layer = deepcopy(_buffer(payload, template_buffer_code))
        layer["buffer_code"] = buffer_code
        if capacity is not None:
            layer["max_capacity"] = float(capacity)
        payload["buffer_master"].append(layer)
    _upsert_inventory(
        payload,
        buffer_code=buffer_code,
        product_name=product_name,
        quantity=quantity,
        capacity=capacity,
    )


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

    product_names = {
        item["order_code"]: item["product_name"]
        for item in payload["orders"]
    }
    payload["buffer_realtime"] = [
        item
        for item in payload["buffer_realtime"]
        if item["buffer_code"] != TARGET_BUFFER_CODE
    ]
    _upsert_parallel_inventory(
        payload,
        template_buffer_code=TARGET_BUFFER_CODE,
        buffer_code=SUPPORT_BUFFER_CODE,
        product_name=product_names[SUPPORT_ORDER_CODE],
        quantity=2000.0,
    )
    first_code, second_code = MULTILAYER_BUFFER_CODES
    payload["buffer_realtime"].extend(
        [
            {
                "main_id": MULTILAYER_MAIN_ID,
                "buffer_code": first_code,
                "bound_source_name": product_names[TARGET_ORDER_CODE],
                "current_quantity": 3600.0,
                "current_utilization_rate": 0.36,
            },
            {
                "main_id": MULTILAYER_MAIN_ID,
                "buffer_code": second_code,
                "bound_source_name": product_names[TARGET_ORDER_CODE],
                "current_quantity": 7200.0,
                "current_utilization_rate": 0.36,
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
        product_name="182N至上产品",
        quantity=100,
    )
    _upsert_parallel_inventory(
        payload,
        template_buffer_code=TARGET_BUFFER_CODE,
        buffer_code=SUPPORT_BUFFER_CODE,
        product_name="182N支援产品",
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
    product_names = {
        item["order_code"]: item["product_name"]
        for item in payload["orders"]
    }
    first_code, second_code = MULTILAYER_BUFFER_CODES
    payload["buffer_realtime"].extend(
        [
            {
                "main_id": MULTILAYER_MAIN_ID,
                "buffer_code": first_code,
                "bound_source_name": product_names[TARGET_ORDER_CODE],
                "current_quantity": 40.0,
                "current_utilization_rate": 0.0008,
            },
            {
                "main_id": MULTILAYER_MAIN_ID,
                "buffer_code": second_code,
                "bound_source_name": product_names[TARGET_ORDER_CODE],
                "current_quantity": 60.0,
                "current_utilization_rate": 0.0012,
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
        input_quantity=50,
        output_quantity=50,
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
        product_name="182N至上产品",
        quantity=450,
        capacity=1000,
    )
    _upsert_parallel_inventory(
        payload,
        template_buffer_code=TARGET_BUFFER_CODE,
        buffer_code=SUPPORT_BUFFER_CODE,
        product_name="182N支援产品",
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
        product_name="182N至上产品",
        quantity=950,
        capacity=1000,
    )
    _upsert_parallel_inventory(
        payload,
        template_buffer_code=TARGET_BUFFER_CODE,
        buffer_code=SUPPORT_BUFFER_CODE,
        product_name="182N支援产品",
        quantity=850,
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


def _order_product(
    payload: dict[str, Any],
    order_code: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    order = next(
        item for item in payload["orders"] if item["order_code"] == order_code
    )
    product = next(
        item
        for item in payload["products"]
        if item["product_code"] == order["product_code"]
    )
    return order, product


def _pending_baseline(
    payload: dict[str, Any],
    machine_code: str,
) -> dict[str, Any]:
    relation = next(
        item
        for item in payload["agv_relations"]
        if item["equipmentid"] == machine_code
    )
    order = next(
        item
        for item in payload["orders"]
        if item["product_name"] == relation["linename"]
    )
    _, product = _order_product(payload, order["order_code"])
    machine = next(
        item
        for item in payload["machine_master"]
        if item["machine_code"] == machine_code
    )
    return {
        "machine_code": machine_code,
        "order_code": order["order_code"],
        "product_code": product["product_code"],
        "product_name": product["product_name"],
        "wafer_size": product["wafer_size"],
        "wafer_spec": relation["waferspec"],
        "source_grade": product["source_grade"],
        "process_code": machine["process_code"],
        "workshop_code": "S2",
        "agv_record_time": CATALOG_TIME,
    }


def _round_one_pending_plan(payload: dict[str, Any]) -> dict[str, Any]:
    plan_id = _round_one_plan_id()
    target_order, target_product = _order_product(payload, TARGET_ORDER_CODE)
    support_order, support_product = _order_product(payload, SUPPORT_ORDER_CODE)
    candidate_baseline = _pending_baseline(payload, "EA004")
    return {
        "plan_id": plan_id,
        "warning_id": plan_id,
        "warning_type": "stockout",
        "warning_time": SNAPSHOT_TIME,
        "created_at": SNAPSHOT_TIME,
        "expire_at": "2026-07-17T08:30:00+08:00",
        "status": "PENDING",
        "workshop_code": "S2",
        "buffer_code": TARGET_BUFFER_CODE,
        "upstream_process_code": "制绒",
        "downstream_process_code": "碱抛",
        "monitored_order_code": target_order["order_code"],
        "before_machine_count": 1,
        "before_machine_codes": ["EA003"],
        "expected_machine_count": 2,
        "expected_delta_direction": "increase",
        "candidate_machines": [
            {
                "machine_code": "EA004",
                "baseline_order_code": support_order["order_code"],
                "baseline_product_code": support_product["product_code"],
                "baseline_product_name": support_product["product_name"],
                "baseline_wafer_size": support_product["wafer_size"],
                "baseline_wafer_spec": candidate_baseline["wafer_spec"],
                "baseline_source_grade": support_product["source_grade"],
                "expected_target_order_code": target_order["order_code"],
                "expected_target_product_code": target_product["product_code"],
                "expected_target_product_name": target_product["product_name"],
                "expected_target_wafer_size": target_product["wafer_size"],
                "expected_target_wafer_spec": "N",
                "expected_target_source_grade": target_product["source_grade"],
                "process_code": "制绒",
                "workshop_code": "S2",
                "source_buffer_code": SUPPORT_BUFFER_CODE,
                "target_buffer_code": TARGET_BUFFER_CODE,
                "target_upstream_process_code": "制绒",
                "target_downstream_process_code": "碱抛",
            }
        ],
        "baseline_machine_bindings": [
            _pending_baseline(payload, machine_code)
            for machine_code in ("EA003", "EA004", "EA023", "EA024")
        ],
        "confirmed_machine_codes": [],
    }


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
    payload["pending_cutline_plans"] = [_round_one_pending_plan(payload)]
    payload["active_cutline_events"] = []
    payload["agv_relations"].append(
        _agv_binding_record(
            payload,
            "EA004",
            TARGET_ORDER_CODE,
            previous_product_name="182N支援产品",
            wafer_spec="N",
            binding_time="2026-07-17 08:03:00",
        )
    )
    return payload


def build_return_recommended_payload() -> dict[str, Any]:
    payload = build_return_round_2_payload()
    payload["snapshot_meta"]["snapshot_time"] = "2026-07-17T08:26:00+08:00"
    payload["pending_cutline_plans"] = []
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
            "cutline_start_time": "2026-07-17T08:03:00+08:00",
            "negative_start_time": "2026-07-17T08:05:00+08:00",
        }
    ]
    _inventory(
        payload,
        TARGET_BUFFER_CODE,
        "182N至上产品",
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
        wafer_spec="N",
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
