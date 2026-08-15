import pytest

import app.core.candidate_machine.overflow_candidate_finder as overflow_module
from app.core.buffer_aggregation.models import (
    GroupKey,
    MainBufferAggregationBatch,
    MainBufferGroup,
    PhysicalBufferKey,
)
from app.schemas.result_schema import (
    AlgorithmIntervalNetRateResult,
    AlgorithmOrderGrowthDetail,
    AlgorithmOverflowWarningResult,
)
from tests.core.candidate_machine.helpers import (
    agv_relation,
    line,
    machine,
    machine_line,
    order,
    process_route,
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
    candidate_snapshot.agv_relations[0] = agv_relation(
        order_code="ORD-SOURCE",
        product_name="Source Product",
        wafer_spec="N",
    )
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
    product_name: str | None = None,
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
    candidate_snapshot.agv_relations.append(
        agv_relation(
            machine_code=machine_code,
            order_code=order_code or "ORD-SOURCE",
            product_name=product_name or order_code or "ORD-SOURCE",
            wafer_spec=wafer_spec,
        )
    )


def _find(candidate_snapshot, warning=None):
    return overflow_module.OverflowCandidateFinder().find_algorithm(
        candidate_snapshot,
        [_warning() if warning is None else warning],
    )[0]


def _batch_group(
    *,
    physical_key: PhysicalBufferKey,
    main_id: str,
    order_code: str,
    buffer_code: str,
    auto_receive_eligible: bool = True,
    auto_donate_eligible: bool = True,
) -> MainBufferGroup:
    key = GroupKey(physical_key, main_id, order_code)
    return MainBufferGroup(
        group_key=key,
        main_id=main_id,
        workshop_code=physical_key.workshop_code,
        ordered_service_process_codes=(
            physical_key.ordered_service_process_codes
        ),
        physical_buffer_key=physical_key,
        order_code=order_code,
        product_code=f"PROD-{order_code.removeprefix('ORD-')}",
        buffer_codes=(buffer_code,),
        total_inventory=1000,
        total_capacity=10000,
        remaining_capacity=9000,
        representative_buffer_code=buffer_code,
        stockout_eligible=True,
        overflow_eligible=True,
        stockout_warning_eligible=True,
        overflow_warning_eligible=True,
        auto_receive_eligible=auto_receive_eligible,
        auto_donate_eligible=auto_donate_eligible,
    )


def _with_batch(candidate_snapshot, *groups: MainBufferGroup):
    groups_by_key = {group.group_key: group for group in groups}
    physical_index: dict[PhysicalBufferKey, list[GroupKey]] = {}
    for group in groups:
        physical_index.setdefault(group.physical_buffer_key, []).append(
            group.group_key
        )
    candidate_snapshot.main_buffer_batch = MainBufferAggregationBatch(
        groups=tuple(groups),
        groups_by_group_key=groups_by_key,
        group_keys_by_main_id={
            group.main_id: tuple(
                item.group_key for item in groups if item.main_id == group.main_id
            )
            for group in groups
        },
        group_key_by_buffer_code={
            code: group.group_key
            for group in groups
            for code in group.buffer_codes
        },
        group_key_by_representative_buffer_code={
            group.representative_buffer_code: group.group_key
            for group in groups
            if group.representative_buffer_code is not None
        },
        group_keys_by_physical_buffer_key={
            key: tuple(values) for key, values in physical_index.items()
        },
    )
    return candidate_snapshot


def _group_interval(group: MainBufferGroup, rate: float):
    return AlgorithmIntervalNetRateResult(
        main_id=group.main_id,
        buffer_code=group.representative_buffer_code or "",
        buffer_codes=list(group.buffer_codes),
        order_code=group.order_code,
        wafer_size="182",
        wafer_spec="N",
        workshop_code=group.workshop_code,
        upstream_process_code="P01",
        downstream_process_code="P02",
        current_quantity=group.total_inventory,
        upstream_output_rate=max(rate, 0),
        downstream_input_rate=max(-rate, 0),
        net_consumption_rate=-rate,
        inventory_change_rate=rate,
        group_key=group.group_key,
    )


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
    candidate_snapshot.process_routes = [
        route.model_copy(update={"workshop_code": workshop_code})
        for route in candidate_snapshot.process_routes
    ]


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
    assert candidate.current_order_name == "Source Product"
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


def test_overflow_candidate_runs_without_line_data():
    candidate_snapshot = _candidate_snapshot()
    candidate_snapshot.lines = []
    candidate_snapshot.machine_lines = []

    candidate = _find(candidate_snapshot).candidates[0]

    assert candidate.machine_code == "M-01"
    assert candidate.current_order_code == "ORD-SOURCE"
    assert candidate.current_order_name == "Source Product"
    assert candidate.current_wafer_spec == "N"
    assert candidate.workshop_code == "S1"


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
        candidate_snapshot.agv_relations[0] = (
            candidate_snapshot.agv_relations[0].model_copy(
                update={
                    "order_code": "ORD-TARGET",
                    "product_name": "Target Product",
                }
            )
        )
    elif case == "different_workshop":
        candidate_snapshot.process_routes[0] = (
            candidate_snapshot.process_routes[0].model_copy(
                update={"workshop_code": "S2"}
            )
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
        candidate_snapshot.process_routes.append(process_route("P99"))
    elif case == "source_spec_mismatch":
        candidate_snapshot.agv_relations[0] = (
            candidate_snapshot.agv_relations[0].model_copy(
                update={"wafer_spec": "R"}
            )
        )

    assert _find(candidate_snapshot).candidates == []


def test_source_identity_uses_s2_pre_silk_rp_compatibility_for_agv_spec():
    candidate_snapshot = _candidate_snapshot()
    _set_workshop(candidate_snapshot, "S2")
    candidate_snapshot.agv_relations[0] = (
        candidate_snapshot.agv_relations[0].model_copy(
            update={"wafer_spec": "P"}
        )
    )
    warning = _warning(
        _source_detail(wafer_spec="R"),
        _target_detail(wafer_spec="P"),
        workshop_code="S2",
    )

    assert _find(candidate_snapshot, warning).candidates


def test_overflow_uses_route_workshop_for_s2_compatibility_when_line_is_s1():
    candidate_snapshot = _candidate_snapshot()
    _set_workshop(candidate_snapshot, "S2")
    candidate_snapshot.lines[0] = candidate_snapshot.lines[0].model_copy(
        update={"workshop_code": "S1"}
    )
    candidate_snapshot.agv_relations[0] = (
        candidate_snapshot.agv_relations[0].model_copy(
            update={"wafer_spec": "P"}
        )
    )
    warning = _warning(
        _source_detail(wafer_spec="R"),
        _target_detail(wafer_spec="P"),
        workshop_code="S2",
    )

    candidate = _find(candidate_snapshot, warning).candidates[0]

    assert candidate.workshop_code == "S2"


def test_overflow_does_not_use_line_s2_for_rp_compatibility_when_route_is_s1():
    candidate_snapshot = _candidate_snapshot()
    candidate_snapshot.lines[0] = candidate_snapshot.lines[0].model_copy(
        update={"workshop_code": "S2"}
    )
    candidate_snapshot.agv_relations[0] = (
        candidate_snapshot.agv_relations[0].model_copy(
            update={"wafer_spec": "P"}
        )
    )
    warning = _warning(
        _source_detail(wafer_spec="R"),
        _target_detail(wafer_spec="P"),
        workshop_code="S1",
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
    candidate_snapshot.agv_relations[0] = (
        candidate_snapshot.agv_relations[0].model_copy(
            update={"wafer_spec": source_spec}
        )
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


def test_overflow_uses_agv_current_context_and_ignores_runtime_and_line():
    candidate_snapshot = _candidate_snapshot()
    candidate_snapshot.machine_runtimes[0] = (
        candidate_snapshot.machine_runtimes[0].model_copy(
            update={"current_order_code": None}
        )
    )
    candidate_snapshot.lines[0] = candidate_snapshot.lines[0].model_copy(
        update={"wafer_spec": "R"}
    )
    candidate_snapshot.agv_relations[0] = (
        candidate_snapshot.agv_relations[0].model_copy(
            update={
                "product_name": "AGV Source Product",
                "wafer_spec": "N",
            }
        )
    )

    candidate = _find(candidate_snapshot).candidates[0]

    assert candidate.current_order_code == "ORD-SOURCE"
    assert candidate.current_order_name == "AGV Source Product"
    assert candidate.current_wafer_spec == "N"


def test_overflow_target_compatibility_uses_agv_spec_instead_of_line_spec():
    candidate_snapshot = _candidate_snapshot()
    candidate_snapshot.lines[0] = candidate_snapshot.lines[0].model_copy(
        update={"wafer_spec": "R"}
    )

    assert _find(candidate_snapshot).candidates


def test_overflow_candidate_dump_contains_agv_product_name():
    candidate = _find(_candidate_snapshot()).candidates[0]

    assert candidate.model_dump()["current_order_name"] == "Source Product"


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


def test_batch_targets_never_cross_main_even_when_physical_key_matches():
    physical_key = PhysicalBufferKey("S1", ("P01", "P02"))
    source = _batch_group(
        physical_key=physical_key,
        main_id="MAIN-SOURCE",
        order_code="ORD-SOURCE",
        buffer_code="BUF-01",
    )
    target = _batch_group(
        physical_key=physical_key,
        main_id="MAIN-TARGET",
        order_code="ORD-TARGET",
        buffer_code="BUF-TARGET",
    )
    candidate_snapshot = _with_batch(_candidate_snapshot(), source, target)
    warning = _warning(
        _source_detail("ORD-SECOND", growth_rate=4000),
        _target_detail("ORD-SECOND", capacity_gap=4000),
    ).model_copy(update={"group_key": source.group_key})

    result = overflow_module.OverflowCandidateFinder().find_algorithm(
        candidate_snapshot,
        [warning],
        interval_results=[
            _group_interval(source, 3000),
            _group_interval(target, -1800),
        ],
    )[0]

    assert result.source_order_code == "ORD-SOURCE"
    assert result.source_growth_rate == 3000
    assert result.buffer_code == "BUF-01"
    assert result.candidates == []
    assert result.source_group_key == source.group_key


def test_batch_candidates_include_machines_for_orders_that_can_become_virtual_sources():
    physical_key = PhysicalBufferKey("S1", ("P01", "P02"))
    source = _batch_group(
        physical_key=physical_key,
        main_id="MAIN-SOURCE",
        order_code="ORD-SOURCE",
        buffer_code="BUF-01",
    )
    second_source = _batch_group(
        physical_key=physical_key,
        main_id="MAIN-SOURCE",
        order_code="ORD-SECOND",
        buffer_code="BUF-SECOND",
    )
    target = _batch_group(
        physical_key=physical_key,
        main_id="MAIN-SOURCE",
        order_code="ORD-TARGET",
        buffer_code="BUF-TARGET",
    )
    candidate_snapshot = _with_batch(
        _candidate_snapshot(), source, second_source, target
    )
    _add_machine(
        candidate_snapshot,
        machine_code="M-02",
        order_code="ORD-SECOND",
        product_name="PROD-SECOND",
    )
    warning = _warning().model_copy(update={"group_key": source.group_key})

    result = overflow_module.OverflowCandidateFinder().find_algorithm(
        candidate_snapshot,
        [warning],
        interval_results=[
            _group_interval(source, 3000),
            _group_interval(second_source, -500),
            _group_interval(target, -1800),
        ],
    )[0]

    assert {
        (candidate.machine_code, candidate.current_order_code, candidate.source_group_key)
        for candidate in result.candidates
    } == {
        ("M-01", "ORD-SOURCE", source.group_key),
        ("M-02", "ORD-SECOND", second_source.group_key),
    }


def test_batch_target_filters_group_identity_and_receive_capability():
    physical_key = PhysicalBufferKey("S1", ("P01", "P02"))
    other_physical_key = PhysicalBufferKey("S1", ("P01", "P03"))
    source = _batch_group(
        physical_key=physical_key,
        main_id="MAIN-SOURCE",
        order_code="ORD-SOURCE",
        buffer_code="BUF-01",
    )
    valid = _batch_group(
        physical_key=physical_key,
        main_id="MAIN-SOURCE",
        order_code="ORD-TARGET",
        buffer_code="BUF-TARGET",
    )
    same_main = _batch_group(
        physical_key=physical_key,
        main_id="MAIN-SOURCE",
        order_code="ORD-SECOND",
        buffer_code="BUF-SAME-MAIN",
    )
    same_order = _batch_group(
        physical_key=physical_key,
        main_id="MAIN-SAME-ORDER",
        order_code="ORD-SOURCE",
        buffer_code="BUF-SAME-ORDER",
    )
    unavailable = _batch_group(
        physical_key=physical_key,
        main_id="MAIN-UNAVAILABLE",
        order_code="ORD-UNAVAILABLE",
        buffer_code="BUF-UNAVAILABLE",
        auto_receive_eligible=False,
    )
    other_physical = _batch_group(
        physical_key=other_physical_key,
        main_id="MAIN-OTHER-PHYSICAL",
        order_code="ORD-OTHER-PHYSICAL",
        buffer_code="BUF-OTHER-PHYSICAL",
    )
    candidate_snapshot = _candidate_snapshot()
    candidate_snapshot.orders.extend(
        [
            order("ORD-UNAVAILABLE", "PROD-UNAVAILABLE", "S1"),
            order("ORD-OTHER-PHYSICAL", "PROD-OTHER-PHYSICAL", "S1"),
        ]
    )
    candidate_snapshot.products.extend(
        [
            product("PROD-UNAVAILABLE", "182", "A"),
            product("PROD-OTHER-PHYSICAL", "182", "A"),
        ]
    )
    _with_batch(
        candidate_snapshot,
        source,
        valid,
        same_main,
        same_order,
        unavailable,
        other_physical,
    )
    warning = _warning().model_copy(update={"group_key": source.group_key})
    intervals = [
        _group_interval(group, 3000 if group is source else -1000)
        for group in (
            source,
            valid,
            same_main,
            same_order,
            unavailable,
            other_physical,
        )
    ]

    result = overflow_module.OverflowCandidateFinder().find_algorithm(
        candidate_snapshot,
        [warning],
        interval_results=intervals,
    )[0]

    assert [
        option.target_order_code
        for option in result.candidates[0].target_options
    ] == ["ORD-SECOND", "ORD-TARGET"]


def test_batch_source_must_be_auto_donate_eligible():
    physical_key = PhysicalBufferKey("S1", ("P01", "P02"))
    source = _batch_group(
        physical_key=physical_key,
        main_id="MAIN-SOURCE",
        order_code="ORD-SOURCE",
        buffer_code="BUF-01",
        auto_donate_eligible=False,
    )
    target = _batch_group(
        physical_key=physical_key,
        main_id="MAIN-SOURCE",
        order_code="ORD-TARGET",
        buffer_code="BUF-TARGET",
    )
    candidate_snapshot = _with_batch(_candidate_snapshot(), source, target)
    warning = _warning().model_copy(update={"group_key": source.group_key})

    result = overflow_module.OverflowCandidateFinder().find_algorithm(
        candidate_snapshot,
        [warning],
        interval_results=[
            _group_interval(source, 3000),
            _group_interval(target, -1800),
        ],
    )[0]

    assert result.candidates == []


def test_overflow_group_keys_are_internal_only():
    physical_key = PhysicalBufferKey("S1", ("P01", "P02"))
    source = _batch_group(
        physical_key=physical_key,
        main_id="MAIN-SOURCE",
        order_code="ORD-SOURCE",
        buffer_code="BUF-01",
    )
    target = _batch_group(
        physical_key=physical_key,
        main_id="MAIN-SOURCE",
        order_code="ORD-TARGET",
        buffer_code="BUF-TARGET",
    )
    candidate_snapshot = _with_batch(_candidate_snapshot(), source, target)
    warning = _warning().model_copy(update={"group_key": source.group_key})
    result = overflow_module.OverflowCandidateFinder().find_algorithm(
        candidate_snapshot,
        [warning],
        interval_results=[
            _group_interval(source, 3000),
            _group_interval(target, -1800),
        ],
    )[0]

    dumped = result.model_dump()

    assert "source_group_key" not in dumped
    assert "source_group_key" not in dumped["candidates"][0]
    assert "target_group_key" not in dumped["candidates"][0]["target_options"][0]


def test_batch_source_rate_must_be_finite():
    physical_key = PhysicalBufferKey("S1", ("P01", "P02"))
    source = _batch_group(
        physical_key=physical_key,
        main_id="MAIN-SOURCE",
        order_code="ORD-SOURCE",
        buffer_code="BUF-01",
    )
    target = _batch_group(
        physical_key=physical_key,
        main_id="MAIN-TARGET",
        order_code="ORD-TARGET",
        buffer_code="BUF-TARGET",
    )
    candidate_snapshot = _with_batch(_candidate_snapshot(), source, target)
    warning = _warning().model_copy(update={"group_key": source.group_key})
    invalid_source_rate = _group_interval(source, 3000).model_copy(
        update={"inventory_change_rate": float("nan")}
    )

    with pytest.raises(
        overflow_module.CandidateMachineCalculationError,
        match="source group rate.*finite",
    ):
        overflow_module.OverflowCandidateFinder().find_algorithm(
            candidate_snapshot,
            [warning],
            interval_results=[
                invalid_source_rate,
                _group_interval(target, -1800),
            ],
        )
