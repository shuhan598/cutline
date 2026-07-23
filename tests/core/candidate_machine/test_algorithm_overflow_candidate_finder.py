import pytest

import app.core.candidate_machine.overflow_candidate_finder as overflow_module
from app.schemas.result_schema import (
    AlgorithmIntervalNetRateResult,
    AlgorithmOrderGrowthDetail,
    AlgorithmOverflowWarningResult,
)
from tests.core.candidate_machine.helpers import (
    line,
    machine,
    machine_line,
    order,
    product,
    runtime,
    snapshot,
)


def _detail(
    order_code: str,
    *,
    wafer_size: str = "182",
    wafer_spec: str = "N",
    net_consumption_rate: float,
    growth_rate: float,
) -> AlgorithmOrderGrowthDetail:
    return AlgorithmOrderGrowthDetail(
        order_code=order_code,
        wafer_size=wafer_size,
        wafer_spec=wafer_spec,
        current_quantity=1000,
        upstream_output_rate=5000,
        downstream_input_rate=5000 + net_consumption_rate,
        net_consumption_rate=net_consumption_rate,
        growth_rate=growth_rate,
    )


def _source_detail(
    order_code: str = "ORD-SOURCE",
    *,
    wafer_size: str = "182",
    wafer_spec: str = "N",
    growth_rate: float = 3000,
) -> AlgorithmOrderGrowthDetail:
    return _detail(
        order_code,
        wafer_size=wafer_size,
        wafer_spec=wafer_spec,
        net_consumption_rate=-growth_rate,
        growth_rate=growth_rate,
    )


def _target_detail(
    order_code: str = "ORD-TARGET",
    *,
    wafer_size: str = "182",
    wafer_spec: str = "N",
    capacity_gap: float = 1800,
) -> AlgorithmOrderGrowthDetail:
    return _detail(
        order_code,
        wafer_size=wafer_size,
        wafer_spec=wafer_spec,
        net_consumption_rate=capacity_gap,
        growth_rate=-capacity_gap,
    )


def _warning(
    *details: AlgorithmOrderGrowthDetail,
    workshop_code: str = "S1",
    upstream_process_code: str = "P01",
    downstream_process_code: str = "P02",
) -> AlgorithmOverflowWarningResult:
    if not details:
        details = (_source_detail(), _target_detail())
    return AlgorithmOverflowWarningResult(
        warning_type="overflow",
        warning_time=snapshot().current_time,
        main_id="MAIN-BUF-01",
        buffer_code="BUF-01",
        buffer_codes=["BUF-01"],
        workshop_code=workshop_code,
        upstream_process_code=upstream_process_code,
        downstream_process_code=downstream_process_code,
        max_capacity=10000,
        total_inventory=9000,
        remaining_capacity=1000,
        buffer_growth_rate=1200,
        overflow_minutes=20,
        overflow_warning_lead_minutes=30,
        order_growth_details=list(details),
    )


def _candidate_snapshot():
    candidate_snapshot = snapshot()
    candidate_snapshot.machine_runtimes[0] = (
        candidate_snapshot.machine_runtimes[0].model_copy(
            update={"current_order_code": "ORD-SOURCE"}
        )
    )
    candidate_snapshot.orders = [
        order("ORD-SOURCE", "PROD-SOURCE", "S1"),
        order("ORD-TARGET", "PROD-TARGET", "S1"),
        order("ORD-SECOND", "PROD-SECOND", "S1"),
    ]
    candidate_snapshot.products = [
        product("PROD-SOURCE", "182", "A"),
        product("PROD-TARGET", "182", "A"),
        product("PROD-SECOND", "182", "A"),
    ]
    return candidate_snapshot


def _add_machine(
    candidate_snapshot,
    *,
    machine_code: str,
    order_code: str = "ORD-SOURCE",
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
    return overflow_module.OverflowCandidateFinder().find_algorithm(
        candidate_snapshot,
        [_warning() if warning is None else warning],
    )[0]


def _set_workshop(candidate_snapshot, workshop_code: str) -> None:
    candidate_snapshot.lines[0] = candidate_snapshot.lines[0].model_copy(
        update={"workshop_code": workshop_code}
    )
    candidate_snapshot.orders = [
        item.model_copy(update={"workshop_code": workshop_code})
        for item in candidate_snapshot.orders
    ]
    candidate_snapshot.buffer_process_relations[0] = (
        candidate_snapshot.buffer_process_relations[0].model_copy(
            update={"workshop_code": workshop_code}
        )
    )


def test_overflow_result_contains_selected_source_candidate_and_target_context():
    result = _find(_candidate_snapshot())
    candidate = result.candidates[0]
    option = candidate.target_options[0]

    assert result.warning_type == "overflow"
    assert result.workshop_code == "S1"
    assert result.buffer_code == "BUF-01"
    assert result.upstream_process_code == "P01"
    assert result.downstream_process_code == "P02"
    assert result.source_order_code == "ORD-SOURCE"
    assert result.source_product_code == "PROD-SOURCE"
    assert result.source_wafer_size == "182"
    assert result.source_wafer_spec == "N"
    assert result.source_source_grade == "A"
    assert result.source_growth_rate == 3000
    assert result.source_net_consumption_rate == -3000

    assert candidate.machine_code == "M-01"
    assert candidate.machine_name == "M-01"
    assert candidate.status == "running"
    assert candidate.workshop_code == "S1"
    assert candidate.process_code == "P01"
    assert candidate.process_name == "制绒"
    assert candidate.current_order_code == "ORD-SOURCE"
    assert candidate.current_product_code == "PROD-SOURCE"
    assert candidate.current_wafer_size == "182"
    assert candidate.current_wafer_spec == "N"
    assert candidate.current_source_grade == "A"
    assert candidate.input_quantity_30m == 10000
    assert candidate.output_quantity_30m == 8000
    assert candidate.current_output_rate_per_hour == 16000
    assert candidate.reduced_capacity == 16000
    assert candidate.utilization_rate == pytest.approx(0.8)
    assert candidate.idle_rate == pytest.approx(0.2)

    assert option.target_order_code == "ORD-TARGET"
    assert option.target_product_code == "PROD-TARGET"
    assert option.target_wafer_size == "182"
    assert option.target_wafer_spec == "N"
    assert option.target_source_grade == "A"
    assert option.capacity_gap == 1800
    assert option.estimated_contribution_capacity == 16000


def test_target_option_carries_the_unique_target_interval_context():
    target_interval = AlgorithmIntervalNetRateResult(
        main_id="MAIN-BUF-TARGET",
        buffer_code="BUF-TARGET",
        buffer_codes=["BUF-TARGET"],
        order_code="ORD-TARGET",
        wafer_size="182",
        wafer_spec="N",
        workshop_code="S1",
        upstream_process_code="P01",
        downstream_process_code="P03",
        current_quantity=1000,
        upstream_output_rate=3200,
        downstream_input_rate=5000,
        net_consumption_rate=1800,
    )

    result = overflow_module.OverflowCandidateFinder().find_algorithm(
        _candidate_snapshot(),
        [_warning()],
        interval_results=[target_interval],
    )[0]
    option = result.candidates[0].target_options[0]

    assert option.target_buffer_code == "BUF-TARGET"
    assert option.target_workshop_code == "S1"
    assert option.target_upstream_process_code == "P01"
    assert option.target_downstream_process_code == "P03"


def test_only_largest_positive_growth_order_is_selected_as_source():
    warning = _warning(
        _source_detail("ORD-SOURCE", growth_rate=3000),
        _source_detail("ORD-SECOND", growth_rate=1800),
        _target_detail(),
        _detail(
            "ORD-TARGET",
            net_consumption_rate=500,
            growth_rate=-500,
        ),
    )

    assert _find(_candidate_snapshot(), warning).source_order_code == "ORD-SOURCE"


def test_equal_source_growth_uses_order_code_ascending():
    warning = _warning(
        _source_detail("ORD-SOURCE", growth_rate=3000),
        _source_detail("ORD-SECOND", growth_rate=3000),
        _target_detail(),
    )

    assert _find(_candidate_snapshot(), warning).source_order_code == "ORD-SECOND"


def test_no_positive_growth_order_fails_explicitly():
    warning = _warning(
        _target_detail(),
        _detail(
            "ORD-SECOND",
            net_consumption_rate=0,
            growth_rate=0,
        ),
    )
    error_type = getattr(
        overflow_module,
        "CandidateMachineCalculationError",
        ValueError,
    )

    with pytest.raises(error_type, match="BUF-01.*positive growth"):
        _find(_candidate_snapshot(), warning)


def test_largest_source_without_machine_returns_empty_without_fallback():
    warning = _warning(
        _source_detail("ORD-SECOND", growth_rate=4000),
        _source_detail("ORD-SOURCE", growth_rate=3000),
        _target_detail(),
    )

    result = _find(_candidate_snapshot(), warning)

    assert result.source_order_code == "ORD-SECOND"
    assert result.candidates == []


@pytest.mark.parametrize(
    "case",
    [
        "not_running",
        "other_order",
        "different_workshop",
        "downstream_process",
        "other_process",
        "source_spec_mismatch",
    ],
)
def test_overflow_source_machine_requires_strict_source_identity(case: str):
    candidate_snapshot = _candidate_snapshot()
    if case == "not_running":
        candidate_snapshot.machine_runtimes[0] = (
            candidate_snapshot.machine_runtimes[0].model_copy(
                update={"status": "idle"}
            )
        )
    elif case == "other_order":
        candidate_snapshot.machine_runtimes[0] = (
            candidate_snapshot.machine_runtimes[0].model_copy(
                update={"current_order_code": "ORD-TARGET"}
            )
        )
    elif case == "different_workshop":
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
    elif case == "source_spec_mismatch":
        candidate_snapshot.lines[0] = candidate_snapshot.lines[0].model_copy(
            update={"wafer_spec": "R"}
        )

    assert _find(candidate_snapshot).candidates == []


def test_source_identity_does_not_use_s2_rp_relaxation():
    candidate_snapshot = _candidate_snapshot()
    _set_workshop(candidate_snapshot, "S2")
    candidate_snapshot.lines[0] = candidate_snapshot.lines[0].model_copy(
        update={"wafer_spec": "P"}
    )
    warning = _warning(
        _source_detail(wafer_spec="R"),
        _target_detail(wafer_spec="P"),
        workshop_code="S2",
    )

    assert _find(candidate_snapshot, warning).candidates == []


def test_source_product_size_must_match_source_detail():
    candidate_snapshot = _candidate_snapshot()
    candidate_snapshot.products[0] = candidate_snapshot.products[0].model_copy(
        update={"wafer_size": "210"}
    )
    error_type = getattr(
        overflow_module,
        "CandidateMachineCalculationError",
        ValueError,
    )

    with pytest.raises(error_type, match="ORD-SOURCE.*wafer_size.*182.*210"):
        _find(candidate_snapshot)


@pytest.mark.parametrize(
    "case",
    [
        "nonpositive_gap",
        "different_workshop",
        "different_size",
        "incompatible_spec",
        "source_grade_upgrade",
        "unknown_grade",
    ],
)
def test_overflow_target_order_requires_every_qualification(case: str):
    candidate_snapshot = _candidate_snapshot()
    warning = _warning()
    if case == "nonpositive_gap":
        warning.order_growth_details[1] = _target_detail(capacity_gap=0)
    elif case == "different_workshop":
        candidate_snapshot.orders[1] = candidate_snapshot.orders[1].model_copy(
            update={"workshop_code": "S2"}
        )
    elif case == "different_size":
        candidate_snapshot.products[1] = candidate_snapshot.products[1].model_copy(
            update={"wafer_size": "210"}
        )
        warning.order_growth_details[1] = _target_detail(wafer_size="210")
    elif case == "incompatible_spec":
        warning.order_growth_details[1] = _target_detail(wafer_spec="R")
    elif case == "source_grade_upgrade":
        candidate_snapshot.products[0] = candidate_snapshot.products[0].model_copy(
            update={"source_grade": "A-"}
        )
    elif case == "unknown_grade":
        candidate_snapshot.products[1] = candidate_snapshot.products[1].model_copy(
            update={"source_grade": "UNKNOWN"}
        )

    assert _find(candidate_snapshot, warning).candidates == []


def test_target_product_size_must_match_target_detail():
    candidate_snapshot = _candidate_snapshot()
    warning = _warning(
        _source_detail(),
        _target_detail(wafer_size="210"),
    )
    error_type = getattr(
        overflow_module,
        "CandidateMachineCalculationError",
        ValueError,
    )

    with pytest.raises(error_type, match="ORD-TARGET.*wafer_size.*210.*182"):
        _find(candidate_snapshot, warning)


@pytest.mark.parametrize(
    (
        "workshop_code",
        "process_name",
        "source_spec",
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
def test_overflow_target_uses_algorithm_spec_compatibility(
    workshop_code: str,
    process_name: str,
    source_spec: str,
    target_spec: str,
    expected: bool,
):
    candidate_snapshot = _candidate_snapshot()
    _set_workshop(candidate_snapshot, workshop_code)
    candidate_snapshot.lines[0] = candidate_snapshot.lines[0].model_copy(
        update={"wafer_spec": source_spec}
    )
    candidate_snapshot.machine_masters[0] = (
        candidate_snapshot.machine_masters[0].model_copy(
            update={"process_name": process_name}
        )
    )
    warning = _warning(
        _source_detail(wafer_spec=source_spec),
        _target_detail(wafer_spec=target_spec),
        workshop_code=workshop_code,
    )

    assert bool(_find(candidate_snapshot, warning).candidates) is expected


@pytest.mark.parametrize(
    ("source_grade", "target_grade", "expected"),
    [
        ("A", "A", True),
        ("A", "A-", True),
        ("A-", "A-", True),
        ("A-", "A", False),
    ],
)
def test_overflow_target_uses_directional_source_grade_rule(
    source_grade: str,
    target_grade: str,
    expected: bool,
):
    candidate_snapshot = _candidate_snapshot()
    candidate_snapshot.products[0] = candidate_snapshot.products[0].model_copy(
        update={"source_grade": source_grade}
    )
    candidate_snapshot.products[1] = candidate_snapshot.products[1].model_copy(
        update={"source_grade": target_grade}
    )

    assert bool(_find(candidate_snapshot).candidates) is expected


def test_zero_output_source_machine_remains_candidate_without_static_capacity():
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
    assert candidate.reduced_capacity == 0
    assert candidate.target_options[0].estimated_contribution_capacity == 0
    assert candidate.utilization_rate == 0
    assert candidate.idle_rate == 1
    assert candidate_snapshot.machine_product_capacities == []


def test_multiple_targets_stay_on_one_machine_and_sort_by_gap_then_order():
    candidate_snapshot = _candidate_snapshot()
    candidate_snapshot.orders.append(
        order("ORD-TARGET-2", "PROD-TARGET-2", "S1")
    )
    candidate_snapshot.products.append(
        product("PROD-TARGET-2", "182", "A")
    )
    warning = _warning(
        _source_detail(),
        _target_detail("ORD-TARGET", capacity_gap=1000),
        _target_detail("ORD-TARGET-2", capacity_gap=2000),
    )

    result = _find(candidate_snapshot, warning)

    assert len(result.candidates) == 1
    assert [
        item.target_order_code for item in result.candidates[0].target_options
    ] == ["ORD-TARGET-2", "ORD-TARGET"]


def test_equal_target_gap_sorts_by_order_code():
    candidate_snapshot = _candidate_snapshot()
    candidate_snapshot.orders.append(
        order("ORD-A", "PROD-A", "S1")
    )
    candidate_snapshot.products.append(product("PROD-A", "182", "A"))
    warning = _warning(
        _source_detail(),
        _target_detail("ORD-TARGET", capacity_gap=1000),
        _target_detail("ORD-A", capacity_gap=1000),
    )

    options = _find(candidate_snapshot, warning).candidates[0].target_options

    assert [item.target_order_code for item in options] == [
        "ORD-A",
        "ORD-TARGET",
    ]


def test_candidates_sort_by_utilization_descending_then_machine_code():
    candidate_snapshot = _candidate_snapshot()
    candidate_snapshot.machine_runtimes[0] = (
        candidate_snapshot.machine_runtimes[0].model_copy(
            update={"input_quantity_30m": 100, "output_quantity_30m": 70}
        )
    )
    _add_machine(
        candidate_snapshot,
        machine_code="M-02",
        input_quantity_30m=100,
        output_quantity_30m=95,
    )
    _add_machine(
        candidate_snapshot,
        machine_code="M-03",
        input_quantity_30m=100,
        output_quantity_30m=80,
    )

    assert [item.machine_code for item in _find(candidate_snapshot).candidates] == [
        "M-02",
        "M-03",
        "M-01",
    ]


def test_equal_utilization_sorts_by_machine_code():
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
        overflow_module,
        "CandidateMachineCalculationError",
        ValueError,
    )

    with pytest.raises(error_type, match="BUF-01.*warning interval.*does not match"):
        _find(
            _candidate_snapshot(),
            _warning(upstream_process_code="OTHER"),
        )
