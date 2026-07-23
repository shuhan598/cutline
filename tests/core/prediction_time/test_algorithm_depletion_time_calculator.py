from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)
from app.schemas.result_schema import AlgorithmIntervalNetRateResult


def _rate(
    *,
    main_id: str = "MAIN-01",
    buffer_code: str = "BUF-01",
    buffer_codes: list[str] | None = None,
    order_code: str = "ORD-001",
    wafer_size: str = "182",
    wafer_spec: str = "N",
    current_quantity: float = 1600,
    net_consumption_rate: float = 3200,
) -> AlgorithmIntervalNetRateResult:
    return AlgorithmIntervalNetRateResult(
        main_id=main_id,
        buffer_code=buffer_code,
        buffer_codes=(
            [buffer_code] if buffer_codes is None else buffer_codes
        ),
        order_code=order_code,
        wafer_size=wafer_size,
        wafer_spec=wafer_spec,
        workshop_code="S1",
        upstream_process_code="ZR",
        downstream_process_code="PK",
        current_quantity=current_quantity,
        upstream_output_rate=2000,
        downstream_input_rate=2000 + net_consumption_rate,
        net_consumption_rate=net_consumption_rate,
    )


def _calculate(*rates: AlgorithmIntervalNetRateResult):
    return DepletionTimeCalculator().calculate_algorithm(list(rates))


def test_order_inventory_1600_at_rate_3200_depletes_in_30_minutes():
    result = _calculate(_rate())[0]

    assert result.depletion_minutes == 30


def test_algorithm_depletion_copies_complete_interval_result_fields():
    result = _calculate(_rate())[0]

    assert result.model_dump() == {
        "main_id": "MAIN-01",
        "buffer_code": "BUF-01",
        "buffer_codes": ["BUF-01"],
        "order_code": "ORD-001",
        "wafer_size": "182",
        "wafer_spec": "N",
        "workshop_code": "S1",
        "upstream_process_code": "ZR",
        "downstream_process_code": "PK",
        "current_quantity": 1600.0,
        "upstream_output_rate": 2000.0,
        "downstream_input_rate": 5200.0,
        "net_consumption_rate": 3200.0,
        "depletion_minutes": 30.0,
    }


def test_zero_net_consumption_has_no_depletion_prediction():
    assert _calculate(_rate(net_consumption_rate=0))[0].depletion_minutes is None


def test_negative_net_consumption_has_no_depletion_prediction():
    assert (
        _calculate(_rate(net_consumption_rate=-100))[0].depletion_minutes is None
    )


def test_zero_inventory_with_positive_consumption_depletes_immediately():
    result = _calculate(_rate(current_quantity=0, net_consumption_rate=100))[0]

    assert result.depletion_minutes == 0


def test_same_wafer_spec_different_orders_are_calculated_separately():
    results = _calculate(
        _rate(order_code="ORD-001", current_quantity=1600, net_consumption_rate=3200),
        _rate(order_code="ORD-002", current_quantity=5000, net_consumption_rate=1000),
    )

    assert [(result.order_code, result.depletion_minutes) for result in results] == [
        ("ORD-001", 30),
        ("ORD-002", 300),
    ]


def test_same_order_in_different_main_ids_is_calculated_separately():
    results = _calculate(
        _rate(
            main_id="MAIN-01",
            buffer_code="BUF-01",
            current_quantity=100,
            net_consumption_rate=100,
        ),
        _rate(
            main_id="MAIN-02",
            buffer_code="BUF-02",
            current_quantity=500,
            net_consumption_rate=100,
        ),
    )

    assert [
        (result.main_id, result.buffer_code, result.depletion_minutes)
        for result in results
    ] == [
        ("MAIN-01", "BUF-01", 60),
        ("MAIN-02", "BUF-02", 300),
    ]


def test_aggregated_10800_inventory_produces_one_180_minute_result():
    results = _calculate(
        _rate(
            main_id="MAIN-10800",
            buffer_code="BUF-01",
            buffer_codes=["BUF-01", "BUF-02"],
            current_quantity=10800,
            net_consumption_rate=3600,
        )
    )

    assert len(results) == 1
    assert results[0].main_id == "MAIN-10800"
    assert results[0].buffer_codes == ["BUF-01", "BUF-02"]
    assert results[0].current_quantity == 10800
    assert results[0].depletion_minutes == 180


def test_depletion_does_not_use_whole_buffer_inventory_or_other_order_rate():
    results = _calculate(
        _rate(order_code="ORD-001", current_quantity=100, net_consumption_rate=200),
        _rate(order_code="ORD-002", current_quantity=10000, net_consumption_rate=10),
    )

    assert results[0].depletion_minutes == 30
    assert results[1].depletion_minutes == 60000
