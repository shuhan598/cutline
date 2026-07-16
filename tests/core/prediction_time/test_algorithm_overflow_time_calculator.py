from datetime import datetime

import pytest

import app.core.prediction_time.overflow_time.overflow_time_calculator as overflow_module
from app.schemas.common_schema import (
    AlgorithmBufferMaster,
    AlgorithmBufferProcessRelation,
)
from app.schemas.request_schema import AlgorithmSnapshot
from app.schemas.result_schema import AlgorithmIntervalNetRateResult


def _buffer(
    buffer_code: str = "BUF-01",
    max_capacity: float = 10000,
) -> AlgorithmBufferMaster:
    return AlgorithmBufferMaster(
        buffer_code=buffer_code,
        buffer_name=buffer_code,
        buffer_type="LINE",
        buffer_type_title="线边库",
        max_capacity=max_capacity,
        safety_low=0,
        served_process_codes=["ZR", "PK"],
        served_process_names=["制绒", "硼扩"],
        loop_code="LOOP-1",
        loop_name="循环一",
    )


def _relation(
    buffer_code: str = "BUF-01",
    workshop_code: str = "S1",
    upstream_process_code: str = "ZR",
    downstream_process_code: str = "PK",
) -> AlgorithmBufferProcessRelation:
    return AlgorithmBufferProcessRelation(
        buffer_code=buffer_code,
        workshop_code=workshop_code,
        upstream_process_code=upstream_process_code,
        downstream_process_code=downstream_process_code,
    )


def _snapshot(
    *buffers: AlgorithmBufferMaster,
    relations: list[AlgorithmBufferProcessRelation] | None = None,
) -> AlgorithmSnapshot:
    if relations is None:
        relations = [_relation(buffer.buffer_code) for buffer in buffers]
    return AlgorithmSnapshot(
        current_time=datetime(2026, 7, 15, 8, 30),
        workshops=[],
        lines=[],
        machine_lines=[],
        machine_runtimes=[],
        machine_masters=[],
        machine_product_capacities=[],
        orders=[],
        products=[],
        process_routes=[],
        buffer_masters=list(buffers),
        buffer_process_relations=relations,
        buffer_order_inventories=[],
        agv_relations=[],
    )


def _rate(
    *,
    buffer_code: str = "BUF-01",
    order_code: str = "ORD-001",
    wafer_size: str = "182",
    wafer_spec: str = "N",
    current_quantity: float = 2000,
    net_consumption_rate: float = -2000,
) -> AlgorithmIntervalNetRateResult:
    upstream_output_rate = 5000
    downstream_input_rate = upstream_output_rate + net_consumption_rate
    return AlgorithmIntervalNetRateResult(
        buffer_code=buffer_code,
        order_code=order_code,
        wafer_size=wafer_size,
        wafer_spec=wafer_spec,
        workshop_code="S1",
        upstream_process_code="ZR",
        downstream_process_code="PK",
        current_quantity=current_quantity,
        upstream_output_rate=upstream_output_rate,
        downstream_input_rate=downstream_input_rate,
        net_consumption_rate=net_consumption_rate,
    )


def _calculate(
    snapshot: AlgorithmSnapshot,
    *rates: AlgorithmIntervalNetRateResult,
):
    return overflow_module.OverflowTimeCalculator().calculate_algorithm(
        snapshot,
        list(rates),
    )


def _assert_calculation_error(
    snapshot: AlgorithmSnapshot,
    rates: list[AlgorithmIntervalNetRateResult],
    match: str,
) -> None:
    error_type = getattr(
        overflow_module,
        "PredictionTimeCalculationError",
        ValueError,
    )
    with pytest.raises(error_type, match=match):
        overflow_module.OverflowTimeCalculator().calculate_algorithm(snapshot, rates)


def test_one_buffer_one_order_overflow_time():
    result = _calculate(_snapshot(_buffer()), _rate())[0]

    assert result.total_inventory == 2000
    assert result.buffer_growth_rate == 2000
    assert result.remaining_capacity == 8000
    assert result.overflow_minutes == 240


def test_result_context_fields_come_from_buffer_process_relation():
    result = _calculate(
        _snapshot(
            _buffer(),
            relations=[_relation("BUF-01", "S2", "P01", "P02")],
        ),
        _rate(),
    )[0]

    assert result.workshop_code == "S2"
    assert result.upstream_process_code == "P01"
    assert result.downstream_process_code == "P02"


def test_multiple_order_inventory_and_growth_rates_are_algebraically_summed():
    results = _calculate(
        _snapshot(_buffer()),
        _rate(order_code="ORD-001", current_quantity=2000, net_consumption_rate=-3000),
        _rate(order_code="ORD-002", current_quantity=1000, net_consumption_rate=1000),
        _rate(
            order_code="ORD-003",
            wafer_spec="R",
            current_quantity=500,
            net_consumption_rate=-500,
        ),
    )

    result = results[0]
    assert result.total_inventory == 3500
    assert result.buffer_growth_rate == 2500
    assert result.remaining_capacity == 6500
    assert result.overflow_minutes == 156
    assert len(results) == 1


def test_order_growth_details_preserve_every_order_and_signed_rate():
    result = _calculate(
        _snapshot(_buffer()),
        _rate(order_code="ORD-001", current_quantity=2000, net_consumption_rate=-3000),
        _rate(
            order_code="ORD-002",
            wafer_spec="R",
            current_quantity=1000,
            net_consumption_rate=1000,
        ),
    )[0]

    assert [detail.model_dump() for detail in result.order_growth_details] == [
        {
            "order_code": "ORD-001",
            "wafer_size": "182",
            "wafer_spec": "N",
            "current_quantity": 2000.0,
            "upstream_output_rate": 5000.0,
            "downstream_input_rate": 2000.0,
            "net_consumption_rate": -3000.0,
            "growth_rate": 3000.0,
        },
        {
            "order_code": "ORD-002",
            "wafer_size": "182",
            "wafer_spec": "R",
            "current_quantity": 1000.0,
            "upstream_output_rate": 5000.0,
            "downstream_input_rate": 6000.0,
            "net_consumption_rate": 1000.0,
            "growth_rate": -1000.0,
        },
    ]


@pytest.mark.parametrize("net_consumption_rate", [0, 100])
def test_nonpositive_buffer_growth_has_no_overflow_prediction(
    net_consumption_rate,
):
    result = _calculate(
        _snapshot(_buffer()),
        _rate(net_consumption_rate=net_consumption_rate),
    )[0]

    assert result.buffer_growth_rate <= 0
    assert result.overflow_minutes is None


def test_inventory_equal_to_capacity_is_already_overflowed():
    result = _calculate(
        _snapshot(_buffer(max_capacity=10000)),
        _rate(current_quantity=10000, net_consumption_rate=1000),
    )[0]

    assert result.remaining_capacity == 0
    assert result.buffer_growth_rate == -1000
    assert result.overflow_minutes == 0


def test_inventory_above_capacity_returns_zero_without_error():
    result = _calculate(
        _snapshot(_buffer(max_capacity=10000)),
        _rate(current_quantity=12000, net_consumption_rate=1000),
    )[0]

    assert result.remaining_capacity == -2000
    assert result.overflow_minutes == 0


def test_multiple_buffers_are_calculated_separately():
    results = _calculate(
        _snapshot(_buffer("BUF-01", 10000), _buffer("BUF-02", 2000)),
        _rate(buffer_code="BUF-01", current_quantity=1000, net_consumption_rate=-1000),
        _rate(buffer_code="BUF-02", current_quantity=1000, net_consumption_rate=-500),
    )

    assert [(result.buffer_code, result.overflow_minutes) for result in results] == [
        ("BUF-01", 540),
        ("BUF-02", 120),
    ]


def test_empty_buffer_still_generates_complete_result():
    result = _calculate(_snapshot(_buffer()))[0]

    assert result.model_dump() == {
        "buffer_code": "BUF-01",
        "workshop_code": "S1",
        "upstream_process_code": "ZR",
        "downstream_process_code": "PK",
        "max_capacity": 10000.0,
        "total_inventory": 0.0,
        "remaining_capacity": 10000.0,
        "buffer_growth_rate": 0.0,
        "overflow_minutes": None,
        "order_growth_details": [],
    }


def test_unknown_buffer_reference_fails():
    _assert_calculation_error(
        _snapshot(_buffer()),
        [_rate(buffer_code="UNKNOWN")],
        "UNKNOWN.*buffer master",
    )


def test_duplicate_buffer_master_fails():
    _assert_calculation_error(
        _snapshot(_buffer(), _buffer()),
        [],
        "BUF-01.*duplicate buffer master",
    )


def test_buffer_master_without_process_relation_fails():
    _assert_calculation_error(
        _snapshot(_buffer(), relations=[]),
        [],
        "BUF-01.*process relation.*does not exist",
    )


def test_multiple_process_relations_for_same_buffer_fail():
    _assert_calculation_error(
        _snapshot(
            _buffer(),
            relations=[
                _relation(),
                _relation(
                    workshop_code="S2",
                    upstream_process_code="P01",
                    downstream_process_code="P02",
                ),
            ],
        ),
        [],
        "BUF-01.*duplicate process relation",
    )


def test_duplicate_interval_result_fails_instead_of_double_counting():
    rate = _rate()
    _assert_calculation_error(
        _snapshot(_buffer()),
        [rate, rate.model_copy()],
        "BUF-01.*ORD-001.*duplicate interval net rate",
    )
