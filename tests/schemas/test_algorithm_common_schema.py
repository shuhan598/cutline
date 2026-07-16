from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas import common_schema as schema


ALGORITHM_MODEL_FIELDS = {
    "AlgorithmWorkshop": ("workshop_code", "workshop_name"),
    "AlgorithmLine": (
        "line_code",
        "line_name",
        "wafer_spec",
        "workshop_code",
        "workshop_name",
    ),
    "AlgorithmMachineLineRelation": ("machine_code", "line_code"),
    "AlgorithmMachineRuntime": (
        "machine_code",
        "status",
        "current_order_code",
        "tangent_time",
        "input_quantity_30m",
        "output_quantity_30m",
        "period_quantity_30m",
        "out_time",
    ),
    "AlgorithmMachineMaster": (
        "machine_code",
        "machine_name",
        "process_code",
        "process_name",
    ),
    "AlgorithmMachineProductCapacity": (
        "machine_code",
        "product_code",
        "proc_seconds",
        "actual_capacity",
    ),
    "AlgorithmOrder": (
        "order_code",
        "order_name",
        "order_status",
        "product_code",
        "product_name",
        "workshop_code",
        "workshop_name",
        "total_quantity",
        "produced_quantity",
        "piece_source",
        "estimated_yield",
    ),
    "AlgorithmProduct": (
        "product_code",
        "product_name",
        "wafer_size",
        "source_grade",
        "material_code",
        "material_name",
    ),
    "AlgorithmProcessRoute": (
        "process_code",
        "process_name",
        "sequence",
        "cache_type",
        "workshop_code",
        "workshop_name",
        "loop_code",
        "loop_name",
        "upstream_process_code",
        "upstream_process_name",
        "downstream_process_code",
        "downstream_process_name",
    ),
    "AlgorithmBufferMaster": (
        "buffer_code",
        "buffer_name",
        "buffer_type",
        "buffer_type_title",
        "max_capacity",
        "safety_low",
        "served_process_codes",
        "served_process_names",
        "loop_code",
        "loop_name",
    ),
    "AlgorithmBufferProcessRelation": (
        "buffer_code",
        "workshop_code",
        "upstream_process_code",
        "downstream_process_code",
    ),
    "AlgorithmBufferOrderInventory": (
        "buffer_code",
        "order_code",
        "current_quantity",
    ),
    "AlgorithmAgvRelation": (
        "buffer_code",
        "machine_code",
        "line_code",
        "line_name",
        "last_line_code",
        "last_line_name",
        "process_code",
        "process_name",
    ),
}


def _runtime_payload(**updates):
    payload = {
        "machine_code": "MC-01",
        "status": "RUNNING",
        "current_order_code": "ORD-01",
        "tangent_time": datetime(2026, 7, 15, 8, 30),
        "input_quantity_30m": 120.0,
        "output_quantity_30m": 100.0,
        "period_quantity_30m": 400.0,
        "out_time": None,
    }
    payload.update(updates)
    return payload


def _order_payload(**updates):
    payload = {
        "order_code": "ORD-01",
        "order_name": "订单一",
        "order_status": "生产中",
        "product_code": "PROD-01",
        "product_name": "产品一",
        "workshop_code": "WS-01",
        "workshop_name": "一车间",
        "total_quantity": 1000.0,
        "produced_quantity": 400.0,
        "piece_source": "自产",
        "estimated_yield": "98.5%",
    }
    payload.update(updates)
    return payload


def _buffer_master_payload(**updates):
    payload = {
        "buffer_code": "BUF-A",
        "buffer_name": "一号缓存区",
        "buffer_type": "LINE",
        "buffer_type_title": "线边缓存",
        "max_capacity": 2000.0,
        "safety_low": 100.0,
        "served_process_codes": ["PROC-01", "PROC-02"],
        "served_process_names": ["工序一", "工序二"],
        "loop_code": "LOOP-01",
        "loop_name": "循环一",
    }
    payload.update(updates)
    return payload


@pytest.mark.parametrize(
    ("model_name", "expected_fields"),
    ALGORITHM_MODEL_FIELDS.items(),
)
def test_algorithm_models_have_exact_required_fields(model_name, expected_fields):
    model = getattr(schema, model_name)

    assert issubclass(model, schema.AlgorithmModel)
    assert tuple(model.model_fields) == expected_fields
    assert all(field.is_required() for field in model.model_fields.values())
    assert model.model_config["extra"] == "forbid"


def test_algorithm_model_field_types_and_nullable_contracts_are_explicit():
    nullable_string_fields = {
        ("AlgorithmWorkshop", "workshop_name"),
        ("AlgorithmLine", "workshop_name"),
        ("AlgorithmMachineRuntime", "current_order_code"),
        ("AlgorithmOrder", "workshop_name"),
        ("AlgorithmProcessRoute", "workshop_name"),
        ("AlgorithmProcessRoute", "upstream_process_code"),
        ("AlgorithmProcessRoute", "upstream_process_name"),
        ("AlgorithmProcessRoute", "downstream_process_code"),
        ("AlgorithmProcessRoute", "downstream_process_name"),
        ("AlgorithmAgvRelation", "buffer_code"),
        ("AlgorithmAgvRelation", "line_name"),
        ("AlgorithmAgvRelation", "last_line_code"),
        ("AlgorithmAgvRelation", "last_line_name"),
        ("AlgorithmAgvRelation", "process_code"),
        ("AlgorithmAgvRelation", "process_name"),
    }
    special_types = {
        ("AlgorithmMachineRuntime", "tangent_time"): datetime | None,
        ("AlgorithmMachineRuntime", "out_time"): datetime | None,
        ("AlgorithmMachineRuntime", "input_quantity_30m"): float,
        ("AlgorithmMachineRuntime", "output_quantity_30m"): float,
        ("AlgorithmMachineRuntime", "period_quantity_30m"): float,
        ("AlgorithmMachineProductCapacity", "proc_seconds"): float,
        ("AlgorithmMachineProductCapacity", "actual_capacity"): float,
        ("AlgorithmOrder", "total_quantity"): float,
        ("AlgorithmOrder", "produced_quantity"): float,
        ("AlgorithmProcessRoute", "sequence"): int,
        ("AlgorithmBufferMaster", "max_capacity"): float,
        ("AlgorithmBufferMaster", "safety_low"): float,
        ("AlgorithmBufferMaster", "served_process_codes"): list[str],
        ("AlgorithmBufferMaster", "served_process_names"): list[str],
        ("AlgorithmBufferOrderInventory", "current_quantity"): float,
    }

    for model_name, field_names in ALGORITHM_MODEL_FIELDS.items():
        model = getattr(schema, model_name)
        for field_name in field_names:
            key = (model_name, field_name)
            expected_type = special_types.get(
                key,
                str | None if key in nullable_string_fields else str,
            )
            assert model.model_fields[field_name].annotation == expected_type


def test_algorithm_models_and_fields_have_chinese_documentation():
    def contains_chinese(value):
        return any("\u4e00" <= character <= "\u9fff" for character in value)

    for model_name in ALGORITHM_MODEL_FIELDS:
        model = getattr(schema, model_name)
        assert model.__doc__ and contains_chinese(model.__doc__)
        assert all(
            field.description and contains_chinese(field.description)
            for field in model.model_fields.values()
        )


def test_algorithm_line_accepts_n_r_and_p_wafer_specs():
    for wafer_spec in ("N", "R", "P"):
        line = schema.AlgorithmLine(
            line_code=f"LINE-{wafer_spec}",
            line_name=f"{wafer_spec}产线",
            wafer_spec=wafer_spec,
            workshop_code="WS-01",
            workshop_name=None,
        )

        assert line.wafer_spec == wafer_spec


def test_algorithm_line_requires_wafer_spec():
    with pytest.raises(ValidationError):
        schema.AlgorithmLine(
            line_code="LINE-N",
            line_name="N产线",
            workshop_code="WS-01",
            workshop_name=None,
        )


def test_algorithm_line_wafer_spec_description_matches_business_rule():
    assert schema.AlgorithmLine.model_fields["wafer_spec"].description == (
        "产线绑定的硅片规格，用于判断该产线机台对应的 N、R、P 规格"
    )


def test_machine_line_relation_links_machine_to_line_by_codes_only():
    relation = schema.AlgorithmMachineLineRelation(
        machine_code="MC-01",
        line_code="LINE-N",
    )

    assert relation.model_dump() == {
        "machine_code": "MC-01",
        "line_code": "LINE-N",
    }


def test_machine_runtime_can_be_created_with_nullable_values():
    runtime = schema.AlgorithmMachineRuntime(
        **_runtime_payload(current_order_code=None, tangent_time=None, out_time=None)
    )

    assert runtime.current_order_code is None
    assert runtime.tangent_time is None
    assert runtime.out_time is None


@pytest.mark.parametrize(
    "field",
    ("input_quantity_30m", "output_quantity_30m", "period_quantity_30m"),
)
def test_machine_runtime_rejects_negative_quantities(field):
    with pytest.raises(ValidationError):
        schema.AlgorithmMachineRuntime(**_runtime_payload(**{field: -1}))


def test_machine_runtime_rejects_removed_period_quantity():
    with pytest.raises(ValidationError) as error:
        schema.AlgorithmMachineRuntime(**_runtime_payload(period_quantity=1))

    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_machine_runtime_rejects_request_only_completed_quantity():
    with pytest.raises(ValidationError) as error:
        schema.AlgorithmMachineRuntime(**_runtime_payload(completed_quantity=1))

    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_machine_runtime_accepts_out_time():
    out_time = datetime(2026, 7, 15, 8, 30)

    runtime = schema.AlgorithmMachineRuntime(**_runtime_payload(out_time=out_time))

    assert runtime.out_time == out_time


def test_algorithm_models_reject_unknown_fields():
    with pytest.raises(ValidationError) as error:
        schema.AlgorithmWorkshop(
            workshop_code="WS-01",
            workshop_name=None,
            unexpected="value",
        )

    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_machine_product_capacity_allows_zero_process_duration():
    capacity = schema.AlgorithmMachineProductCapacity(
        machine_code="MC-01",
        product_code="PROD-01",
        proc_seconds=0,
        actual_capacity=120.0,
    )

    assert capacity.proc_seconds == 0


def test_machine_product_capacity_requires_positive_actual_capacity():
    payload = {
        "machine_code": "MC-01",
        "product_code": "PROD-01",
        "proc_seconds": 30.0,
        "actual_capacity": 120.0,
    }
    payload["actual_capacity"] = 0

    with pytest.raises(ValidationError):
        schema.AlgorithmMachineProductCapacity(**payload)


@pytest.mark.parametrize("field", ("order_name", "product_name", "workshop_name"))
def test_algorithm_order_requires_name_fields(field):
    payload = _order_payload()
    del payload[field]

    with pytest.raises(ValidationError):
        schema.AlgorithmOrder(**payload)


def test_algorithm_order_accepts_null_workshop_name():
    order = schema.AlgorithmOrder(**_order_payload(workshop_name=None))

    assert order.workshop_name is None


def test_algorithm_order_computes_remaining_quantity():
    order = schema.AlgorithmOrder(**_order_payload())

    assert order.remaining_quantity == 600.0
    assert order.model_dump()["remaining_quantity"] == 600.0
    assert schema.AlgorithmOrder.model_computed_fields[
        "remaining_quantity"
    ].description == "订单未生产数量，由订单计划总量减去订单累计已生产量计算得到"


def test_algorithm_order_rejects_produced_quantity_above_total():
    with pytest.raises(ValidationError):
        schema.AlgorithmOrder(
            **_order_payload(total_quantity=1000.0, produced_quantity=1000.1)
        )


@pytest.mark.parametrize("field", ("total_quantity", "produced_quantity"))
def test_algorithm_order_rejects_negative_quantities(field):
    with pytest.raises(ValidationError):
        schema.AlgorithmOrder(**_order_payload(**{field: -1}))


def test_algorithm_order_rejects_remaining_quantity_input():
    with pytest.raises(ValidationError) as error:
        schema.AlgorithmOrder(**_order_payload(remaining_quantity=1.0))

    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_buffer_master_descriptions_match_document_terms():
    assert schema.AlgorithmBufferMaster.model_fields["buffer_type"].description == (
        "Buffer类型"
    )
    assert schema.AlgorithmBufferMaster.model_fields[
        "buffer_type_title"
    ].description == "Buffer类型_类型"


def test_algorithm_process_route_requires_positive_sequence():
    with pytest.raises(ValidationError):
        schema.AlgorithmProcessRoute(
            process_code="PROC-01",
            process_name="工序一",
            sequence=0,
            cache_type="BUFFER",
            workshop_code="WS-01",
            workshop_name=None,
            loop_code="LOOP-01",
            loop_name="循环一",
            upstream_process_code=None,
            upstream_process_name=None,
            downstream_process_code=None,
            downstream_process_name=None,
        )


def test_buffer_master_requires_positive_capacity():
    with pytest.raises(ValidationError):
        schema.AlgorithmBufferMaster(**_buffer_master_payload(max_capacity=0))


def test_buffer_master_rejects_negative_safety_low():
    with pytest.raises(ValidationError):
        schema.AlgorithmBufferMaster(**_buffer_master_payload(safety_low=-1))


def test_algorithm_buffer_runtime_is_not_defined():
    assert not hasattr(schema, "AlgorithmBufferRuntime")


def test_buffer_order_inventory_rejects_negative_quantity():
    with pytest.raises(ValidationError):
        schema.AlgorithmBufferOrderInventory(
            buffer_code="BUF-A",
            order_code="ORD-01",
            current_quantity=-1,
        )


def test_buffer_order_inventory_supports_many_to_many_relationship():
    inventories = [
        schema.AlgorithmBufferOrderInventory(
            buffer_code="BUF-A", order_code="ORD-01", current_quantity=1000
        ),
        schema.AlgorithmBufferOrderInventory(
            buffer_code="BUF-B", order_code="ORD-01", current_quantity=800
        ),
        schema.AlgorithmBufferOrderInventory(
            buffer_code="BUF-B", order_code="ORD-02", current_quantity=600
        ),
        schema.AlgorithmBufferOrderInventory(
            buffer_code="BUF-C", order_code="ORD-01", current_quantity=500
        ),
    ]

    order_01_buffers = {
        item.buffer_code for item in inventories if item.order_code == "ORD-01"
    }
    buffer_b_orders = {
        item.order_code for item in inventories if item.buffer_code == "BUF-B"
    }
    buffer_b_total = sum(
        item.current_quantity for item in inventories if item.buffer_code == "BUF-B"
    )
    order_01_total = sum(
        item.current_quantity for item in inventories if item.order_code == "ORD-01"
    )

    assert order_01_buffers == {"BUF-A", "BUF-B", "BUF-C"}
    assert buffer_b_orders == {"ORD-01", "ORD-02"}
    assert buffer_b_total == 1400
    assert order_01_total == 2300


def test_buffer_process_relations_support_interval_lookup():
    relations = [
        schema.AlgorithmBufferProcessRelation(
            buffer_code="BUF-A",
            workshop_code="WS-01",
            upstream_process_code="PROC-01",
            downstream_process_code="PROC-02",
        ),
        schema.AlgorithmBufferProcessRelation(
            buffer_code="BUF-B",
            workshop_code="WS-01",
            upstream_process_code="PROC-02",
            downstream_process_code="PROC-03",
        ),
        schema.AlgorithmBufferProcessRelation(
            buffer_code="BUF-C",
            workshop_code="WS-01",
            upstream_process_code="PROC-03",
            downstream_process_code="PROC-04",
        ),
    ]

    intervals = {
        item.buffer_code: (
            item.upstream_process_code,
            item.downstream_process_code,
        )
        for item in relations
    }

    assert intervals == {
        "BUF-A": ("PROC-01", "PROC-02"),
        "BUF-B": ("PROC-02", "PROC-03"),
        "BUF-C": ("PROC-03", "PROC-04"),
    }


def test_algorithm_config_time_parameter_defaults_are_floats():
    config = schema.AlgorithmConfig()

    assert all(
        isinstance(value, float)
        for value in (
            config.stockout_warning_lead_minutes,
            config.overflow_warning_lead_minutes,
            config.stability_window_minutes,
            config.silk_screen_clear_minutes,
        )
    )


def test_algorithm_config_cutline_execution_delay_defaults_to_immediate_cutline():
    config = schema.AlgorithmConfig()

    assert config.cutline_execution_delay_minutes == 0.0
    assert schema.AlgorithmConfig.model_fields[
        "cutline_execution_delay_minutes"
    ].description == "当前默认方案生成后立即切线，单位：分钟"


@pytest.mark.parametrize("valid_value", [0, 7.5])
def test_algorithm_config_cutline_execution_delay_accepts_non_negative_values(
    valid_value: float,
):
    config = schema.AlgorithmConfig(cutline_execution_delay_minutes=valid_value)

    assert config.cutline_execution_delay_minutes == valid_value


@pytest.mark.parametrize(
    "invalid_value",
    [-0.1, float("nan"), float("inf"), float("-inf"), True, "0"],
)
def test_algorithm_config_cutline_execution_delay_rejects_invalid_values(
    invalid_value: float | bool | str,
):
    with pytest.raises(ValidationError):
        schema.AlgorithmConfig(cutline_execution_delay_minutes=invalid_value)


@pytest.mark.parametrize(
    "field_name",
    [
        "stockout_warning_lead_minutes",
        "overflow_warning_lead_minutes",
        "stability_window_minutes",
        "silk_screen_clear_minutes",
    ],
)
@pytest.mark.parametrize(
    "invalid_value",
    [0, -1, float("nan"), float("inf"), float("-inf"), True, "30"],
)
def test_algorithm_config_time_parameters_require_finite_positive_non_boolean_values(
    field_name: str,
    invalid_value: float | bool | str,
):
    with pytest.raises(ValidationError):
        schema.AlgorithmConfig(**{field_name: invalid_value})
