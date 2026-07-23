import pytest

import app.core.candidate_machine.stockout_candidate_finder as stockout_module
from app.schemas.result_schema import AlgorithmStockoutWarningResult
from tests.core.candidate_machine.helpers import (
    line,
    machine,
    machine_line,
    order,
    product,
    runtime,
    snapshot,
)


def _warning(
    *,
    workshop_code: str = "S1",
    buffer_code: str = "BUF-01",
    order_code: str = "ORD-TARGET",
    wafer_size: str = "182",
    wafer_spec: str = "N",
    upstream_process_code: str = "P01",
    downstream_process_code: str = "P02",
    net_consumption_rate: float = 3000,
) -> AlgorithmStockoutWarningResult:
    return AlgorithmStockoutWarningResult(
        warning_type="stockout",
        warning_time=snapshot().current_time,
        workshop_code=workshop_code,
        main_id=f"MAIN-{buffer_code}",
        buffer_code=buffer_code,
        buffer_codes=[buffer_code],
        order_code=order_code,
        wafer_size=wafer_size,
        wafer_spec=wafer_spec,
        upstream_process_code=upstream_process_code,
        downstream_process_code=downstream_process_code,
        current_quantity=1000,
        upstream_output_rate=2000,
        downstream_input_rate=5000,
        net_consumption_rate=net_consumption_rate,
        depletion_minutes=20,
        stockout_warning_lead_minutes=30,
    )


def _candidate_snapshot():
    candidate_snapshot = snapshot()
    candidate_snapshot.orders.append(
        order("ORD-TARGET", "PROD-TARGET", "S1")
    )
    candidate_snapshot.products.append(
        product("PROD-TARGET", "182", "A")
    )
    return candidate_snapshot


def _add_machine(
    candidate_snapshot,
    *,
    machine_code: str,
    order_code: str = "ORD-CURRENT",
    status: str = "running",
    workshop_code: str = "S1",
    process_code: str = "P01",
    process_name: str = "制绒",
    wafer_spec: str = "N",
    input_quantity_30m: float = 10000,
    output_quantity_30m: float = 8000,
) -> None:
    line_code = f"LINE-{machine_code}"
    candidate_snapshot.lines.append(
        line(line_code, wafer_spec, workshop_code)
    )
    candidate_snapshot.machine_masters.append(
        machine(machine_code, process_code, process_name)
    )
    candidate_snapshot.machine_lines.append(
        machine_line(machine_code, line_code)
    )
    candidate_snapshot.machine_runtimes.append(
        runtime(
            machine_code,
            order_code,
            status,
            input_quantity_30m,
            output_quantity_30m,
        )
    )


def _find(candidate_snapshot, warning=None):
    return stockout_module.StockoutCandidateFinder().find_algorithm(
        candidate_snapshot,
        [_warning() if warning is None else warning],
    )[0]


def _set_workshop(candidate_snapshot, workshop_code: str) -> None:
    candidate_snapshot.lines[0] = candidate_snapshot.lines[0].model_copy(
        update={"workshop_code": workshop_code}
    )
    candidate_snapshot.orders[1] = candidate_snapshot.orders[1].model_copy(
        update={"workshop_code": workshop_code}
    )
    candidate_snapshot.buffer_process_relations[0] = (
        candidate_snapshot.buffer_process_relations[0].model_copy(
            update={"workshop_code": workshop_code}
        )
    )


def test_stockout_candidate_result_contains_complete_realtime_context():
    result = _find(_candidate_snapshot())
    candidate = result.candidates[0]

    assert result.warning_type == "stockout"
    assert result.workshop_code == "S1"
    assert result.buffer_code == "BUF-01"
    assert result.warning_order_code == "ORD-TARGET"
    assert result.target_product_code == "PROD-TARGET"
    assert result.target_wafer_size == "182"
    assert result.target_wafer_spec == "N"
    assert result.target_source_grade == "A"
    assert result.upstream_process_code == "P01"
    assert result.downstream_process_code == "P02"
    assert result.capacity_gap == 3000

    assert candidate.machine_code == "M-01"
    assert candidate.machine_name == "M-01"
    assert candidate.status == "running"
    assert candidate.workshop_code == "S1"
    assert candidate.process_code == "P01"
    assert candidate.process_name == "制绒"
    assert candidate.current_order_code == "ORD-CURRENT"
    assert candidate.current_product_code == "PROD-CURRENT"
    assert candidate.current_wafer_size == "182"
    assert candidate.current_wafer_spec == "N"
    assert candidate.current_source_grade == "A"
    assert candidate.target_order_code == "ORD-TARGET"
    assert candidate.target_product_code == "PROD-TARGET"
    assert candidate.target_wafer_size == "182"
    assert candidate.target_wafer_spec == "N"
    assert candidate.target_source_grade == "A"
    assert candidate.input_quantity_30m == 10000
    assert candidate.output_quantity_30m == 8000
    assert candidate.current_output_rate_per_hour == 16000
    assert candidate.contribution_capacity == 16000
    assert candidate.utilization_rate == pytest.approx(0.8)
    assert candidate.idle_rate == pytest.approx(0.2)


@pytest.mark.parametrize(
    "case",
    [
        "different_workshop",
        "downstream_process",
        "other_process",
        "not_running",
        "uppercase_running",
        "empty_order",
        "target_order",
        "different_size",
        "incompatible_spec",
        "source_grade_upgrade",
        "unknown_source_grade",
    ],
)
def test_stockout_candidate_requires_every_static_qualification(case: str):
    candidate_snapshot = _candidate_snapshot()
    if case == "different_workshop":
        candidate_snapshot.lines[0] = candidate_snapshot.lines[0].model_copy(
            update={"workshop_code": "S2"}
        )
    elif case == "downstream_process":
        candidate_snapshot.machine_masters[0] = (
            candidate_snapshot.machine_masters[0].model_copy(
                update={"process_code": "P02"}
            )
        )
    elif case == "other_process":
        candidate_snapshot.machine_masters[0] = (
            candidate_snapshot.machine_masters[0].model_copy(
                update={"process_code": "P99"}
            )
        )
    elif case == "not_running":
        candidate_snapshot.machine_runtimes[0] = (
            candidate_snapshot.machine_runtimes[0].model_copy(
                update={"status": "idle"}
            )
        )
    elif case == "uppercase_running":
        candidate_snapshot.machine_runtimes[0] = (
            candidate_snapshot.machine_runtimes[0].model_copy(
                update={"status": "RUNNING"}
            )
        )
    elif case == "empty_order":
        candidate_snapshot.machine_runtimes[0] = (
            candidate_snapshot.machine_runtimes[0].model_copy(
                update={"current_order_code": None}
            )
        )
    elif case == "target_order":
        candidate_snapshot.machine_runtimes[0] = (
            candidate_snapshot.machine_runtimes[0].model_copy(
                update={"current_order_code": "ORD-TARGET"}
            )
        )
    elif case == "different_size":
        candidate_snapshot.products[0] = candidate_snapshot.products[0].model_copy(
            update={"wafer_size": "210"}
        )
    elif case == "incompatible_spec":
        candidate_snapshot.lines[0] = candidate_snapshot.lines[0].model_copy(
            update={"wafer_spec": "R"}
        )
    elif case == "source_grade_upgrade":
        candidate_snapshot.products[0] = candidate_snapshot.products[0].model_copy(
            update={"source_grade": "A-"}
        )
    elif case == "unknown_source_grade":
        candidate_snapshot.products[0] = candidate_snapshot.products[0].model_copy(
            update={"source_grade": "UNKNOWN"}
        )

    assert _find(candidate_snapshot).candidates == []


@pytest.mark.parametrize(
    (
        "workshop_code",
        "process_name",
        "current_spec",
        "target_spec",
        "expected",
    ),
    [
        ("S2", "制绒", "R", "P", True),
        ("S2", "制绒", "P", "R", True),
        ("S2", "丝网", "R", "P", False),
        ("S1", "制绒", "R", "P", False),
    ],
)
def test_stockout_candidate_uses_algorithm_spec_compatibility(
    workshop_code: str,
    process_name: str,
    current_spec: str,
    target_spec: str,
    expected: bool,
):
    candidate_snapshot = _candidate_snapshot()
    _set_workshop(candidate_snapshot, workshop_code)
    candidate_snapshot.lines[0] = candidate_snapshot.lines[0].model_copy(
        update={"wafer_spec": current_spec}
    )
    candidate_snapshot.machine_masters[0] = (
        candidate_snapshot.machine_masters[0].model_copy(
            update={"process_name": process_name}
        )
    )
    warning = _warning(
        workshop_code=workshop_code,
        wafer_spec=target_spec,
    )

    assert bool(_find(candidate_snapshot, warning).candidates) is expected


@pytest.mark.parametrize(
    ("current_grade", "target_grade", "expected"),
    [
        ("A", "A", True),
        ("A", "A-", True),
        ("A-", "A-", True),
        ("A-", "A", False),
    ],
)
def test_stockout_candidate_uses_directional_source_grade_rule(
    current_grade: str,
    target_grade: str,
    expected: bool,
):
    candidate_snapshot = _candidate_snapshot()
    candidate_snapshot.products[0] = candidate_snapshot.products[0].model_copy(
        update={"source_grade": current_grade}
    )
    candidate_snapshot.products[1] = candidate_snapshot.products[1].model_copy(
        update={"source_grade": target_grade}
    )

    assert bool(_find(candidate_snapshot).candidates) is expected


def test_warning_size_must_match_target_order_product_size():
    candidate_snapshot = _candidate_snapshot()
    candidate_snapshot.products[1] = candidate_snapshot.products[1].model_copy(
        update={"wafer_size": "210"}
    )
    error_type = getattr(
        stockout_module,
        "CandidateMachineCalculationError",
        ValueError,
    )

    with pytest.raises(error_type, match="ORD-TARGET.*wafer_size.*182.*210"):
        _find(candidate_snapshot)


def test_running_zero_output_machine_remains_candidate_without_static_capacity():
    candidate_snapshot = _candidate_snapshot()
    candidate_snapshot.machine_runtimes[0] = (
        candidate_snapshot.machine_runtimes[0].model_copy(
            update={
                "input_quantity_30m": 1000,
                "output_quantity_30m": 0,
            }
        )
    )

    candidate = _find(candidate_snapshot).candidates[0]

    assert candidate.current_output_rate_per_hour == 0
    assert candidate.contribution_capacity == 0
    assert candidate.utilization_rate == 0
    assert candidate.idle_rate == 1
    assert candidate_snapshot.machine_product_capacities == []


def test_candidates_sort_by_idle_rate_descending_then_machine_code():
    candidate_snapshot = _candidate_snapshot()
    candidate_snapshot.machine_runtimes[0] = (
        candidate_snapshot.machine_runtimes[0].model_copy(
            update={"input_quantity_30m": 100, "output_quantity_30m": 80}
        )
    )
    _add_machine(
        candidate_snapshot,
        machine_code="M-02",
        input_quantity_30m=100,
        output_quantity_30m=40,
    )
    _add_machine(
        candidate_snapshot,
        machine_code="M-03",
        input_quantity_30m=100,
        output_quantity_30m=60,
    )

    result = _find(candidate_snapshot)

    assert [item.machine_code for item in result.candidates] == [
        "M-02",
        "M-03",
        "M-01",
    ]


def test_equal_idle_rate_sorts_by_machine_code():
    candidate_snapshot = _candidate_snapshot()
    _add_machine(
        candidate_snapshot,
        machine_code="M-00",
        input_quantity_30m=10000,
        output_quantity_30m=8000,
    )

    assert [item.machine_code for item in _find(candidate_snapshot).candidates] == [
        "M-00",
        "M-01",
    ]


def test_warning_interval_must_match_buffer_process_relation():
    error_type = getattr(
        stockout_module,
        "CandidateMachineCalculationError",
        ValueError,
    )

    with pytest.raises(error_type, match="BUF-01.*warning interval.*does not match"):
        _find(
            _candidate_snapshot(),
            _warning(upstream_process_code="OTHER"),
        )
