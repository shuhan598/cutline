from datetime import datetime

import pytest

import app.core.warning.stockout_warning as stockout_module
from app.schemas.request_schema import AlgorithmSnapshot
from app.schemas.result_schema import AlgorithmDepletionTimeResult


SNAPSHOT_TIME = datetime(2026, 7, 15, 8, 30)


def _snapshot(lead_minutes: float = 30) -> AlgorithmSnapshot:
    return AlgorithmSnapshot(
        current_time=SNAPSHOT_TIME,
        workshops=[],
        lines=[],
        machine_lines=[],
        machine_runtimes=[],
        machine_masters=[],
        machine_product_capacities=[],
        orders=[],
        products=[],
        process_routes=[],
        buffer_masters=[],
        buffer_process_relations=[],
        buffer_order_inventories=[],
        agv_relations=[],
        config={
            "stockout_warning_lead_minutes": lead_minutes,
            "overflow_warning_lead_minutes": 90,
        },
    )


def _depletion(
    *,
    buffer_code: str = "BUF-01",
    order_code: str = "ORD-001",
    wafer_size: str = "182",
    wafer_spec: str = "N",
    workshop_code: str = "S1",
    upstream_process_code: str = "ZR",
    downstream_process_code: str = "PK",
    depletion_minutes: float | None = 20,
    current_quantity: float = 800,
    upstream_output_rate: float = 1000,
    downstream_input_rate: float = 3400,
    net_consumption_rate: float = 2400,
) -> AlgorithmDepletionTimeResult:
    return AlgorithmDepletionTimeResult(
        buffer_code=buffer_code,
        order_code=order_code,
        wafer_size=wafer_size,
        wafer_spec=wafer_spec,
        workshop_code=workshop_code,
        upstream_process_code=upstream_process_code,
        downstream_process_code=downstream_process_code,
        current_quantity=current_quantity,
        upstream_output_rate=upstream_output_rate,
        downstream_input_rate=downstream_input_rate,
        net_consumption_rate=net_consumption_rate,
        depletion_minutes=depletion_minutes,
    )


def _evaluate(
    snapshot: AlgorithmSnapshot,
    *results: AlgorithmDepletionTimeResult,
):
    return stockout_module.StockoutWarningEvaluator().evaluate_algorithm(
        snapshot,
        list(results),
    )


def _assert_warning_error(
    snapshot: AlgorithmSnapshot,
    results: list[AlgorithmDepletionTimeResult],
    match: str,
) -> None:
    error_type = getattr(stockout_module, "WarningEvaluationError", ValueError)
    with pytest.raises(error_type, match=match):
        stockout_module.StockoutWarningEvaluator().evaluate_algorithm(
            snapshot,
            results,
        )


def test_boundary_results_only_return_predictions_within_lead_time():
    warnings = _evaluate(
        _snapshot(30),
        _depletion(buffer_code="BUF-01", order_code="ORD-001", depletion_minutes=20),
        _depletion(buffer_code="BUF-01", order_code="ORD-002", depletion_minutes=30),
        _depletion(
            buffer_code="BUF-02",
            order_code="ORD-003",
            wafer_spec="R",
            depletion_minutes=31,
        ),
        _depletion(
            buffer_code="BUF-03",
            order_code="ORD-004",
            wafer_spec="R",
            depletion_minutes=None,
        ),
    )

    assert [
        (warning.buffer_code, warning.order_code, warning.depletion_minutes)
        for warning in warnings
    ] == [
        ("BUF-01", "ORD-001", 20),
        ("BUF-01", "ORD-002", 30),
    ]


def test_zero_minutes_triggers_and_preserves_time_lead_and_complete_input_fields():
    warning = _evaluate(
        _snapshot(30),
        _depletion(
            buffer_code="BUF-ZERO",
            order_code="ORD-ZERO",
            wafer_spec="R",
            workshop_code="S2",
            upstream_process_code="YS",
            downstream_process_code="SX",
            current_quantity=0,
            upstream_output_rate=1200,
            downstream_input_rate=1800,
            net_consumption_rate=600,
            depletion_minutes=0,
        ),
    )[0]

    assert warning.model_dump() == {
        "warning_type": "stockout",
        "warning_time": SNAPSHOT_TIME,
        "buffer_code": "BUF-ZERO",
        "order_code": "ORD-ZERO",
        "wafer_size": "182",
        "wafer_spec": "R",
        "workshop_code": "S2",
        "upstream_process_code": "YS",
        "downstream_process_code": "SX",
        "current_quantity": 0.0,
        "upstream_output_rate": 1200.0,
        "downstream_input_rate": 1800.0,
        "net_consumption_rate": 600.0,
        "depletion_minutes": 0.0,
        "stockout_warning_lead_minutes": 30.0,
    }


def test_same_wafer_spec_different_orders_are_independent_without_aggregation():
    warnings = _evaluate(
        _snapshot(),
        _depletion(order_code="ORD-001", current_quantity=100, depletion_minutes=10),
        _depletion(order_code="ORD-002", current_quantity=9000, depletion_minutes=20),
    )

    assert [(item.order_code, item.current_quantity) for item in warnings] == [
        ("ORD-001", 100),
        ("ORD-002", 9000),
    ]


def test_same_order_in_different_buffers_is_independent():
    warnings = _evaluate(
        _snapshot(),
        _depletion(
            buffer_code="BUF-01",
            upstream_process_code="P01",
            downstream_process_code="P02",
            depletion_minutes=10,
        ),
        _depletion(
            buffer_code="BUF-02",
            upstream_process_code="P02",
            downstream_process_code="P03",
            depletion_minutes=20,
        ),
    )

    assert [
        (
            item.buffer_code,
            item.order_code,
            item.upstream_process_code,
            item.downstream_process_code,
        )
        for item in warnings
    ] == [
        ("BUF-01", "ORD-001", "P01", "P02"),
        ("BUF-02", "ORD-001", "P02", "P03"),
    ]


def test_same_order_same_buffer_different_process_intervals_are_independent():
    warnings = _evaluate(
        _snapshot(),
        _depletion(
            upstream_process_code="P01",
            downstream_process_code="P02",
        ),
        _depletion(
            upstream_process_code="P02",
            downstream_process_code="P03",
        ),
    )

    assert [
        (item.upstream_process_code, item.downstream_process_code)
        for item in warnings
    ] == [("P01", "P02"), ("P02", "P03")]


@pytest.mark.parametrize(
    "different_field",
    ["workshop_code", "wafer_spec"],
)
def test_complete_unique_key_keeps_different_workshop_or_spec_independent(
    different_field: str,
):
    changed_value = "S2" if different_field == "workshop_code" else "R"
    second = _depletion().model_copy(update={different_field: changed_value})

    warnings = _evaluate(_snapshot(), _depletion(), second)

    assert len(warnings) == 2


def test_complete_unique_key_keeps_different_wafer_size_independent():
    warnings = _evaluate(
        _snapshot(),
        _depletion(wafer_size="182"),
        _depletion(wafer_size="210"),
    )

    assert [item.wafer_size for item in warnings] == ["182", "210"]


def test_equal_times_use_complete_business_granularity_for_stable_sorting():
    warnings = _evaluate(
        _snapshot(),
        _depletion(
            workshop_code="S2",
            buffer_code="BUF-A",
            order_code="ORD-A",
            wafer_spec="N",
            upstream_process_code="A",
            downstream_process_code="B",
        ),
        _depletion(
            workshop_code="S1",
            buffer_code="BUF-B",
            order_code="ORD-A",
            wafer_spec="N",
            upstream_process_code="A",
            downstream_process_code="B",
        ),
        _depletion(
            workshop_code="S1",
            buffer_code="BUF-A",
            order_code="ORD-B",
            wafer_spec="N",
            upstream_process_code="A",
            downstream_process_code="B",
        ),
        _depletion(
            workshop_code="S1",
            buffer_code="BUF-A",
            order_code="ORD-A",
            wafer_spec="R",
            upstream_process_code="A",
            downstream_process_code="B",
        ),
        _depletion(
            workshop_code="S1",
            buffer_code="BUF-A",
            order_code="ORD-A",
            wafer_spec="N",
            upstream_process_code="B",
            downstream_process_code="C",
        ),
        _depletion(
            workshop_code="S1",
            buffer_code="BUF-A",
            order_code="ORD-A",
            wafer_spec="N",
            upstream_process_code="A",
            downstream_process_code="C",
        ),
    )

    assert [
        (
            item.workshop_code,
            item.buffer_code,
            item.order_code,
            item.wafer_spec,
            item.upstream_process_code,
            item.downstream_process_code,
        )
        for item in warnings
    ] == [
        ("S1", "BUF-A", "ORD-A", "N", "A", "C"),
        ("S1", "BUF-A", "ORD-A", "N", "B", "C"),
        ("S1", "BUF-A", "ORD-A", "R", "A", "B"),
        ("S1", "BUF-A", "ORD-B", "N", "A", "B"),
        ("S1", "BUF-B", "ORD-A", "N", "A", "B"),
        ("S2", "BUF-A", "ORD-A", "N", "A", "B"),
    ]


def test_duplicate_interval_identity_fails_instead_of_emitting_two_warnings():
    result = _depletion()

    with pytest.raises(stockout_module.WarningEvaluationError) as exc_info:
        stockout_module.StockoutWarningEvaluator().evaluate_algorithm(
            _snapshot(),
            [result, result.model_copy()],
        )

    assert str(exc_info.value) == (
        "duplicate stockout warning input: "
        "workshop=S1, buffer=BUF-01, order=ORD-001, "
        "wafer_size=182, wafer_spec=N, interval=ZR->PK"
    )


def test_negative_lead_time_fails_even_when_snapshot_was_copied_without_validation():
    snapshot = _snapshot().model_copy(
        update={
            "config": _snapshot().config.model_copy(
                update={"stockout_warning_lead_minutes": -1}
            )
        }
    )

    _assert_warning_error(snapshot, [], "lead.*negative")


def test_negative_depletion_time_fails_even_when_result_was_copied_without_validation():
    result = _depletion().model_copy(update={"depletion_minutes": -1})

    _assert_warning_error(
        _snapshot(),
        [result],
        "BUF-01.*ORD-001.*depletion.*negative",
    )


@pytest.mark.parametrize(
    ("field", "match"),
    [
        ("buffer_code", "buffer_code"),
        ("order_code", "order_code"),
        ("wafer_size", "wafer_size"),
        ("wafer_spec", "wafer_spec"),
        ("workshop_code", "workshop_code"),
        ("upstream_process_code", "upstream_process_code"),
        ("downstream_process_code", "downstream_process_code"),
    ],
)
def test_blank_required_code_fails(field: str, match: str):
    result = _depletion().model_copy(update={field: "  "})

    _assert_warning_error(_snapshot(), [result], match)

