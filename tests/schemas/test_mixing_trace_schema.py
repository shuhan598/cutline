from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas import common_schema, result_schema


def test_mixing_config_defaults_are_business_defaults():
    config = common_schema.AlgorithmConfig()

    assert config.cutline_execution_delay_minutes == 0
    assert config.agv_delivery_minutes == 5
    assert config.mixed_basket_count == 10
    assert config.basket_capacity_pieces == 120
    assert config.mixing_input_max_baskets == 10


def test_mixing_duration_config_defaults_are_floats():
    config = common_schema.AlgorithmConfig()

    assert type(config.cutline_execution_delay_minutes) is float
    assert type(config.agv_delivery_minutes) is float


@pytest.mark.parametrize(
    "field_name",
    ("cutline_execution_delay_minutes", "agv_delivery_minutes"),
)
def test_mixing_duration_config_allows_zero(field_name):
    config = common_schema.AlgorithmConfig(**{field_name: 0})

    assert getattr(config, field_name) == 0


@pytest.mark.parametrize(
    "field_name",
    ("cutline_execution_delay_minutes", "agv_delivery_minutes"),
)
@pytest.mark.parametrize(
    "invalid_value",
    (-1, float("nan"), float("inf"), float("-inf"), True),
)
def test_mixing_duration_config_rejects_invalid_values(
    field_name,
    invalid_value,
):
    with pytest.raises(ValidationError):
        common_schema.AlgorithmConfig(**{field_name: invalid_value})


@pytest.mark.parametrize(
    "field_name",
    (
        "mixed_basket_count",
        "basket_capacity_pieces",
        "mixing_input_max_baskets",
    ),
)
@pytest.mark.parametrize("invalid_value", (0, -1, 1.5, True))
def test_mixing_count_config_requires_positive_non_boolean_integer(
    field_name,
    invalid_value,
):
    with pytest.raises(ValidationError):
        common_schema.AlgorithmConfig(**{field_name: invalid_value})


@pytest.mark.parametrize(
    "invalid_value",
    (-1, float("nan"), float("inf"), float("-inf"), True),
)
def test_process_duration_rejects_invalid_values(invalid_value):
    with pytest.raises(ValidationError):
        common_schema.AlgorithmMachineProductCapacity(
            machine_code="M01",
            product_code="P01",
            proc_seconds=invalid_value,
            actual_capacity=1,
        )


@pytest.mark.parametrize(
    "field_name",
    ("input_quantity_30m", "output_quantity_30m"),
)
def test_runtime_quantities_reject_boolean_before_coercion(field_name):
    payload = {
        "machine_code": "M01",
        "status": "running",
        "current_order_code": "O1",
        "tangent_time": None,
        "input_quantity_30m": 1,
        "output_quantity_30m": 1,
        "out_time": None,
    }
    payload[field_name] = True

    with pytest.raises(ValidationError):
        common_schema.AlgorithmMachineRuntime(**payload)


def test_mixing_trace_record_has_only_compact_business_fields():
    expected = {
        "mix_trace_id",
        "plan_id",
        "cutline_event_id",
        "machine_code",
        "workshop_code",
        "process_code",
        "process_name",
        "source_order_code",
        "target_order_code",
        "source_product_code",
        "target_product_code",
        "mix_start_time",
        "mixed_basket_start_index",
        "mixed_basket_end_index",
        "mixed_basket_count",
        "estimated_total_mixed_pieces",
        "compositions",
        "notification_status",
    }

    assert set(result_schema.AlgorithmMixingTraceRecord.model_fields) == expected


def test_mixing_trace_result_models_have_expected_fields():
    assert set(result_schema.AlgorithmMixingComposition.model_fields) == {
        "order_code",
        "product_code",
        "sequence",
        "estimated_pieces",
    }
    assert set(result_schema.AlgorithmMixingTraceFailure.model_fields) == {
        "plan_id",
        "cutline_event_id",
        "machine_code",
        "source_order_code",
        "target_order_code",
        "reason",
        "message",
    }
    assert set(result_schema.AlgorithmMixingTraceBatchResult.model_fields) == {
        "records",
        "failures",
    }


def test_mixing_trace_record_accepts_only_supported_notification_statuses():
    payload = {
        "mix_trace_id": "MIX-P1-M1",
        "plan_id": "P1",
        "cutline_event_id": "CUT-P1-M1",
        "machine_code": "M1",
        "workshop_code": "S1",
        "process_code": "P01",
        "process_name": "制绒",
        "source_order_code": "O1",
        "target_order_code": "O2",
        "source_product_code": "A",
        "target_product_code": "B",
        "mix_start_time": datetime(2026, 7, 16, 10, 0),
        "mixed_basket_start_index": 1,
        "mixed_basket_end_index": 10,
        "mixed_basket_count": 10,
        "estimated_total_mixed_pieces": 1200,
        "compositions": [
            {
                "order_code": "O1",
                "product_code": "A",
                "sequence": 1,
                "estimated_pieces": 600,
            },
            {
                "order_code": "O2",
                "product_code": "B",
                "sequence": 2,
                "estimated_pieces": 600,
            },
        ],
        "notification_status": "sent",
    }

    with pytest.raises(ValidationError):
        result_schema.AlgorithmMixingTraceRecord(**payload)
