from datetime import datetime

import pytest
from pydantic import BaseModel, ValidationError

from app.schemas import common_schema
from app.schemas import request_schema as schema
from app.schemas.pending_cutline_schema import PendingCutlinePlan


SNAPSHOT_FIELDS = (
    "current_time",
    "workshops",
    "lines",
    "machine_lines",
    "machine_runtimes",
    "machine_masters",
    "machine_product_capacities",
    "orders",
    "products",
    "process_routes",
    "buffer_masters",
    "buffer_process_relations",
    "buffer_order_inventories",
    "agv_relations",
    "pending_cutline_plans",
    "agv_binding_history",
    "active_cutline_events",
    "return_suggested_event_ids",
    "mixed_cutline_event_ids",
    "config",
)

CORE_LIST_FIELDS = SNAPSHOT_FIELDS[1:14]
REQUIRED_CORE_LIST_FIELDS = tuple(
    field
    for field in CORE_LIST_FIELDS
    if field not in {"lines", "machine_lines"}
)

SNAPSHOT_DESCRIPTIONS = {
    "current_time": "本次算法计算所使用的数据快照时间",
    "workshops": "算法使用的车间基础数据列表",
    "lines": (
        "可选兼容产线基础数据列表；兼容保留产线所属车间和硅片规格，"
        "但二者均不作为机台所属车间或当前生产规格的算法依据"
    ),
    "machine_lines": (
        "可选兼容机台与产线绑定关系列表，不作为核心算法的数据依据"
    ),
    "machine_runtimes": "快照时刻的机台实时运行状态列表",
    "machine_masters": "机台基础信息列表，包括机台所属工序",
    "machine_product_capacities": "机台与产品型号之间的工艺时间和实际产能关系列表",
    "orders": "算法使用的生产订单列表，订单未生产量由计划总量减去累计已生产量计算",
    "products": "算法使用的产品型号基础数据列表",
    "process_routes": "车间各循环中的工艺路线步骤列表，包括工序顺序和上下游工序关系",
    "buffer_masters": "物理小Buffer基础数据列表，包括容量、安全库存、服务工序和所属循环",
    "buffer_process_relations": "物理Buffer与所属车间、上下游工序区间之间的关系列表",
    "buffer_order_inventories": "当前快照时刻，各订单在各物理Buffer中的实时库存明细列表",
    "agv_relations": "算法使用的AGV调度关系列表",
    "pending_cutline_plans": "后端持久化并回传的待确认切线方案列表",
    "agv_binding_history": "待确认切线窗口内的AGV绑定历史列表",
    "active_cutline_events": "当前仍需跟踪的切线事件列表",
    "config": "切线算法运行参数配置",
    "return_suggested_event_ids": (
        "Backend-persisted event ids that already produced a return suggestion"
    ),
    "mixed_cutline_event_ids": (
        "Backend-persisted event ids that already produced a real mixing record"
    ),
}

LIST_MODEL_TYPES = {
    "workshops": common_schema.AlgorithmWorkshop,
    "lines": common_schema.AlgorithmLine,
    "machine_lines": common_schema.AlgorithmMachineLineRelation,
    "machine_runtimes": common_schema.AlgorithmMachineRuntime,
    "machine_masters": common_schema.AlgorithmMachineMaster,
    "machine_product_capacities": common_schema.AlgorithmMachineProductCapacity,
    "orders": common_schema.AlgorithmOrder,
    "products": common_schema.AlgorithmProduct,
    "process_routes": common_schema.AlgorithmProcessRoute,
    "buffer_masters": common_schema.AlgorithmBufferMaster,
    "buffer_process_relations": common_schema.AlgorithmBufferProcessRelation,
    "buffer_order_inventories": common_schema.AlgorithmBufferOrderInventory,
    "agv_relations": common_schema.AlgorithmAgvRelation,
}

CUTLINE_REQUEST_FIELDS = (
    "snapshot_meta",
    "machine_realtime",
    "machine_master",
    "machine_process_times",
    "workshops",
    "lines",
    "machine_lines",
    "orders",
    "products",
    "process_routes",
    "buffer_realtime",
    "buffer_master",
    "agv_relations",
    "pending_cutline_plans",
    "active_cutline_events",
    "return_suggested_event_ids",
    "mixed_cutline_event_ids",
)

@pytest.fixture
def snapshot_payload():
    return {
        "current_time": "2026-07-15T09:00:00+08:00",
        "workshops": [
            {
                "workshop_code": "WS-01",
                "workshop_name": "一车间",
            }
        ],
        "lines": [
            {
                "line_code": "LINE-N",
                "line_name": "N产线",
                "wafer_spec": "N",
                "workshop_code": "WS-01",
                "workshop_name": "一车间",
            }
        ],
        "machine_lines": [
            {
                "machine_code": "MC-01",
                "line_code": "LINE-N",
            }
        ],
        "machine_runtimes": [
            {
                "machine_code": "MC-01",
                "status": "RUNNING",
                "current_order_code": "ORD-01",
                "tangent_time": None,
                "input_quantity_30m": 120,
                "output_quantity_30m": 100,
                "period_quantity_30m": 400,
                "out_time": None,
            }
        ],
        "machine_masters": [
            {
                "machine_code": "MC-01",
                "machine_name": "机台一",
                "process_code": "PROC-01",
                "process_name": "工序一",
            }
        ],
        "machine_product_capacities": [
            {
                "machine_code": "MC-01",
                "product_code": "PROD-01",
                "proc_seconds": 30,
                "actual_capacity": 120,
            }
        ],
        "orders": [
            {
                "order_code": "ORD-01",
                "order_status": "生产中",
                "product_code": "PROD-01",
                "product_name": "产品一",
                "workshop_code": "WS-01",
                "workshop_name": "一车间",
                "total_quantity": 3000,
                "produced_quantity": 700,
                "piece_source": "自产",
                "estimated_yield": "98.5%",
            },
            {
                "order_code": "ORD-02",
                "order_status": "待生产",
                "product_code": "PROD-01",
                "product_name": "产品一",
                "workshop_code": "WS-01",
                "workshop_name": "一车间",
                "total_quantity": 2000,
                "produced_quantity": 0,
                "piece_source": "自产",
                "estimated_yield": "98.5%",
            },
        ],
        "products": [
            {
                "product_code": "PROD-01",
                "product_name": "产品一",
                "wafer_size": "182",
                "source_grade": "A",
                "material_code": "MAT-01",
                "material_name": "物料一",
            }
        ],
        "process_routes": [
            {
                "process_code": "PROC-01",
                "process_name": "工序一",
                "sequence": 1,
                "cache_type": "BUFFER",
                "workshop_code": "WS-01",
                "workshop_name": "一车间",
                "loop_code": "LOOP-01",
                "loop_name": "循环一",
                "upstream_process_code": None,
                "upstream_process_name": None,
                "downstream_process_code": None,
                "downstream_process_name": None,
            }
        ],
        "buffer_masters": [
            {
                "buffer_code": "BUF-A",
                "buffer_name": "缓存A",
                "buffer_type": "LINE",
                "buffer_type_title": "线边缓存",
                "max_capacity": 3000,
                "safety_low": 100,
                "served_process_codes": ["PROC-01", "PROC-02"],
                "served_process_names": ["工序一", "工序二"],
                "loop_code": "LOOP-01",
                "loop_name": "循环一",
            },
            {
                "buffer_code": "BUF-B",
                "buffer_name": "缓存B",
                "buffer_type": "LINE",
                "buffer_type_title": "线边缓存",
                "max_capacity": 3000,
                "safety_low": 100,
                "served_process_codes": ["PROC-02", "PROC-03"],
                "served_process_names": ["工序二", "工序三"],
                "loop_code": "LOOP-01",
                "loop_name": "循环一",
            },
        ],
        "buffer_process_relations": [
            {
                "buffer_code": "BUF-A",
                "workshop_code": "WS-01",
                "upstream_process_code": "PROC-01",
                "downstream_process_code": "PROC-02",
            },
            {
                "buffer_code": "BUF-B",
                "workshop_code": "WS-01",
                "upstream_process_code": "PROC-02",
                "downstream_process_code": "PROC-03",
            },
        ],
        "buffer_order_inventories": [
            {
                "main_id": "MAIN-A",
                "buffer_code": "BUF-A",
                "order_code": "ORD-01",
                "current_quantity": 1000,
            },
            {
                "main_id": "MAIN-B",
                "buffer_code": "BUF-B",
                "order_code": "ORD-01",
                "current_quantity": 800,
            },
            {
                "main_id": "MAIN-B",
                "buffer_code": "BUF-B",
                "order_code": "ORD-02",
                "current_quantity": 600,
            },
        ],
        "agv_relations": [
            {
                "machine_code": "MC-01",
                "machine_name": "一号机",
                "order_code": "ORD-01",
                "product_code": "PROD-01",
                "product_name": "产品一",
                "wafer_spec": "N",
                "binding_time": "2026-07-15T08:55:00+08:00",
            }
        ],
    }


def test_minimal_complete_algorithm_snapshot_parses_typed_data(snapshot_payload):
    snapshot = schema.AlgorithmSnapshot.model_validate(snapshot_payload)

    assert isinstance(snapshot.current_time, datetime)
    for field_name, model_type in LIST_MODEL_TYPES.items():
        assert getattr(snapshot, field_name)
        assert isinstance(getattr(snapshot, field_name)[0], model_type)


def test_algorithm_snapshot_parses_typed_pending_and_agv_history(snapshot_payload):
    snapshot_payload["pending_cutline_plans"] = [
        {
            "plan_id": "PLAN-01",
            "warning_id": "WARN-01",
            "warning_type": "stockout",
            "warning_time": "2026-07-15T08:59:00+08:00",
            "created_at": "2026-07-15T09:00:00+08:00",
            "expire_at": "2026-07-15T09:30:00+08:00",
            "status": "PENDING",
            "workshop_code": "WS-01",
            "buffer_code": "BUF-A",
            "upstream_process_code": "PROC-01",
            "downstream_process_code": "PROC-02",
            "monitored_order_code": "ORD-01",
            "before_machine_count": 0,
            "before_machine_codes": [],
            "expected_machine_count": 1,
            "expected_delta_direction": "increase",
        }
    ]
    snapshot_payload["agv_binding_history"] = [
        {
            **snapshot_payload["agv_relations"][0],
            "previous_product_code": "PROD-OLD",
            "previous_product_name": "old-product",
        }
    ]

    snapshot = schema.AlgorithmSnapshot.model_validate(snapshot_payload)

    assert isinstance(snapshot.pending_cutline_plans[0], PendingCutlinePlan)
    assert isinstance(
        snapshot.agv_binding_history[0],
        common_schema.AlgorithmAgvRelation,
    )
    assert snapshot.agv_binding_history[0].previous_product_code == "PROD-OLD"


def test_algorithm_snapshot_has_exact_field_order_and_descriptions():
    snapshot_model = schema.AlgorithmSnapshot

    assert snapshot_model.__bases__ == (BaseModel,)
    assert tuple(snapshot_model.model_fields) == SNAPSHOT_FIELDS
    assert {
        name: field.description for name, field in snapshot_model.model_fields.items()
    } == SNAPSHOT_DESCRIPTIONS


@pytest.mark.parametrize(
    "missing_field",
    ("current_time", *REQUIRED_CORE_LIST_FIELDS),
)
def test_algorithm_snapshot_requires_current_time_and_all_core_lists(
    snapshot_payload,
    missing_field,
):
    del snapshot_payload[missing_field]

    with pytest.raises(ValidationError):
        schema.AlgorithmSnapshot.model_validate(snapshot_payload)


def test_algorithm_snapshot_allows_explicit_empty_core_lists(snapshot_payload):
    for field_name in CORE_LIST_FIELDS:
        snapshot_payload[field_name] = []

    snapshot = schema.AlgorithmSnapshot.model_validate(snapshot_payload)

    assert all(getattr(snapshot, field_name) == [] for field_name in CORE_LIST_FIELDS)


def test_algorithm_snapshot_optional_line_lists_default_independently(
    snapshot_payload,
):
    snapshot_payload.pop("lines")
    snapshot_payload.pop("machine_lines")

    first = schema.AlgorithmSnapshot.model_validate(snapshot_payload)
    second = schema.AlgorithmSnapshot.model_validate(snapshot_payload)

    assert first.lines == []
    assert first.machine_lines == []
    assert first.lines is not second.lines
    assert first.machine_lines is not second.machine_lines
    assert schema.AlgorithmSnapshot.model_fields["lines"].default_factory is list
    assert (
        schema.AlgorithmSnapshot.model_fields[
            "machine_lines"
        ].default_factory
        is list
    )


def test_algorithm_snapshot_uses_only_allowed_defaults(snapshot_payload):
    first = schema.AlgorithmSnapshot.model_validate(snapshot_payload)
    second = schema.AlgorithmSnapshot.model_validate(snapshot_payload)

    assert first.active_cutline_events == []
    assert first.active_cutline_events is not second.active_cutline_events
    assert first.pending_cutline_plans == []
    assert first.pending_cutline_plans is not second.pending_cutline_plans
    assert first.agv_binding_history == []
    assert first.agv_binding_history is not second.agv_binding_history
    assert first.config.model_dump() == common_schema.AlgorithmConfig().model_dump()
    assert all(
        schema.AlgorithmSnapshot.model_fields[name].is_required()
        for name in ("current_time", *REQUIRED_CORE_LIST_FIELDS)
    )
    assert not schema.AlgorithmSnapshot.model_fields["lines"].is_required()
    assert not schema.AlgorithmSnapshot.model_fields[
        "machine_lines"
    ].is_required()
    assert not schema.AlgorithmSnapshot.model_fields[
        "active_cutline_events"
    ].is_required()
    assert not schema.AlgorithmSnapshot.model_fields[
        "pending_cutline_plans"
    ].is_required()
    assert not schema.AlgorithmSnapshot.model_fields[
        "agv_binding_history"
    ].is_required()
    assert schema.AlgorithmSnapshot.model_fields[
        "pending_cutline_plans"
    ].default_factory is list
    assert schema.AlgorithmSnapshot.model_fields[
        "agv_binding_history"
    ].default_factory is list
    assert not schema.AlgorithmSnapshot.model_fields["config"].is_required()


def test_algorithm_snapshot_excludes_buffer_results():
    fields = set(schema.AlgorithmSnapshot.model_fields)

    assert "buffer_runtimes" not in fields
    assert "buffer_total_quantities" not in fields
    assert "buffer_utilization_rates" not in fields
    assert "overflow_results" not in fields
    assert not hasattr(schema, "AlgorithmBufferRuntime")


def test_snapshot_inventory_supports_buffer_order_many_to_many(snapshot_payload):
    snapshot = schema.AlgorithmSnapshot.model_validate(snapshot_payload)

    order_01_buffers = {
        item.buffer_code
        for item in snapshot.buffer_order_inventories
        if item.order_code == "ORD-01"
    }
    buffer_b_orders = {
        item.order_code
        for item in snapshot.buffer_order_inventories
        if item.buffer_code == "BUF-B"
    }

    assert order_01_buffers == {"BUF-A", "BUF-B"}
    assert buffer_b_orders == {"ORD-01", "ORD-02"}


def test_inventory_records_use_snapshot_time_without_duplicate_time_fields(
    snapshot_payload,
):
    snapshot = schema.AlgorithmSnapshot.model_validate(snapshot_payload)

    assert snapshot.current_time == datetime.fromisoformat(
        "2026-07-15T09:00:00+08:00"
    )
    assert all(
        tuple(item.model_fields)
        == ("main_id", "buffer_code", "order_code", "current_quantity")
        for item in snapshot.buffer_order_inventories
    )


def test_cutline_algorithm_request_has_expected_contract_fields():
    assert tuple(schema.CutlineAlgorithmRequest.model_fields) == CUTLINE_REQUEST_FIELDS
