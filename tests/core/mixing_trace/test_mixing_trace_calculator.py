from datetime import datetime
from importlib.machinery import PathFinder
from importlib.util import find_spec

import pytest

from app.schemas.common_schema import (
    AlgorithmActiveCutlineEvent,
    AlgorithmConfig,
    AlgorithmMachineMaster,
    AlgorithmMachineProductCapacity,
    AlgorithmMachineRuntime,
    AlgorithmOrder,
)
from app.schemas.request_schema import AlgorithmSnapshot
from app.schemas.result_schema import (
    AlgorithmCutlineDecisionResult,
    AlgorithmOverflowCutlinePlan,
    AlgorithmSelectedMachineEvaluation,
    AlgorithmStockoutCutlinePlan,
)


PLAN_TIME = datetime(2026, 7, 16, 10, 0)


@pytest.mark.parametrize(
    "module_name",
    [
        "app.core.mix_trace.mix_start_calculator",
        "app.api.mix_trace_api",
        "app.service.mix_trace_service",
        "app.core.silk_screen.silk_screen_handler",
    ],
)
def test_removed_legacy_modules_are_not_importable(module_name):
    assert find_spec(module_name) is None


def test_removed_legacy_mix_trace_package_has_no_importable_initializer():
    core_spec = find_spec("app.core")
    assert core_spec is not None

    spec = PathFinder.find_spec(
        "app.core.mix_trace",
        core_spec.submodule_search_locations,
    )

    assert spec is None or spec.loader is None


def calculator():
    from app.core.mixing_trace import MixingTraceCalculator

    return MixingTraceCalculator()


def selected_machine(
    machine_code="pk03",
    *,
    source_order_code="ORD-A",
    target_order_code="ORD-B",
    workshop_code="S2",
    process_code="PK",
):
    return AlgorithmSelectedMachineEvaluation(
        machine_code=machine_code,
        source_order_code=source_order_code,
        target_order_code=target_order_code,
        source_buffer_code=f"BUF-SOURCE-{machine_code}",
        target_buffer_code=f"BUF-TARGET-{machine_code}",
        process_code=process_code,
        workshop_code=workshop_code,
        wafer_size="182",
        source_wafer_spec="R",
        target_wafer_spec="N",
        contribution_capacity=1,
        utilization_rate=0.5,
        idle_rate=0.5,
        source_net_rate_before=0,
        source_net_rate_after=0,
        target_net_rate_before=0,
        target_net_rate_after=0,
    )


def order(order_code, product_code, workshop_code="S2"):
    return AlgorithmOrder(
        order_code=order_code,
        order_status="RUNNING",
        product_code=product_code,
        product_name=product_code,
        workshop_code=workshop_code,
        workshop_name=workshop_code,
        total_quantity=10000,
        produced_quantity=1000,
        piece_source="A",
        estimated_yield="99%",
    )


def runtime(
    machine_code="pk03",
    *,
    input_quantity_30m=5000,
    output_quantity_30m=4800,
):
    return AlgorithmMachineRuntime(
        machine_code=machine_code,
        status="running",
        current_order_code="ORD-A",
        tangent_time=None,
        input_quantity_30m=input_quantity_30m,
        output_quantity_30m=output_quantity_30m,
        period_quantity_30m=999999,
        out_time=None,
    )


def unchecked_runtime(
    machine_code="pk03",
    *,
    input_quantity_30m=5000,
    output_quantity_30m=4800,
):
    return AlgorithmMachineRuntime.model_construct(
        machine_code=machine_code,
        status="running",
        current_order_code="ORD-A",
        tangent_time=None,
        input_quantity_30m=input_quantity_30m,
        output_quantity_30m=output_quantity_30m,
        period_quantity_30m=999999,
        out_time=None,
    )


def machine_master(
    machine_code="pk03",
    *,
    process_code="PK",
    process_name="硼扩",
):
    return AlgorithmMachineMaster(
        machine_code=machine_code,
        machine_name=machine_code,
        process_code=process_code,
        process_name=process_name,
    )


def capacity(
    machine_code="pk03",
    product_code="HG210R",
    *,
    proc_seconds=3600,
    actual_capacity=1,
):
    return AlgorithmMachineProductCapacity(
        machine_code=machine_code,
        product_code=product_code,
        proc_seconds=proc_seconds,
        actual_capacity=actual_capacity,
    )


def unchecked_capacity(
    machine_code="pk03",
    product_code="HG210R",
    *,
    proc_seconds=3600,
    actual_capacity=1,
):
    return AlgorithmMachineProductCapacity.model_construct(
        machine_code=machine_code,
        product_code=product_code,
        proc_seconds=proc_seconds,
        actual_capacity=actual_capacity,
    )


def snapshot(
    *,
    current_time=PLAN_TIME,
    machine_runtimes=None,
    machine_masters=None,
    machine_product_capacities=None,
    orders=None,
    config=None,
):
    return AlgorithmSnapshot(
        current_time=current_time,
        workshops=[],
        lines=[],
        machine_lines=[],
        machine_runtimes=(
            [runtime()] if machine_runtimes is None else machine_runtimes
        ),
        machine_masters=(
            [machine_master()] if machine_masters is None else machine_masters
        ),
        machine_product_capacities=(
            [capacity()]
            if machine_product_capacities is None
            else machine_product_capacities
        ),
        orders=(
            [order("ORD-A", "HG210R"), order("ORD-B", "HG182T")]
            if orders is None
            else orders
        ),
        products=[],
        process_routes=[],
        buffer_masters=[],
        buffer_process_relations=[],
        buffer_order_inventories=[],
        agv_relations=[],
        config=config or AlgorithmConfig(),
    )


def mixing_event(
    *,
    event_id="EVENT-REAL-001",
    plan_id="PLAN001",
    cutline_start_time=PLAN_TIME,
):
    return AlgorithmActiveCutlineEvent(
        event_id=event_id,
        plan_id=plan_id,
        warning_id="WARNING-001",
        machine_code="pk03",
        source_order_code="ORD-A",
        target_order_code="ORD-B",
        workshop_code="S2",
        source_buffer_code="BUF-SOURCE-pk03",
        target_buffer_code="BUF-TARGET-pk03",
        upstream_process_code="PK",
        downstream_process_code="NEXT",
        source_wafer_size="210",
        source_wafer_spec="R",
        target_wafer_size="182",
        target_wafer_spec="N",
        cutline_start_time=cutline_start_time,
        status="active",
        warning_type="stockout",
        process_code="PK",
        warning_buffer_code="BUF-TARGET",
        warning_upstream_process_code="PK",
        warning_downstream_process_code="NEXT",
        is_recommended_candidate=True,
    )


def stockout_plan(*machines, plan_id="PLAN001", calculation_time=PLAN_TIME):
    selected = list(machines) or [selected_machine()]
    return AlgorithmStockoutCutlinePlan(
        plan_id=plan_id,
        calculation_time=calculation_time,
        workshop_code="S2",
        buffer_code="BUF-TARGET",
        order_code="ORD-B",
        wafer_size="182",
        wafer_spec="N",
        upstream_process_code="PK",
        downstream_process_code="NEXT",
        initial_capacity_gap=1,
        total_contribution_capacity=1,
        remaining_capacity_gap=0,
        selected_machines=selected,
    )


def overflow_plan(*machines, plan_id="PLAN-OVERFLOW"):
    selected = list(machines) or [
        selected_machine().model_copy(
            update={"contribution_capacity": None, "reduced_capacity": 1}
        )
    ]
    return AlgorithmOverflowCutlinePlan(
        plan_id=plan_id,
        calculation_time=PLAN_TIME,
        workshop_code="S2",
        buffer_code="BUF-SOURCE",
        source_order_code="ORD-A",
        source_wafer_size="210",
        source_wafer_spec="R",
        upstream_process_code="PK",
        downstream_process_code="NEXT",
        initial_growth_rate=1,
        total_reduced_capacity=1,
        remaining_growth_rate=0,
        selected_machines=selected,
    )


def test_example_plan_generates_compact_trace_record():
    result = calculator().calculate_for_plan(
        snapshot=snapshot(),
        plan=stockout_plan(),
    )

    assert result.failures == []
    assert len(result.records) == 1
    record = result.records[0]
    assert record.model_dump() == {
        "mix_trace_id": "MIX-PLAN001-pk03",
        "plan_id": "PLAN001",
        "cutline_event_id": "CUT-PLAN001-pk03",
        "machine_code": "pk03",
        "workshop_code": "S2",
        "process_code": "PK",
        "process_name": "硼扩",
        "source_order_code": "ORD-A",
        "target_order_code": "ORD-B",
        "source_product_code": "HG210R",
        "target_product_code": "HG182T",
        "mix_start_time": datetime(2026, 7, 16, 11, 12, 30),
        "mixed_basket_start_index": 1,
        "mixed_basket_end_index": 10,
        "mixed_basket_count": 10,
        "estimated_total_mixed_pieces": 1200,
        "compositions": [
            {
                "order_code": "ORD-A",
                "product_code": "HG210R",
                "sequence": 1,
                "estimated_pieces": 600,
            },
            {
                "order_code": "ORD-B",
                "product_code": "HG182T",
                "sequence": 2,
                "estimated_pieces": 600,
            },
        ],
        "notification_status": "scheduled",
    }


def test_overflow_formal_plan_is_supported():
    result = calculator().calculate_for_plan(
        snapshot=snapshot(),
        plan=overflow_plan(),
    )

    assert [record.machine_code for record in result.records] == ["pk03"]
    assert result.failures == []


def test_notification_is_due_at_or_after_mix_start_time():
    result = calculator().calculate_for_plan(
        snapshot=snapshot(current_time=datetime(2026, 7, 16, 11, 12, 30)),
        plan=stockout_plan(),
    )

    assert result.records[0].notification_status == "due"


def test_explicit_fifteen_minute_execution_delay_is_preserved():
    result = calculator().calculate_for_plan(
        snapshot=snapshot(
            config=AlgorithmConfig(cutline_execution_delay_minutes=15)
        ),
        plan=stockout_plan(),
    )

    assert result.records[0].mix_start_time == datetime(2026, 7, 16, 11, 27, 30)


def test_event_uses_observed_cutline_time_without_plan_execution_delay():
    observed_time = datetime(2026, 7, 16, 10, 7)
    result = calculator().calculate_for_event(
        snapshot=snapshot(
            config=AlgorithmConfig(cutline_execution_delay_minutes=15)
        ),
        event=mixing_event(cutline_start_time=observed_time),
    )

    assert result.failures == []
    assert len(result.records) == 1
    record = result.records[0]
    assert record.cutline_event_id == "EVENT-REAL-001"
    assert record.mix_trace_id == "MIX-PLAN001-pk03"
    assert record.source_product_code == "HG210R"
    assert record.target_product_code == "HG182T"
    assert record.mix_start_time == datetime(2026, 7, 16, 11, 19, 30)


def test_custom_timing_and_basket_config_use_independent_fields():
    config = AlgorithmConfig(
        cutline_execution_delay_minutes=0,
        agv_delivery_minutes=0,
        mixed_basket_count=3,
        basket_capacity_pieces=101,
        mixing_input_max_baskets=2,
    )
    result = calculator().calculate_for_plan(
        snapshot=snapshot(
            config=config,
            machine_product_capacities=[capacity(proc_seconds=0)],
        ),
        plan=stockout_plan(),
    )

    record = result.records[0]
    assert record.mix_start_time == datetime(2026, 7, 16, 10, 1, 15, 750000)
    assert record.mixed_basket_end_index == 3
    assert record.estimated_total_mixed_pieces == 303
    assert [item.estimated_pieces for item in record.compositions] == [151, 152]


def test_actual_capacity_uses_minimum_realtime_quantity_and_ignores_static_value():
    first = calculator().calculate_for_plan(
        snapshot=snapshot(
            machine_product_capacities=[capacity(actual_capacity=1)]
        ),
        plan=stockout_plan(),
    )
    second = calculator().calculate_for_plan(
        snapshot=snapshot(
            machine_runtimes=[
                runtime(input_quantity_30m=4800, output_quantity_30m=5000)
            ],
            machine_product_capacities=[capacity(actual_capacity=999999)],
        ),
        plan=stockout_plan(),
    )

    assert first.records[0].mix_start_time == datetime(2026, 7, 16, 11, 12, 30)
    assert second.records[0].mix_start_time == first.records[0].mix_start_time


def test_realtime_quantity_changes_mix_start_time():
    result = calculator().calculate_for_plan(
        snapshot=snapshot(
            machine_runtimes=[
                runtime(input_quantity_30m=2400, output_quantity_30m=5000)
            ]
        ),
        plan=stockout_plan(),
    )

    assert result.records[0].mix_start_time == datetime(2026, 7, 16, 11, 20)


@pytest.mark.parametrize(
    ("input_quantity", "output_quantity", "reason"),
    [
        (-1, 1, "runtime_quantity_invalid"),
        (1, float("nan"), "runtime_quantity_invalid"),
        (float("inf"), 1, "runtime_quantity_invalid"),
        (True, 1, "runtime_quantity_invalid"),
        (0, 5000, "runtime_actual_capacity_unavailable"),
        (5000, 0, "runtime_actual_capacity_unavailable"),
        (0, 0, "runtime_actual_capacity_unavailable"),
    ],
)
def test_invalid_or_unavailable_realtime_capacity_returns_failure(
    input_quantity,
    output_quantity,
    reason,
):
    result = calculator().calculate_for_plan(
        snapshot=snapshot(
            machine_runtimes=[
                unchecked_runtime(
                    input_quantity_30m=input_quantity,
                    output_quantity_30m=output_quantity,
                )
            ]
        ),
        plan=stockout_plan(),
    )

    assert result.records == []
    assert [failure.reason for failure in result.failures] == [reason]


@pytest.mark.parametrize(
    ("machine_runtimes", "reason"),
    [
        ([], "machine_runtime_not_found"),
        ([runtime(), runtime()], "machine_runtime_ambiguous"),
    ],
)
def test_runtime_must_be_uniquely_located(machine_runtimes, reason):
    result = calculator().calculate_for_plan(
        snapshot=snapshot(machine_runtimes=machine_runtimes),
        plan=stockout_plan(),
    )

    assert [failure.reason for failure in result.failures] == [reason]


def test_source_process_duration_changes_time_but_target_duration_does_not():
    baseline = calculator().calculate_for_plan(
        snapshot=snapshot(
            machine_product_capacities=[
                capacity(proc_seconds=3600),
                capacity(product_code="HG182T", proc_seconds=1),
            ]
        ),
        plan=stockout_plan(),
    )
    changed_target = calculator().calculate_for_plan(
        snapshot=snapshot(
            machine_product_capacities=[
                capacity(proc_seconds=3600),
                capacity(product_code="HG182T", proc_seconds=9999),
            ]
        ),
        plan=stockout_plan(),
    )
    changed_source = calculator().calculate_for_plan(
        snapshot=snapshot(
            machine_product_capacities=[capacity(proc_seconds=0)]
        ),
        plan=stockout_plan(),
    )

    assert changed_target.records[0].mix_start_time == baseline.records[0].mix_start_time
    assert changed_source.records[0].mix_start_time == datetime(2026, 7, 16, 10, 12, 30)


@pytest.mark.parametrize(
    ("records", "reason"),
    [
        ([], "process_duration_not_found"),
        ([capacity(), capacity()], "process_duration_ambiguous"),
        (
            [unchecked_capacity(proc_seconds=-1)],
            "process_duration_invalid",
        ),
        (
            [unchecked_capacity(proc_seconds=float("nan"))],
            "process_duration_invalid",
        ),
        (
            [unchecked_capacity(proc_seconds=True)],
            "process_duration_invalid",
        ),
    ],
)
def test_process_duration_must_be_unique_and_valid(records, reason):
    result = calculator().calculate_for_plan(
        snapshot=snapshot(machine_product_capacities=records),
        plan=stockout_plan(),
    )

    assert [failure.reason for failure in result.failures] == [reason]


@pytest.mark.parametrize(
    ("orders", "reason"),
    [
        ([order("ORD-B", "HG182T")], "source_order_not_found"),
        ([order("ORD-A", "HG210R")], "target_order_not_found"),
    ],
)
def test_source_and_target_orders_must_exist(orders, reason):
    result = calculator().calculate_for_plan(
        snapshot=snapshot(orders=orders),
        plan=stockout_plan(),
    )

    assert [failure.reason for failure in result.failures] == [reason]


def test_embedded_plan_product_must_match_order_product():
    machine = selected_machine().model_copy(
        update={"source_product_code": "WRONG"}
    )
    result = calculator().calculate_for_plan(
        snapshot=snapshot(),
        plan=stockout_plan(machine),
    )

    assert [failure.reason for failure in result.failures] == [
        "cutline_plan_product_mismatch"
    ]


def test_same_order_transition_is_invalid():
    machine = selected_machine(target_order_code="ORD-A")
    result = calculator().calculate_for_plan(
        snapshot=snapshot(),
        plan=stockout_plan(machine),
    )

    assert [failure.reason for failure in result.failures] == [
        "same_order_transition_invalid"
    ]


def test_same_product_different_order_returns_no_mixing_failure():
    result = calculator().calculate_for_plan(
        snapshot=snapshot(
            orders=[order("ORD-A", "HG210R"), order("ORD-B", "HG210R")]
        ),
        plan=stockout_plan(),
    )

    assert result.records == []
    assert [failure.reason for failure in result.failures] == [
        "same_product_transition_no_mixing"
    ]


def test_machine_process_context_must_be_unique_and_consistent():
    result = calculator().calculate_for_plan(
        snapshot=snapshot(machine_masters=[]),
        plan=stockout_plan(),
    )

    assert [failure.reason for failure in result.failures] == [
        "selected_machine_context_incomplete"
    ]


def test_three_machines_use_independent_runtime_and_source_duration_then_sort():
    machines = [
        selected_machine("M01", source_order_code="S1", target_order_code="T1"),
        selected_machine("M02", source_order_code="S2", target_order_code="T2"),
        selected_machine("M03", source_order_code="S3", target_order_code="T3"),
    ]
    result = calculator().calculate_for_plan(
        snapshot=snapshot(
            machine_runtimes=[
                runtime("M01", input_quantity_30m=4800, output_quantity_30m=5000),
                runtime("M02", input_quantity_30m=2400, output_quantity_30m=2400),
                runtime("M03", input_quantity_30m=1200, output_quantity_30m=1200),
            ],
            machine_masters=[
                machine_master("M01"),
                machine_master("M02"),
                machine_master("M03"),
            ],
            machine_product_capacities=[
                capacity("M01", "PS1", proc_seconds=3600),
                capacity("M02", "PS2", proc_seconds=0),
                capacity("M03", "PS3", proc_seconds=600),
            ],
            orders=[
                order("S1", "PS1"), order("T1", "PT1"),
                order("S2", "PS2"), order("T2", "PT2"),
                order("S3", "PS3"), order("T3", "PT3"),
            ],
        ),
        plan=stockout_plan(*machines),
    )

    assert result.failures == []
    assert [record.machine_code for record in result.records] == [
        "M02",
        "M03",
        "M01",
    ]
    assert [record.mix_start_time for record in result.records] == [
        datetime(2026, 7, 16, 10, 20),
        datetime(2026, 7, 16, 10, 45),
        datetime(2026, 7, 16, 11, 12, 30),
    ]


def test_one_machine_failure_does_not_block_other_machines():
    machines = [
        selected_machine("M03", source_order_code="S3", target_order_code="T3"),
        selected_machine("M02", source_order_code="S2", target_order_code="T2"),
        selected_machine("M01", source_order_code="S1", target_order_code="T1"),
    ]
    result = calculator().calculate_for_plan(
        snapshot=snapshot(
            machine_runtimes=[
                runtime("M01"),
                runtime("M02", input_quantity_30m=0, output_quantity_30m=5000),
                runtime("M03"),
            ],
            machine_masters=[
                machine_master("M01"),
                machine_master("M02"),
                machine_master("M03"),
            ],
            machine_product_capacities=[
                capacity("M01", "PS1"),
                capacity("M02", "PS2"),
                capacity("M03", "PS3"),
            ],
            orders=[
                order("S1", "PS1"), order("T1", "PT1"),
                order("S2", "PS2"), order("T2", "PT2"),
                order("S3", "PS3"), order("T3", "PT3"),
            ],
        ),
        plan=stockout_plan(*machines),
    )

    assert [record.machine_code for record in result.records] == ["M01", "M03"]
    assert [(item.machine_code, item.reason) for item in result.failures] == [
        ("M02", "runtime_actual_capacity_unavailable")
    ]


def test_unrepresentable_mix_time_is_isolated_from_other_machine():
    machines = [
        selected_machine("M01", source_order_code="S1", target_order_code="T1"),
        selected_machine("M02", source_order_code="S2", target_order_code="T2"),
    ]
    result = calculator().calculate_for_plan(
        snapshot=snapshot(
            machine_runtimes=[runtime("M01"), runtime("M02")],
            machine_masters=[machine_master("M01"), machine_master("M02")],
            machine_product_capacities=[
                capacity("M01", "PS1", proc_seconds=1e308),
                capacity("M02", "PS2", proc_seconds=0),
            ],
            orders=[
                order("S1", "PS1"), order("T1", "PT1"),
                order("S2", "PS2"), order("T2", "PT2"),
            ],
        ),
        plan=stockout_plan(*machines),
    )

    assert [record.machine_code for record in result.records] == ["M02"]
    assert [(item.machine_code, item.reason) for item in result.failures] == [
        ("M01", "mix_start_time_unrepresentable")
    ]


def test_missing_process_duration_does_not_block_other_machine():
    machines = [
        selected_machine("M01", source_order_code="S1", target_order_code="T1"),
        selected_machine("M02", source_order_code="S2", target_order_code="T2"),
    ]
    result = calculator().calculate_for_plan(
        snapshot=snapshot(
            machine_runtimes=[runtime("M01"), runtime("M02")],
            machine_masters=[machine_master("M01"), machine_master("M02")],
            machine_product_capacities=[capacity("M02", "PS2")],
            orders=[
                order("S1", "PS1"), order("T1", "PT1"),
                order("S2", "PS2"), order("T2", "PT2"),
            ],
        ),
        plan=stockout_plan(*machines),
    )

    assert [record.machine_code for record in result.records] == ["M02"]
    assert [(item.machine_code, item.reason) for item in result.failures] == [
        ("M01", "process_duration_not_found")
    ]


def test_failures_are_sorted_by_machine_and_cutline_event_id():
    machines = [
        selected_machine("M03", source_order_code="S3", target_order_code="T3"),
        selected_machine("M01", source_order_code="S1", target_order_code="T1"),
        selected_machine("M02", source_order_code="S2", target_order_code="T2"),
    ]
    result = calculator().calculate_for_plan(
        snapshot=snapshot(
            machine_runtimes=[],
            machine_masters=[
                machine_master("M01"),
                machine_master("M02"),
                machine_master("M03"),
            ],
            machine_product_capacities=[],
            orders=[
                order("S1", "PS1"), order("T1", "PT1"),
                order("S2", "PS2"), order("T2", "PT2"),
                order("S3", "PS3"), order("T3", "PT3"),
            ],
        ),
        plan=stockout_plan(*machines),
    )

    assert [failure.machine_code for failure in result.failures] == [
        "M01",
        "M02",
        "M03",
    ]


def test_repeated_calculation_has_stable_ids_and_no_internal_history():
    calc = calculator()
    first = calc.calculate_for_plan(snapshot=snapshot(), plan=stockout_plan())
    repeated = calc.calculate_for_plan(snapshot=snapshot(), plan=stockout_plan())
    second_plan = calc.calculate_for_plan(
        snapshot=snapshot(),
        plan=stockout_plan(plan_id="PLAN002"),
    )

    assert first.records[0].mix_trace_id == repeated.records[0].mix_trace_id
    assert first.records[0].cutline_event_id == repeated.records[0].cutline_event_id
    assert second_plan.records[0].mix_trace_id == "MIX-PLAN002-pk03"
    assert second_plan.records[0].mix_trace_id != first.records[0].mix_trace_id


def test_manual_intervention_decision_returns_empty_batch():
    decision = AlgorithmCutlineDecisionResult.model_construct(
        plan=None,
        manual_intervention=object(),
    )

    result = calculator().calculate_for_decision(
        snapshot=snapshot(),
        decision=decision,
    )

    assert result.records == []
    assert result.failures == []


def test_decision_with_formal_plan_calculates_records():
    decision = AlgorithmCutlineDecisionResult(
        plan=stockout_plan(),
        manual_intervention=None,
    )

    result = calculator().calculate_for_decision(
        snapshot=snapshot(),
        decision=decision,
    )

    assert len(result.records) == 1


def test_ineligible_or_empty_formal_plan_returns_empty_batch():
    ineligible = stockout_plan().model_copy(update={"risk_resolved": False})
    empty = stockout_plan().model_copy(update={"selected_machines": []})

    ineligible_result = calculator().calculate_for_plan(
        snapshot=snapshot(),
        plan=ineligible,
    )
    empty_result = calculator().calculate_for_plan(
        snapshot=snapshot(),
        plan=empty,
    )

    assert ineligible_result.records == ineligible_result.failures == []
    assert empty_result.records == empty_result.failures == []


def test_calculation_does_not_mutate_inputs():
    current_snapshot = snapshot()
    current_plan = stockout_plan()
    before = current_snapshot.model_dump(), current_plan.model_dump()

    calculator().calculate_for_plan(
        snapshot=current_snapshot,
        plan=current_plan,
    )

    assert current_snapshot.model_dump() == before[0]
    assert current_plan.model_dump() == before[1]
