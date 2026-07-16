from datetime import datetime, timedelta

import pytest

from app.core.silk_screen.order_transition_planner import (
    SilkScreenOrderTransitionPlanner,
)
from app.core.silk_screen.errors import SilkScreenTransitionCalculationError
from app.schemas.common_schema import (
    AlgorithmConfig,
    AlgorithmLine,
    AlgorithmMachineLineRelation,
    AlgorithmMachineMaster,
    AlgorithmMachineProductCapacity,
    AlgorithmMachineRuntime,
    AlgorithmOrder,
)
from app.schemas.request_schema import AlgorithmSnapshot


CURRENT_TIME = datetime(2026, 7, 15, 10, 0)


def _runtime(
    machine_code: str = "M01",
    *,
    order_code: str | None = "ORD-01",
    status: str = "running",
    output_quantity_30m: float = 5000,
    input_quantity_30m: float = 999999,
    period_quantity_30m: float = 888888,
) -> AlgorithmMachineRuntime:
    return AlgorithmMachineRuntime(
        machine_code=machine_code,
        status=status,
        current_order_code=order_code,
        tangent_time=None,
        input_quantity_30m=input_quantity_30m,
        output_quantity_30m=output_quantity_30m,
        period_quantity_30m=period_quantity_30m,
        out_time=None,
    )


def _master(
    machine_code: str = "M01",
    *,
    process_code: str = "SW",
    process_name: str = "丝网",
) -> AlgorithmMachineMaster:
    return AlgorithmMachineMaster(
        machine_code=machine_code,
        machine_name=machine_code,
        process_code=process_code,
        process_name=process_name,
    )


def _relation(
    machine_code: str = "M01",
    line_code: str = "LINE-01",
) -> AlgorithmMachineLineRelation:
    return AlgorithmMachineLineRelation(
        machine_code=machine_code,
        line_code=line_code,
    )


def _line(
    line_code: str = "LINE-01",
    *,
    workshop_code: str = "S1",
) -> AlgorithmLine:
    return AlgorithmLine(
        line_code=line_code,
        line_name=line_code,
        wafer_spec="N",
        workshop_code=workshop_code,
        workshop_name=f"{workshop_code}车间",
    )


def _order(
    order_code: str = "ORD-01",
    *,
    workshop_code: str = "S1",
    product_code: str | None = None,
    total_quantity: float = 100000,
    produced_quantity: float = 80000,
) -> AlgorithmOrder:
    return AlgorithmOrder(
        order_code=order_code,
        order_name=order_code,
        order_status="running",
        product_code=product_code or f"PROD-{order_code}",
        product_name=product_code or f"PROD-{order_code}",
        workshop_code=workshop_code,
        workshop_name=f"{workshop_code}车间",
        total_quantity=total_quantity,
        produced_quantity=produced_quantity,
        piece_source="A",
        estimated_yield="99%",
    )


def _snapshot(
    *,
    current_time: datetime = CURRENT_TIME,
    runtimes: list[AlgorithmMachineRuntime] | None = None,
    masters: list[AlgorithmMachineMaster] | None = None,
    relations: list[AlgorithmMachineLineRelation] | None = None,
    lines: list[AlgorithmLine] | None = None,
    orders: list[AlgorithmOrder] | None = None,
    capacities: list[AlgorithmMachineProductCapacity] | None = None,
    clear_minutes: float = 30,
) -> AlgorithmSnapshot:
    return AlgorithmSnapshot(
        current_time=current_time,
        workshops=[],
        lines=list(lines if lines is not None else [_line()]),
        machine_lines=list(
            relations if relations is not None else [_relation()]
        ),
        machine_runtimes=list(
            runtimes if runtimes is not None else [_runtime()]
        ),
        machine_masters=list(
            masters if masters is not None else [_master()]
        ),
        machine_product_capacities=list(capacities or []),
        orders=list(orders if orders is not None else [_order()]),
        products=[],
        process_routes=[],
        buffer_masters=[],
        buffer_process_relations=[],
        buffer_order_inventories=[],
        agv_relations=[],
        config=AlgorithmConfig(silk_screen_clear_minutes=clear_minutes),
    )


def _evaluate(snapshot: AlgorithmSnapshot):
    return SilkScreenOrderTransitionPlanner().evaluate(snapshot=snapshot)


def test_single_running_silk_machine_forecasts_current_order():
    result = _evaluate(_snapshot())[0]

    assert result.workshop_code == "S1"
    assert result.process_code == "SW"
    assert result.process_name == "丝网"
    assert result.current_order_code == "ORD-01"
    assert result.current_product_code == "PROD-ORD-01"
    assert result.machine_codes == ["M01"]
    assert result.total_quantity == 100000
    assert result.produced_quantity == 80000
    assert result.remaining_quantity == 20000
    assert result.current_order_output_rate == 10000
    assert result.remaining_production_hours == 2
    assert result.current_time == CURRENT_TIME
    assert result.estimated_finish_time == CURRENT_TIME + timedelta(hours=2)
    assert result.clearance_prepare_time == CURRENT_TIME + timedelta(minutes=90)
    assert result.silk_screen_clear_minutes == 30
    assert result.prepare_clearance is False
    assert result.reason == "not_yet_time_to_prepare"
    assert result.next_order_code is None


def test_same_workshop_and_order_aggregate_realtime_outputs_only():
    snapshot = _snapshot(
        runtimes=[
            _runtime("M02", output_quantity_30m=4000),
            _runtime(
                "M01",
                output_quantity_30m=5000,
                input_quantity_30m=1,
                period_quantity_30m=1,
            ),
        ],
        masters=[_master("M02"), _master("M01")],
        relations=[_relation("M02"), _relation("M01")],
    )

    result = _evaluate(snapshot)[0]

    assert result.machine_codes == ["M01", "M02"]
    assert result.current_order_output_rate == 18000
    assert result.remaining_production_hours == pytest.approx(20000 / 18000)
    assert result.estimated_finish_time == CURRENT_TIME + timedelta(
        hours=20000 / 18000
    )


def test_same_order_in_different_workshops_produces_separate_results():
    results = _evaluate(
        _snapshot(
            runtimes=[_runtime("M-S2"), _runtime("M-S1")],
            masters=[_master("M-S2"), _master("M-S1")],
            relations=[
                _relation("M-S2", "LINE-S2"),
                _relation("M-S1", "LINE-S1"),
            ],
            lines=[
                _line("LINE-S2", workshop_code="S2"),
                _line("LINE-S1", workshop_code="S1"),
            ],
            orders=[
                _order(workshop_code="S2"),
                _order(workshop_code="S1"),
            ],
        )
    )

    assert [(item.workshop_code, item.current_order_code) for item in results] == [
        ("S1", "ORD-01"),
        ("S2", "ORD-01"),
    ]


def test_different_orders_are_separate_and_results_are_stably_sorted():
    results = _evaluate(
        _snapshot(
            runtimes=[
                _runtime("M02", order_code="ORD-02"),
                _runtime("M01", order_code="ORD-01"),
            ],
            masters=[_master("M02"), _master("M01")],
            relations=[_relation("M02"), _relation("M01")],
            orders=[_order("ORD-02"), _order("ORD-01")],
        )
    )

    assert [item.current_order_code for item in results] == [
        "ORD-01",
        "ORD-02",
    ]


def test_non_exact_nonrunning_and_empty_order_machines_do_not_participate():
    results = _evaluate(
        _snapshot(
            runtimes=[
                _runtime("VALID"),
                _runtime("OTHER-PROCESS"),
                _runtime("FUZZY"),
                _runtime("IDLE", status="idle"),
                _runtime("EMPTY", order_code=None),
            ],
            masters=[
                _master("VALID"),
                _master("OTHER-PROCESS", process_name="制绒"),
                _master("FUZZY", process_name="丝网01"),
                _master("IDLE"),
                _master("EMPTY"),
            ],
            relations=[_relation("VALID")],
        )
    )

    assert len(results) == 1
    assert results[0].machine_codes == ["VALID"]


def test_completed_and_overproduced_orders_clamp_remaining_to_zero():
    completed = _order(total_quantity=1000, produced_quantity=1000)
    overproduced = completed.model_copy(update={"produced_quantity": 1200})

    snapshots = [
        _snapshot(orders=[completed]),
        _snapshot(orders=[completed]).model_copy(
            update={"orders": [overproduced]}
        ),
    ]
    for snapshot in snapshots:
        result = _evaluate(snapshot)[0]

        assert result.remaining_quantity == 0
        assert result.remaining_production_hours is None
        assert result.estimated_finish_time == CURRENT_TIME
        assert result.clearance_prepare_time == CURRENT_TIME
        assert result.prepare_clearance is True
        assert result.reason == "current_order_completed"
        assert "已经完成" in result.message


def test_zero_realtime_output_has_no_theoretical_capacity_fallback():
    result = _evaluate(
        _snapshot(
            runtimes=[_runtime(output_quantity_30m=0)],
            capacities=[
                AlgorithmMachineProductCapacity(
                    machine_code="M01",
                    product_code="PROD-ORD-01",
                    proc_seconds=1,
                    actual_capacity=999999,
                )
            ],
        )
    )[0]

    assert result.current_order_output_rate == 0
    assert result.remaining_production_hours is None
    assert result.estimated_finish_time is None
    assert result.clearance_prepare_time is None
    assert result.prepare_clearance is False
    assert result.reason == "current_order_capacity_unavailable"


def test_prepare_boundary_is_inclusive_and_one_second_before_is_not_ready():
    at_boundary = _evaluate(
        _snapshot(
            runtimes=[_runtime(output_quantity_30m=5000)],
            orders=[
                _order(total_quantity=5000, produced_quantity=0)
            ],
        )
    )[0]
    one_second_early = _evaluate(
        _snapshot(
            runtimes=[_runtime(output_quantity_30m=1800)],
            orders=[
                _order(total_quantity=1801, produced_quantity=0)
            ],
        )
    )[0]

    assert at_boundary.clearance_prepare_time == CURRENT_TIME
    assert at_boundary.prepare_clearance is True
    assert at_boundary.reason == "clearance_preparation_required"
    assert one_second_early.clearance_prepare_time == CURRENT_TIME + timedelta(
        seconds=1
    )
    assert one_second_early.prepare_clearance is False


def test_clear_minutes_parameter_moves_prepare_time():
    thirty = _evaluate(_snapshot(clear_minutes=30))[0]
    sixty = _evaluate(_snapshot(clear_minutes=60))[0]

    assert sixty.clearance_prepare_time == (
        thirty.clearance_prepare_time - timedelta(minutes=30)
    )


@pytest.mark.parametrize(
    ("snapshot", "match"),
    [
        (
            _snapshot(runtimes=[_runtime(), _runtime()]),
            "duplicate machine runtime.*M01",
        ),
        (
            _snapshot(masters=[_master(), _master()]),
            "duplicate machine master.*M01",
        ),
        (
            _snapshot(
                relations=[
                    _relation(line_code="LINE-01"),
                    _relation(line_code="LINE-02"),
                ]
            ),
            "multiple line relations.*M01",
        ),
        (_snapshot(masters=[]), "machine master.*M01"),
        (_snapshot(relations=[]), "line relation.*M01"),
        (_snapshot(lines=[]), "line.*LINE-01"),
        (_snapshot(orders=[]), "current order.*ORD-01"),
    ],
)
def test_invalid_silk_indexes_raise_explicit_error(snapshot, match):
    with pytest.raises(SilkScreenTransitionCalculationError, match=match):
        _evaluate(snapshot)


def test_same_group_with_conflicting_silk_process_codes_is_rejected():
    with pytest.raises(
        SilkScreenTransitionCalculationError,
        match="conflicting silk process codes",
    ):
        _evaluate(
            _snapshot(
                runtimes=[_runtime("M01"), _runtime("M02")],
                masters=[
                    _master("M01", process_code="SW-1"),
                    _master("M02", process_code="SW-2"),
                ],
                relations=[_relation("M01"), _relation("M02")],
            )
        )


def test_evaluation_does_not_mutate_snapshot_runtime_or_order():
    snapshot = _snapshot()
    runtime = snapshot.machine_runtimes[0]
    order = snapshot.orders[0]
    before = (snapshot.model_dump(), runtime.model_dump(), order.model_dump())

    _evaluate(snapshot)

    assert snapshot.model_dump() == before[0]
    assert runtime.model_dump() == before[1]
    assert order.model_dump() == before[2]


@pytest.mark.parametrize(
    "snapshot",
    [
        _snapshot(clear_minutes=1e308),
        _snapshot(current_time=datetime.max),
    ],
)
def test_out_of_range_forecast_time_raises_domain_error(snapshot):
    with pytest.raises(
        SilkScreenTransitionCalculationError,
        match="forecast time is outside supported datetime range",
    ):
        _evaluate(snapshot)
