from datetime import datetime

import pytest

import app.core.warning.overflow_warning as overflow_module
from app.schemas.request_schema import AlgorithmSnapshot
from app.schemas.result_schema import (
    AlgorithmBufferOverflowTimeResult,
    AlgorithmOrderGrowthDetail,
)


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
            "stockout_warning_lead_minutes": 5,
            "overflow_warning_lead_minutes": lead_minutes,
        },
    )


def _detail(
    order_code: str = "ORD-001",
    wafer_size: str = "182",
    wafer_spec: str = "N",
) -> AlgorithmOrderGrowthDetail:
    return AlgorithmOrderGrowthDetail(
        order_code=order_code,
        wafer_size=wafer_size,
        wafer_spec=wafer_spec,
        current_quantity=2000,
        upstream_output_rate=5000,
        downstream_input_rate=2000,
        net_consumption_rate=-3000,
        growth_rate=3000,
    )


def _overflow(
    *,
    main_id: str | None = None,
    buffer_code: str = "BUF-01",
    buffer_codes: list[str] | None = None,
    workshop_code: str = "S1",
    upstream_process_code: str = "ZR",
    downstream_process_code: str = "PK",
    max_capacity: float = 10000,
    total_inventory: float = 9000,
    remaining_capacity: float = 1000,
    buffer_growth_rate: float = 4000,
    overflow_minutes: float | None = 15,
    order_growth_details: list[AlgorithmOrderGrowthDetail] | None = None,
) -> AlgorithmBufferOverflowTimeResult:
    return AlgorithmBufferOverflowTimeResult(
        main_id=main_id or f"MAIN-{buffer_code}",
        buffer_code=buffer_code,
        buffer_codes=(
            [buffer_code] if buffer_codes is None else buffer_codes
        ),
        workshop_code=workshop_code,
        upstream_process_code=upstream_process_code,
        downstream_process_code=downstream_process_code,
        max_capacity=max_capacity,
        total_inventory=total_inventory,
        remaining_capacity=remaining_capacity,
        buffer_growth_rate=buffer_growth_rate,
        overflow_minutes=overflow_minutes,
        order_growth_details=(
            [_detail()] if order_growth_details is None else order_growth_details
        ),
    )


def _evaluate(
    snapshot: AlgorithmSnapshot,
    *results: AlgorithmBufferOverflowTimeResult,
):
    return overflow_module.OverflowWarningEvaluator().evaluate_algorithm(
        snapshot,
        list(results),
    )


def _assert_warning_error(
    snapshot: AlgorithmSnapshot,
    results: list[AlgorithmBufferOverflowTimeResult],
    match: str,
) -> None:
    error_type = getattr(overflow_module, "WarningEvaluationError", ValueError)
    with pytest.raises(error_type, match=match):
        overflow_module.OverflowWarningEvaluator().evaluate_algorithm(
            snapshot,
            results,
        )


def test_boundary_results_return_only_buffers_within_lead_time_in_time_order():
    warnings = _evaluate(
        _snapshot(30),
        _overflow(buffer_code="BUF-01", overflow_minutes=15),
        _overflow(buffer_code="BUF-02", overflow_minutes=30),
        _overflow(buffer_code="BUF-03", overflow_minutes=45),
        _overflow(buffer_code="BUF-04", overflow_minutes=None),
        _overflow(
            buffer_code="BUF-05",
            total_inventory=11000,
            remaining_capacity=-1000,
            buffer_growth_rate=-500,
            overflow_minutes=0,
        ),
    )

    assert [
        (warning.buffer_code, warning.overflow_minutes) for warning in warnings
    ] == [
        ("BUF-05", 0),
        ("BUF-01", 15),
        ("BUF-02", 30),
    ]


def test_warning_preserves_prediction_fields_details_snapshot_time_and_config_lead():
    details = [
        _detail("ORD-001", "182", "N"),
        _detail("ORD-002", "210", "R"),
    ]
    warning = _evaluate(
        _snapshot(30),
        _overflow(
            buffer_code="BUF-COPY",
            max_capacity=10000,
            total_inventory=1234,
            remaining_capacity=-987,
            buffer_growth_rate=-321,
            overflow_minutes=0,
            order_growth_details=details,
        ),
    )[0]

    assert warning.warning_type == "overflow"
    assert warning.warning_time == SNAPSHOT_TIME
    assert warning.overflow_warning_lead_minutes == 30
    assert warning.main_id == "MAIN-BUF-COPY"
    assert warning.buffer_code == "BUF-COPY"
    assert warning.buffer_codes == ["BUF-COPY"]
    assert warning.workshop_code == "S1"
    assert warning.upstream_process_code == "ZR"
    assert warning.downstream_process_code == "PK"
    assert warning.max_capacity == 10000
    assert warning.total_inventory == 1234
    assert warning.remaining_capacity == -987
    assert warning.buffer_growth_rate == -321
    assert warning.overflow_minutes == 0
    assert [item.model_dump() for item in warning.order_growth_details] == [
        item.model_dump() for item in details
    ]
    assert warning.order_growth_details is not details
    assert warning.order_growth_details[0] is not details[0]
    assert [item.wafer_size for item in warning.order_growth_details] == [
        "182",
        "210",
    ]


def test_prediction_totals_and_growth_are_not_recomputed_from_details():
    warning = _evaluate(
        _snapshot(),
        _overflow(
            total_inventory=777,
            remaining_capacity=222,
            buffer_growth_rate=-55,
            order_growth_details=[_detail()],
        ),
    )[0]

    assert (
        warning.total_inventory,
        warning.remaining_capacity,
        warning.buffer_growth_rate,
    ) == (777, 222, -55)


def test_equal_times_sort_by_workshop_buffer_and_process_interval():
    warnings = _evaluate(
        _snapshot(),
        _overflow(
            buffer_code="BUF-A",
            workshop_code="S2",
            upstream_process_code="A",
            downstream_process_code="B",
            overflow_minutes=10,
        ),
        _overflow(
            buffer_code="BUF-B",
            workshop_code="S1",
            upstream_process_code="A",
            downstream_process_code="B",
            overflow_minutes=10,
        ),
        _overflow(
            buffer_code="BUF-C",
            workshop_code="S1",
            upstream_process_code="B",
            downstream_process_code="C",
            overflow_minutes=10,
        ),
    )

    assert [
        (
            item.workshop_code,
            item.buffer_code,
            item.upstream_process_code,
            item.downstream_process_code,
        )
        for item in warnings
    ] == [
        ("S1", "BUF-B", "A", "B"),
        ("S1", "BUF-C", "B", "C"),
        ("S2", "BUF-A", "A", "B"),
    ]


def test_duplicate_main_fails_instead_of_emitting_multiple_warnings():
    result = _overflow()
    duplicate_with_different_context = result.model_copy(
        update={
            "buffer_code": "BUF-02",
            "buffer_codes": ["BUF-02"],
            "workshop_code": "S2",
            "upstream_process_code": "P01",
            "downstream_process_code": "P02",
        }
    )

    _assert_warning_error(
        _snapshot(),
        [result, duplicate_with_different_context],
        "MAIN-BUF-01.*duplicate",
    )


def test_negative_lead_time_fails_even_when_snapshot_was_copied_without_validation():
    snapshot = _snapshot().model_copy(
        update={
            "config": _snapshot().config.model_copy(
                update={"overflow_warning_lead_minutes": -1}
            )
        }
    )

    _assert_warning_error(snapshot, [], "lead.*negative")


def test_negative_overflow_time_fails_even_when_result_was_copied_without_validation():
    result = _overflow().model_copy(update={"overflow_minutes": -1})

    _assert_warning_error(
        _snapshot(),
        [result],
        "BUF-01.*overflow.*negative",
    )


def test_blank_buffer_code_fails():
    result = _overflow().model_copy(update={"buffer_code": "  "})

    _assert_warning_error(_snapshot(), [result], "buffer_code")


@pytest.mark.parametrize(
    "field_name",
    [
        "workshop_code",
        "upstream_process_code",
        "downstream_process_code",
    ],
)
def test_blank_overflow_context_field_fails(field_name: str):
    result = _overflow().model_copy(update={field_name: "  "})

    _assert_warning_error(_snapshot(), [result], field_name)
