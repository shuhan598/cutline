import importlib
from dataclasses import replace

import pytest

from app.core.buffer_aggregation.models import (
    GroupKey,
    MainBufferAggregationBatch,
    MainBufferGroup,
    PhysicalMainBufferState,
    PhysicalBufferKey,
)
from app.core.cutline_plan.plan_builder import CutlinePlanBuilder
from app.schemas.common_schema import AlgorithmMachineProductCapacity

from tests.core.cutline_plan.helpers import (
    algorithm_snapshot,
    default_overflow_intervals,
    default_overflow_states,
    interval,
    overflow_candidate,
    overflow_candidates,
    overflow_state,
    overflow_target,
    overflow_warning,
)


def _evaluator():
    module = importlib.import_module(
        "app.core.cutline_plan.machine_selection_evaluator"
    )
    return module.MachineSelectionEvaluator(), module


def _select(
    candidates,
    *,
    warning=None,
    intervals=None,
    overflows=None,
    snapshot_value=None,
):
    evaluator, _ = _evaluator()
    return evaluator.select_overflow_machines(
        snapshot=snapshot_value or algorithm_snapshot(),
        warning=warning or overflow_warning(),
        candidate_result=candidates,
        interval_results=intervals or default_overflow_intervals(),
        overflow_results=overflows or default_overflow_states(),
    )


def _batch_group(
    order_code: str,
    buffer_code: str,
    *,
    physical_key: PhysicalBufferKey,
    main_id: str | None = None,
    total_inventory: float = 1000,
    total_capacity: float = 100000,
) -> MainBufferGroup:
    main_id = main_id or f"MAIN-{buffer_code}"
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
        total_inventory=total_inventory,
        total_capacity=total_capacity,
        remaining_capacity=total_capacity - total_inventory,
        representative_buffer_code=buffer_code,
        stockout_eligible=True,
        overflow_eligible=True,
        stockout_warning_eligible=True,
        overflow_warning_eligible=True,
        auto_receive_eligible=True,
        auto_donate_eligible=True,
    )


def _batch_context(
    *,
    source_rate: float = 10000,
    source_inventory: float = 1000,
    source_capacity: float = 1100,
    targets: tuple[tuple[str, str, float, float, float], ...] = (
        ("ORD-TARGET", "BUF-TARGET", -1000, 1000, 3900),
    ),
):
    physical_key = PhysicalBufferKey("S1", ("P01", "P02"))
    source = _batch_group(
        "ORD-SOURCE",
        "BUF-OVERFLOW",
        physical_key=physical_key,
        main_id="MAIN-BUF-OVERFLOW",
        total_inventory=source_inventory,
        total_capacity=source_capacity,
    )
    target_groups = {
        order_code: _batch_group(
            order_code,
            buffer_code,
            physical_key=physical_key,
            main_id=source.main_id,
            total_inventory=inventory,
            total_capacity=capacity,
        )
        for order_code, buffer_code, _, inventory, capacity in targets
    }
    groups = (source, *target_groups.values())
    batch = MainBufferAggregationBatch(
        groups=groups,
        groups_by_group_key={group.group_key: group for group in groups},
        group_keys_by_main_id={
            source.main_id: tuple(group.group_key for group in groups),
        },
        group_key_by_buffer_code={
            code: group.group_key
            for group in groups
            for code in group.buffer_codes
        },
        group_key_by_representative_buffer_code={
            group.representative_buffer_code: group.group_key
            for group in groups
        },
        group_keys_by_physical_buffer_key={
            physical_key: tuple(group.group_key for group in groups)
        },
        physical_main_buffers_by_main_id={
            source.main_id: PhysicalMainBufferState(
                main_id=source.main_id,
                workshop_code=source.workshop_code,
                ordered_service_process_codes=source.ordered_service_process_codes,
                physical_buffer_key=physical_key,
                buffer_codes=tuple(group.representative_buffer_code for group in groups),
                total_inventory=sum(group.total_inventory for group in groups),
                total_capacity=sum(group.total_capacity for group in groups),
                remaining_capacity=sum(group.total_capacity for group in groups)
                - sum(group.total_inventory for group in groups),
                representative_buffer_code=source.representative_buffer_code,
                order_codes=tuple(group.order_code for group in groups),
            )
        },
    )
    snapshot_value = algorithm_snapshot()
    snapshot_value.main_buffer_batch = batch
    snapshot_value.machine_product_capacities = [
        AlgorithmMachineProductCapacity(
            machine_code=machine_code,
            product_code=group.product_code,
            proc_seconds=1.0,
            actual_capacity=100.0,
        )
        for machine_code in ("M-01", "M-02", "M-03")
        for group in target_groups.values()
    ]
    warning = overflow_warning(
        buffer_growth_rate=source_rate,
        total_inventory=source_inventory,
        max_capacity=source_capacity,
    ).model_copy(
        update={
            "group_key": source.group_key,
            "order_growth_details": [],
        }
    )
    intervals = [
        interval(
            buffer_code=source.representative_buffer_code,
            order_code=source.order_code,
            downstream_process_code="P02",
            current_quantity=source.total_inventory,
            net_consumption_rate=-source_rate,
        ).model_copy(
            update={
                "main_id": source.main_id,
                "inventory_change_rate": source_rate,
                "group_key": source.group_key,
            }
        )
    ]
    for order_code, buffer_code, rate, inventory, _ in targets:
        group = target_groups[order_code]
        intervals.append(
            interval(
                buffer_code=buffer_code,
                order_code=order_code,
                downstream_process_code="P02",
                current_quantity=inventory,
                net_consumption_rate=-rate,
            ).model_copy(
                update={
                    "main_id": group.main_id,
                    "inventory_change_rate": rate,
                    "group_key": group.group_key,
                }
            )
        )
    return snapshot_value, warning, intervals, source, target_groups


def _batch_candidates(source, target_groups, *candidates):
    keyed_candidates = []
    for candidate in candidates:
        source_group_key = candidate.source_group_key or source.group_key
        keyed_options = []
        for option in candidate.target_options:
            target_group = target_groups[option.target_order_code]
            keyed_options.append(
                option.model_copy(
                    update={
                        "target_group_key": target_group.group_key,
                        "target_product_code": target_group.product_code,
                        "target_buffer_code": (
                            target_group.representative_buffer_code
                        ),
                        "target_workshop_code": target_group.workshop_code,
                        "target_upstream_process_code": "P01",
                        "target_downstream_process_code": "P02",
                    }
                )
            )
        keyed_candidates.append(
            candidate.model_copy(
                update={
                    "source_group_key": source_group_key,
                    "target_options": keyed_options,
                }
            )
        )
    return overflow_candidates(*keyed_candidates).model_copy(
        update={"source_group_key": source.group_key}
    )


def _candidate_for_source(candidate, source):
    return candidate.model_copy(
        update={
            "current_order_code": source.order_code,
            "current_order_name": source.order_code,
            "current_product_code": source.product_code,
            "source_group_key": source.group_key,
        }
    )


def test_first_machine_and_first_safe_target_are_selected():
    result = _select(
        overflow_candidates(
            overflow_candidate("M-01", 10000, overflow_target())
        )
    )

    assert [item.machine_code for item in result.selected_machines] == ["M-01"]
    assert result.selected_machines[0].target_order_code == "ORD-TARGET"
    assert result.total_reduced_capacity == 10000
    assert result.remaining_growth_rate == 0
    assert result.updated_overflow_minutes is None
    assert result.risk_resolved is True


def test_failed_first_target_option_does_not_block_second_option():
    intervals = default_overflow_intervals()
    intervals.append(
        interval(
            buffer_code="BUF-SAFE",
            order_code="ORD-SAFE",
            downstream_process_code="P04",
            net_consumption_rate=1000,
        )
    )
    overflows = default_overflow_states()
    overflows.append(
        overflow_state(
            "BUF-SAFE",
            max_capacity=1000000,
            downstream_process_code="P04",
        )
    )
    result = _select(
        overflow_candidates(
            overflow_candidate(
                "M-01",
                10000,
                overflow_target(buffer_code="BUF-OVERFLOW"),
                overflow_target(
                    "ORD-SAFE",
                    buffer_code="BUF-SAFE",
                    downstream_process_code="P04",
                ),
            )
        ),
        intervals=intervals,
        overflows=overflows,
    )

    assert len(result.selected_machines) == 1
    assert result.selected_machines[0].target_order_code == "ORD-SAFE"
    assert result.rejected_machines == []


def test_one_machine_selects_only_one_target_option():
    intervals = default_overflow_intervals()
    intervals.append(
        interval(
            buffer_code="BUF-SECOND",
            order_code="ORD-SECOND",
            downstream_process_code="P04",
            net_consumption_rate=900,
        )
    )
    overflows = default_overflow_states()
    overflows.append(overflow_state("BUF-SECOND", downstream_process_code="P04"))
    result = _select(
        overflow_candidates(
            overflow_candidate(
                "M-01",
                10000,
                overflow_target(),
                overflow_target(
                    "ORD-SECOND",
                    buffer_code="BUF-SECOND",
                    downstream_process_code="P04",
                ),
            )
        ),
        intervals=intervals,
        overflows=overflows,
    )

    assert len(result.selected_machines) == 1
    assert result.selected_machines[0].target_order_code == "ORD-TARGET"


def test_all_targets_in_current_overflow_buffer_reject_the_machine():
    result = _select(
        overflow_candidates(
            overflow_candidate(
                "M-01",
                10000,
                overflow_target(buffer_code="BUF-OVERFLOW"),
            )
        )
    )

    assert result.selected_machines == []
    assert result.rejected_machines[0].reason == "target_in_same_overflow_buffer"
    assert result.failure_reason == "no_valid_target_order"


def test_source_stockout_risk_rejects_the_entire_machine():
    result = _select(
        overflow_candidates(
            overflow_candidate("M-01", 10000, overflow_target())
        ),
        intervals=default_overflow_intervals(
            source_net_rate=0,
            source_quantity=0,
        ),
    )

    assert result.selected_machines == []
    assert len(result.rejected_machines) == 1
    assert result.rejected_machines[0].reason == "source_order_stockout_risk"


@pytest.mark.parametrize("remaining_capacity", [4999, 5000])
def test_target_overflow_at_or_inside_lead_time_rejects_target_option(
    remaining_capacity,
):
    result = _select(
        overflow_candidates(
            overflow_candidate("M-01", 10000, overflow_target())
        ),
        overflows=default_overflow_states(
            target_total_inventory=10000 - remaining_capacity,
            target_max_capacity=10000,
        ),
    )

    assert result.selected_machines == []
    assert result.rejected_machines[0].reason == "target_buffer_overflow_risk"


def test_source_risk_uses_stockout_config_not_overflow_warning_lead():
    result = _select(
        overflow_candidates(
            overflow_candidate("M-01", 1000, overflow_target())
        ),
        warning=overflow_warning(
            overflow_warning_lead_minutes=5,
            max_capacity=500,
        ),
        intervals=default_overflow_intervals(
            source_net_rate=0,
            source_quantity=500,
        ),
        snapshot_value=algorithm_snapshot(
            stockout_warning_lead_minutes=30,
            overflow_warning_lead_minutes=5,
        ),
    )

    assert result.selected_machines == []
    assert result.rejected_machines[0].reason == "source_order_stockout_risk"


def test_target_risk_uses_overflow_config_even_when_warning_lead_is_shorter():
    result = _select(
        overflow_candidates(
            overflow_candidate("M-01", 10000, overflow_target())
        ),
        warning=overflow_warning(overflow_warning_lead_minutes=5),
        overflows=default_overflow_states(
            target_total_inventory=5000,
            target_max_capacity=10000,
        ),
        snapshot_value=algorithm_snapshot(
            stockout_warning_lead_minutes=5,
            overflow_warning_lead_minutes=30,
        ),
    )

    assert result.selected_machines == []
    assert result.rejected_machines[0].reason == "target_buffer_overflow_risk"


def test_negative_target_net_rate_after_is_allowed_when_buffer_is_safe():
    result = _select(
        overflow_candidates(
            overflow_candidate("M-01", 2000, overflow_target())
        ),
        intervals=default_overflow_intervals(target_net_rate=1000),
        overflows=default_overflow_states(source_max_capacity=3000),
        warning=overflow_warning(max_capacity=3000),
    )

    assert result.selected_machines[0].target_net_rate_after == -1000


def test_selection_continues_until_current_overflow_risk_is_resolved():
    result = _select(
        overflow_candidates(
            overflow_candidate("M-01", 3000, overflow_target()),
            overflow_candidate("M-02", 7000, overflow_target()),
        ),
        warning=overflow_warning(max_capacity=1000),
        overflows=default_overflow_states(source_max_capacity=1000),
    )

    assert [item.machine_code for item in result.selected_machines] == [
        "M-01",
        "M-02",
    ]
    assert result.remaining_growth_rate == 0
    assert result.risk_resolved is True


def test_positive_remaining_growth_is_safe_when_overflow_time_exceeds_lead():
    result = _select(
        overflow_candidates(
            overflow_candidate("M-01", 3000, overflow_target())
        )
    )

    assert result.remaining_growth_rate == 7000
    assert result.updated_overflow_minutes == pytest.approx(4000 / 7000 * 60)
    assert result.updated_overflow_minutes > 30
    assert result.risk_resolved is True


def test_candidates_exhausted_inside_warning_window_leaves_risk_unresolved():
    result = _select(
        overflow_candidates(
            overflow_candidate("M-01", 1000, overflow_target())
        ),
        warning=overflow_warning(max_capacity=3000),
        overflows=default_overflow_states(source_max_capacity=3000),
    )

    assert result.remaining_growth_rate == 9000
    assert result.updated_overflow_minutes == pytest.approx(20)
    assert result.risk_resolved is False
    assert result.failure_reason == "insufficient_reduced_capacity"


def test_current_overflow_risk_uses_warning_remaining_capacity():
    warning = overflow_warning().model_copy(
        update={"remaining_capacity": 1000}
    )
    result = _select(
        overflow_candidates(
            overflow_candidate("M-01", 7000, overflow_target())
        ),
        warning=warning,
    )

    assert result.remaining_growth_rate == 3000
    assert result.updated_overflow_minutes == pytest.approx(20)
    assert result.risk_resolved is False


def test_current_overflow_resolution_uses_overflow_config_not_warning_lead():
    result = _select(
        overflow_candidates(
            overflow_candidate("M-01", 7000, overflow_target())
        ),
        warning=overflow_warning(overflow_warning_lead_minutes=5).model_copy(
            update={"remaining_capacity": 1000}
        ),
        snapshot_value=algorithm_snapshot(
            stockout_warning_lead_minutes=5,
            overflow_warning_lead_minutes=30,
        ),
    )

    assert result.updated_overflow_minutes == pytest.approx(20)
    assert result.risk_resolved is False


def test_already_over_capacity_buffer_is_not_marked_resolved():
    result = _select(
        overflow_candidates(
            overflow_candidate("M-01", 10000, overflow_target())
        ),
        warning=overflow_warning(total_inventory=4000, max_capacity=4000),
        overflows=default_overflow_states(
            source_total_inventory=4000,
            source_max_capacity=4000,
        ),
    )

    assert result.remaining_growth_rate == 0
    assert result.updated_overflow_minutes == 0
    assert result.risk_resolved is False
    assert result.failure_reason == "current_buffer_already_over_capacity"


def test_zero_reduced_capacity_is_rejected_during_selection():
    result = _select(
        overflow_candidates(
            overflow_candidate("M-01", 0, overflow_target())
        )
    )

    assert result.selected_machines == []
    assert result.rejected_machines[0].reason == "no_effective_reduction"


def test_overflow_candidate_input_order_is_preserved_without_resorting():
    result = _select(
        overflow_candidates(
            overflow_candidate("M-02", 3000, utilization_rate=0.1),
            overflow_candidate("M-01", 7000, utilization_rate=0.9),
        ),
        warning=overflow_warning(max_capacity=3000),
        overflows=default_overflow_states(source_max_capacity=3000),
    )

    assert [item.machine_code for item in result.selected_machines] == [
        "M-02",
        "M-01",
    ]


def test_same_overflow_machine_code_cannot_be_selected_twice():
    result = _select(
        overflow_candidates(
            overflow_candidate("M-01", 3000),
            overflow_candidate("M-01", 3000),
            overflow_candidate("M-02", 7000),
        ),
        warning=overflow_warning(max_capacity=3000),
        overflows=default_overflow_states(source_max_capacity=3000),
    )

    assert [item.machine_code for item in result.selected_machines] == [
        "M-01",
        "M-02",
    ]
    assert any(
        item.reason == "duplicate_machine_selection"
        for item in result.rejected_machines
    )


def test_missing_target_interval_rejects_only_that_target_option():
    result = _select(
        overflow_candidates(
            overflow_candidate(
                "M-01",
                10000,
                overflow_target("ORD-MISSING", buffer_code="BUF-MISSING"),
            )
        )
    )

    assert result.selected_machines == []
    assert result.rejected_machines[0].reason == "target_interval_not_found"


def test_target_interval_without_context_is_rejected_as_ambiguous():
    intervals = default_overflow_intervals()
    intervals.append(
        interval(
            buffer_code="BUF-SECOND",
            order_code="ORD-TARGET",
            downstream_process_code="P04",
            net_consumption_rate=1000,
        )
    )
    result = _select(
        overflow_candidates(
            overflow_candidate(
                "M-01",
                10000,
                overflow_target(buffer_code=None, downstream_process_code=None),
            )
        ),
        intervals=intervals,
    )

    assert result.selected_machines == []
    assert result.rejected_machines[0].reason == "target_interval_ambiguous"


def test_candidate_source_must_remain_the_warning_max_growth_order():
    _, module = _evaluator()
    with pytest.raises(module.MachineSelectionEvaluationError, match="maximum growth"):
        _select(
            overflow_candidates(
                overflow_candidate("M-01", 10000),
                source_order_code="ORD-SECOND",
            )
        )


def test_overflow_selection_uses_cumulative_virtual_source_net_rate():
    result = _select(
        overflow_candidates(
            overflow_candidate("M-01", 6000),
            overflow_candidate("M-02", 6000),
        ),
        intervals=default_overflow_intervals(
            source_net_rate=-10000,
            source_quantity=100,
        ),
        warning=overflow_warning(max_capacity=1000),
        overflows=default_overflow_states(source_max_capacity=1000),
    )

    assert [item.machine_code for item in result.selected_machines] == ["M-01"]
    assert result.rejected_machines[-1].machine_code == "M-02"
    assert result.rejected_machines[-1].source_net_rate_before == -4000
    assert result.rejected_machines[-1].reason == "source_order_stockout_risk"


def test_overflow_selection_does_not_mutate_inputs():
    warning = overflow_warning()
    candidates = overflow_candidates(overflow_candidate("M-01", 10000))
    intervals = default_overflow_intervals()
    overflows = default_overflow_states()
    before = [
        warning.model_dump(),
        candidates.model_dump(),
        [item.model_dump() for item in intervals],
        [item.model_dump() for item in overflows],
    ]

    _select(
        candidates,
        warning=warning,
        intervals=intervals,
        overflows=overflows,
    )

    assert warning.model_dump() == before[0]
    assert candidates.model_dump() == before[1]
    assert [item.model_dump() for item in intervals] == before[2]
    assert [item.model_dump() for item in overflows] == before[3]


def test_batch_selection_dynamically_reranks_source_orders_after_virtual_apply():
    snapshot_value, warning, intervals, source, targets = _batch_context(
        source_rate=8000,
        source_capacity=1040,
        source_inventory=1000,
        targets=(
            ("ORD-B", "BUF-B", 5000, 1000, 1000),
            ("ORD-C", "BUF-C", -2000, 1000, 1000),
        ),
    )
    source_b = targets["ORD-B"]
    source_c = targets["ORD-C"]
    candidates = _batch_candidates(
        source,
        targets,
        overflow_candidate("M-01", 6000, overflow_target("ORD-B")),
        _candidate_for_source(
            overflow_candidate("M-02", 6000, overflow_target("ORD-C")),
            source_b,
        ),
    )

    result = _select(
        candidates,
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    assert [item.machine_code for item in result.selected_machines] == ["M-01", "M-02"]
    assert [item.source_order_code for item in result.selected_machines] == [
        source.order_code,
        source_b.order_code,
    ]
    assert result.selected_machines[1].source_net_rate_before == -5100
    assert result.risk_resolved is True
    assert source_c.order_code not in [
        item.source_order_code for item in result.selected_machines
    ]


def test_batch_selection_activates_an_initially_negative_virtual_source():
    snapshot_value, warning, intervals, source, targets = _batch_context(
        source_rate=8000,
        source_capacity=1040,
        source_inventory=1000,
        targets=(
            ("ORD-B", "BUF-B", -500, 1000, 1000),
            ("ORD-C", "BUF-C", -2000, 1000, 1000),
        ),
    )
    source_b = targets["ORD-B"]
    snapshot_value.machine_product_capacities = [
        item.model_copy(update={"actual_capacity": 7000.0})
        if item.machine_code == "M-01"
        and item.product_code == source_b.product_code
        else item
        for item in snapshot_value.machine_product_capacities
    ]
    candidates = _batch_candidates(
        source,
        targets,
        overflow_candidate("M-01", 8000, overflow_target("ORD-B")),
        _candidate_for_source(
            overflow_candidate("M-02", 5000, overflow_target("ORD-C")),
            source_b,
        ),
    )

    result = _select(
        candidates,
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    assert [item.source_order_code for item in result.selected_machines] == [
        source.order_code,
        source_b.order_code,
    ]
    assert result.selected_machines[0].target_net_rate_after == -6500
    assert result.selected_machines[1].source_net_rate_before == -6500
    assert result.risk_resolved is True


def test_batch_selection_retries_source_after_virtual_stockout_risk_changes():
    snapshot_value, warning, intervals, source, targets = _batch_context(
        source_rate=5000,
        source_capacity=1100,
        source_inventory=1000,
        targets=(
            ("ORD-B", "BUF-B", 6000, 100, 100),
            ("ORD-C", "BUF-C", -1000, 1000, 1000),
        ),
    )
    source_b = targets["ORD-B"]
    source_c = targets["ORD-C"]
    snapshot_value.machine_product_capacities = [
        item.model_copy(update={"actual_capacity": 5000.0})
        if item.machine_code == "M-01"
        and item.product_code == source_b.product_code
        else item.model_copy(update={"actual_capacity": 1000.0})
        if item.machine_code == "M-02"
        and item.product_code == source_c.product_code
        else item
        for item in snapshot_value.machine_product_capacities
    ]
    candidates = _batch_candidates(
        source,
        targets,
        _candidate_for_source(
            overflow_candidate("M-02", 10000, overflow_target("ORD-C")),
            source_b,
        ),
        overflow_candidate("M-01", 6000, overflow_target("ORD-B")),
    )

    result = _select(
        candidates,
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    assert [item.machine_code for item in result.selected_machines] == [
        "M-01",
        "M-02",
    ]
    assert result.selected_machines[1].source_order_code == source_b.order_code
    assert result.selected_machines[1].source_net_rate_before == -11000
    assert result.risk_resolved is True


def test_batch_selection_uses_next_source_when_previous_source_disappears():
    snapshot_value, warning, intervals, source, targets = _batch_context(
        source_rate=8000,
        source_capacity=1040,
        source_inventory=1000,
        targets=(
            ("ORD-B", "BUF-B", 3000, 1000, 1000),
            ("ORD-C", "BUF-C", -2000, 1000, 1000),
        ),
    )
    source_b = targets["ORD-B"]
    candidates = _batch_candidates(
        source,
        targets,
        overflow_candidate("M-01", 9000, overflow_target("ORD-B")),
        _candidate_for_source(
            overflow_candidate("M-02", 4000, overflow_target("ORD-C")),
            source_b,
        ),
    )

    result = _select(
        candidates,
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    assert [item.source_order_code for item in result.selected_machines] == [
        source.order_code,
        source_b.order_code,
    ]
    assert result.selected_machines[0].source_net_rate_after == 1000
    assert result.selected_machines[1].source_order_code == source_b.order_code


def test_batch_selection_tries_next_positive_source_when_largest_has_no_candidate():
    snapshot_value, warning, intervals, source, targets = _batch_context(
        source_rate=8000,
        source_capacity=1040,
        source_inventory=1000,
        targets=(
            ("ORD-B", "BUF-B", 5000, 1000, 1000),
            ("ORD-C", "BUF-C", -2000, 1000, 1000),
        ),
    )
    source_b = targets["ORD-B"]
    candidates = _batch_candidates(
        source,
        targets,
        _candidate_for_source(
            overflow_candidate("M-02", 6000, overflow_target("ORD-C")),
            source_b,
        ),
    )

    result = _select(
        candidates,
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    assert [item.source_order_code for item in result.selected_machines] == [
        source_b.order_code
    ]
    assert result.selected_machines[0].machine_code == "M-02"


def test_batch_selection_accumulates_two_partial_virtual_improvements():
    snapshot_value, warning, intervals, source, targets = _batch_context(
        source_rate=10000,
        source_inventory=1000,
        source_capacity=2250,
        targets=(("ORD-TARGET", "BUF-TARGET", -1000, 1000, 2250),),
    )
    candidates = _batch_candidates(
        source,
        targets,
        overflow_candidate(
            "M-01",
            2500,
            overflow_target(downstream_process_code="P02"),
        ),
        overflow_candidate("M-02", 2500, overflow_target(downstream_process_code="P02")),
    )

    result = _select(
        candidates,
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    assert [item.machine_code for item in result.selected_machines] == ["M-01", "M-02"]
    assert result.selected_machines[0].source_net_rate_after == -7500
    assert result.selected_machines[1].source_net_rate_before == -7500
    assert result.selected_machines[1].source_net_rate_after == -5000
    assert result.total_reduced_capacity == 5000
    assert result.remaining_growth_rate == 4200
    assert result.updated_overflow_minutes > 30
    assert result.risk_resolved is True


def test_batch_physical_no_improvement_rejection_does_not_pollute_virtual_state():
    snapshot_value, warning, intervals, source, targets = _batch_context(
        targets=(
            ("ORD-BAD", "BUF-BAD", -2000, 900, 1000),
            ("ORD-TARGET", "BUF-TARGET", -1000, 1000, 3900),
        )
    )
    candidates = _batch_candidates(
        source,
        targets,
        overflow_candidate(
            "M-01",
            1000,
            overflow_target(
                "ORD-BAD",
                buffer_code="BUF-BAD",
                downstream_process_code="P02",
            ),
        ),
        overflow_candidate(
            "M-02",
            10000,
            overflow_target(downstream_process_code="P02"),
        ),
    )
    snapshot_value.machine_product_capacities = [
        item.model_copy(update={"actual_capacity": 1000.0})
        if item.machine_code == "M-01" and item.product_code == "PROD-BAD"
        else item
        for item in snapshot_value.machine_product_capacities
    ]

    result = _select(
        candidates,
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    assert [item.machine_code for item in result.selected_machines] == ["M-02"]
    assert result.selected_machines[0].source_net_rate_before == -10000
    assert result.remaining_growth_rate == -2900
    assert result.rejected_machines[0].reason == "main_rate_not_improved"


def test_batch_selection_rejects_physical_main_rate_worsening():
    snapshot_value, warning, intervals, source, targets = _batch_context(
        source_rate=1000,
        source_inventory=1000,
        source_capacity=1010,
        targets=(("ORD-TARGET", "BUF-TARGET", -100, 900, 1000),),
    )
    candidates = _batch_candidates(
        source,
        targets,
        overflow_candidate("M-01", 500),
    )
    snapshot_value.machine_product_capacities = [
        item.model_copy(update={"actual_capacity": 600.0})
        if item.machine_code == "M-01" and item.product_code == "PROD-TARGET"
        else item
        for item in snapshot_value.machine_product_capacities
    ]

    result = _select(
        candidates,
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    assert result.selected_machines == []
    assert result.remaining_growth_rate == 900
    assert result.rejected_machines[0].reason == "main_rate_not_improved"


def test_batch_target_ordering_uses_lowest_rate_before_order_code():
    snapshot_value, warning, intervals, source, targets = _batch_context(
        source_rate=10000,
        source_inventory=1000,
        source_capacity=1250,
        targets=(
            ("ORD-B", "BUF-B", -5000, 1000, 1250),
            ("ORD-C", "BUF-C", -1000, 1000, 1250),
            ("ORD-D", "BUF-D", 500, 1000, 1250),
        ),
    )
    candidates = _batch_candidates(
        source,
        targets,
        overflow_candidate(
            "M-01",
            6000,
            overflow_target("ORD-B"),
            overflow_target("ORD-C"),
            overflow_target("ORD-D"),
        ),
    )

    result = _select(
        candidates,
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    assert [item.target_order_code for item in result.selected_machines] == ["ORD-B"]
    assert result.selected_machines[0].target_net_rate_before == 5000


def test_batch_target_ordering_is_recomputed_from_latest_virtual_rates():
    snapshot_value, warning, intervals, source, targets = _batch_context(
        source_rate=10000,
        source_inventory=1000,
        source_capacity=1040,
        targets=(
            ("ORD-B", "BUF-B", -5000, 1000, 1000),
            ("ORD-C", "BUF-C", -1000, 1000, 1000),
        ),
    )
    candidates = _batch_candidates(
        source,
        targets,
        overflow_candidate(
            "M-01",
            8000,
            overflow_target("ORD-B"),
            overflow_target("ORD-C"),
        ),
        overflow_candidate(
            "M-02",
            2500,
            overflow_target("ORD-B"),
            overflow_target("ORD-C"),
        ),
    )
    snapshot_value.machine_product_capacities = [
        item.model_copy(update={"actual_capacity": 6000.0})
        if item.machine_code == "M-01" and item.product_code == "PROD-B"
        else item.model_copy(update={"actual_capacity": 2000.0})
        if item.machine_code == "M-02"
        and item.product_code in {"PROD-B", "PROD-C"}
        else item
        for item in snapshot_value.machine_product_capacities
    ]

    result = _select(
        candidates,
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    assert [item.target_order_code for item in result.selected_machines] == [
        "ORD-B",
        "ORD-C",
    ]
    assert result.selected_machines[0].target_net_rate_after == -1000
    assert result.selected_machines[1].target_net_rate_before == 1000


def test_batch_selection_prefers_largest_safe_physical_improvement():
    snapshot_value, warning, intervals, source, targets = _batch_context(
        source_rate=10000,
        source_inventory=1000,
        source_capacity=2000,
        targets=(("ORD-TARGET", "BUF-TARGET", -1000, 1000, 2000),),
    )
    candidates = _batch_candidates(
        source,
        targets,
        overflow_candidate("M-01", 3000, utilization_rate=0.99),
        overflow_candidate("M-02", 6000, utilization_rate=0.5),
    )

    result = _select(
        candidates,
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    assert [item.machine_code for item in result.selected_machines] == ["M-02"]
    assert result.risk_resolved is True


def test_batch_selection_rejects_duplicate_machine_on_a_later_virtual_round():
    snapshot_value, warning, intervals, source, targets = _batch_context(
        source_rate=10000,
        source_inventory=1000,
        source_capacity=2250,
        targets=(("ORD-TARGET", "BUF-TARGET", -1000, 1000, 2250),),
    )
    candidates = _batch_candidates(
        source,
        targets,
        overflow_candidate("M-01", 2500),
        overflow_candidate(
            "M-01",
            2500,
        ),
        overflow_candidate("M-02", 2500),
    )

    result = _select(
        candidates,
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    assert [item.machine_code for item in result.selected_machines] == ["M-01", "M-02"]
    assert any(
        item.machine_code == "M-01"
        and item.reason == "duplicate_machine_selection"
        for item in result.rejected_machines
    )
    assert result.risk_resolved is True


def test_batch_source_stockout_protection_rejects_without_committing():
    snapshot_value, warning, intervals, source, targets = _batch_context(
        source_rate=1000,
        source_inventory=500,
        source_capacity=510,
        targets=(("ORD-TARGET", "BUF-TARGET", 0, 1000, 1100),),
    )
    candidates = _batch_candidates(
        source,
        targets,
        overflow_candidate("M-01", 2000),
    )

    result = _select(
        candidates,
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    assert result.selected_machines == []
    assert result.remaining_growth_rate == 1000
    assert result.rejected_machines[0].reason == "source_order_stockout_risk"
    assert result.rejected_machines[0].source_depletion_minutes_after == 30


def test_batch_partial_improvement_is_committed_while_main_remains_in_risk_window():
    snapshot_value, warning, intervals, source, targets = _batch_context(
        source_rate=1000,
        source_inventory=1000,
        source_capacity=1010,
        targets=(("ORD-TARGET", "BUF-TARGET", -100, 900, 1000),),
    )
    candidates = _batch_candidates(
        source,
        targets,
        overflow_candidate("M-01", 1000),
    )
    snapshot_value.machine_product_capacities = [
        item.model_copy(update={"actual_capacity": 900.0})
        for item in snapshot_value.machine_product_capacities
        if item.machine_code == "M-01" and item.product_code == "PROD-TARGET"
    ]

    result = _select(
        candidates,
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    assert [item.machine_code for item in result.selected_machines] == ["M-01"]
    assert result.remaining_growth_rate == 800
    assert result.updated_overflow_minutes == pytest.approx(8.25)
    assert result.risk_resolved is False
    assert result.failure_reason == "insufficient_reduced_capacity"


def test_batch_virtual_state_is_new_for_each_warning_evaluation():
    snapshot_value, warning, intervals, source, targets = _batch_context()
    candidates = _batch_candidates(
        source,
        targets,
        overflow_candidate("M-01", 10000),
    )

    first = _select(
        candidates,
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )
    second = _select(
        candidates,
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    assert [item.machine_code for item in first.selected_machines] == ["M-01"]
    assert [item.machine_code for item in second.selected_machines] == ["M-01"]


def test_batch_source_depletion_at_exact_lead_boundary_is_rejected():
    snapshot_value, warning, intervals, source, targets = _batch_context(
        source_rate=1000,
        source_inventory=500,
        source_capacity=510,
        targets=(("ORD-TARGET", "BUF-TARGET", 0, 1000, 1100),),
    )
    candidates = _batch_candidates(
        source,
        targets,
        overflow_candidate("M-01", 2000),
    )

    result = _select(
        candidates,
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    assert result.selected_machines == []
    assert result.rejected_machines[0].reason == "source_order_stockout_risk"
    assert result.rejected_machines[0].source_depletion_minutes_after == 30


def test_batch_source_depletion_beyond_lead_is_allowed_to_reach_other_safety_checks():
    snapshot_value, warning, intervals, source, targets = _batch_context(
        source_rate=1000,
        source_inventory=500,
        source_capacity=510,
        targets=(("ORD-TARGET", "BUF-TARGET", 0, 1000, 1100),),
    )
    candidates = _batch_candidates(
        source,
        targets,
        overflow_candidate("M-01", 1500),
    )

    result = _select(
        candidates,
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    assert [item.machine_code for item in result.selected_machines] == ["M-01"]
    assert result.selected_machines[0].source_net_rate_after == 500
    assert result.selected_machines[0].source_depletion_minutes_after == 60
    assert result.risk_resolved is True


def test_batch_partial_improvement_at_exact_overflow_lead_remains_unresolved():
    snapshot_value, warning, intervals, source, targets = _batch_context(
        source_rate=1000,
        source_inventory=1000,
        source_capacity=1010,
        targets=(("ORD-TARGET", "BUF-TARGET", -100, 450, 800),),
    )
    candidates = _batch_candidates(
        source,
        targets,
        overflow_candidate("M-01", 1200),
    )
    snapshot_value.machine_product_capacities = [
        item.model_copy(update={"actual_capacity": 1020.0})
        for item in snapshot_value.machine_product_capacities
        if item.machine_code == "M-01" and item.product_code == "PROD-TARGET"
    ]

    result = _select(
        candidates,
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    assert [item.machine_code for item in result.selected_machines] == ["M-01"]
    assert result.selected_machines[0].target_overflow_minutes_after == 30
    assert result.updated_overflow_minutes == 30
    assert result.risk_resolved is False
    assert result.failure_reason == "insufficient_reduced_capacity"


def test_batch_source_overflow_at_exact_lead_boundary_remains_unresolved():
    snapshot_value, warning, intervals, source, targets = _batch_context(
        source_rate=10000,
        source_inventory=10000,
        source_capacity=11000,
        targets=(("ORD-TARGET", "BUF-TARGET", 0, 1000, 1050),),
    )
    candidates = _batch_candidates(
        source,
        targets,
        overflow_candidate("M-01", 8000),
    )

    result = _select(
        candidates,
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    assert [item.machine_code for item in result.selected_machines] == ["M-01"]
    assert result.updated_overflow_minutes == 30
    assert result.risk_resolved is False
    assert result.failure_reason == "insufficient_reduced_capacity"


def test_batch_candidates_exhausted_builds_manual_decision():
    snapshot_value, warning, intervals, source, targets = _batch_context(
        source_rate=10000,
        source_inventory=1000,
        source_capacity=1100,
        targets=(("ORD-TARGET", "BUF-TARGET", -1000, 1000, 4900),),
    )
    candidates = _batch_candidates(
        source,
        targets,
        overflow_candidate("M-01", 1000),
    )
    selection = _select(
        candidates,
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    decision = CutlinePlanBuilder().build_overflow_decision(
        snapshot_value,
        warning,
        selection,
    )

    assert selection.risk_resolved is False
    assert selection.failure_reason == "insufficient_reduced_capacity"
    assert decision.plan is None
    assert decision.manual_intervention is not None


@pytest.mark.parametrize(
    ("source_inventory", "source_rate"),
    (
        (1100, 0),
        (1200, 100),
        (1200, -100),
    ),
)
def test_batch_at_or_over_capacity_builds_manual_intervention(
    source_inventory,
    source_rate,
):
    snapshot_value, warning, intervals, source, targets = _batch_context(
        source_rate=source_rate,
        source_inventory=source_inventory,
        source_capacity=1100,
        targets=(("ORD-TARGET", "BUF-TARGET", 0, 3900, 3900),),
    )
    selection = _select(
        _batch_candidates(source, targets),
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    decision = CutlinePlanBuilder().build_overflow_decision(
        snapshot_value,
        warning,
        selection,
    )

    assert selection.selected_machines == []
    assert selection.risk_resolved is False
    assert selection.failure_reason == "current_buffer_already_over_capacity"
    assert decision.plan is None
    assert decision.manual_intervention is not None
    assert (
        decision.manual_intervention.reason
        == "current_buffer_already_over_capacity"
    )


def test_batch_evaluator_rejects_ineligible_source_group():
    snapshot_value, warning, intervals, source, targets = _batch_context()
    unavailable_source = replace(source, auto_donate_eligible=False)
    batch = snapshot_value.main_buffer_batch
    snapshot_value.main_buffer_batch = replace(
        batch,
        groups=(unavailable_source, *batch.groups[1:]),
        groups_by_group_key={
            **batch.groups_by_group_key,
            source.group_key: unavailable_source,
        },
    )
    candidates = _batch_candidates(
        source,
        targets,
        overflow_candidate("M-01", 10000),
    )

    result = _select(
        candidates,
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    assert result.selected_machines == []
    assert result.risk_resolved is False
    assert result.rejected_machines[0].reason == "source_group_not_found"


def test_batch_evaluator_requires_finite_source_rate():
    snapshot_value, warning, intervals, source, targets = _batch_context()
    intervals[0] = intervals[0].model_copy(
        update={"inventory_change_rate": float("nan")}
    )
    candidates = _batch_candidates(
        source,
        targets,
        overflow_candidate("M-01", 10000),
    )
    _, module = _evaluator()

    with pytest.raises(
        module.MachineSelectionEvaluationError,
        match="source group rate.*finite",
    ):
        _select(
            candidates,
            snapshot_value=snapshot_value,
            warning=warning,
            intervals=intervals,
            overflows=[],
        )


def test_batch_warning_buffer_fallback_cannot_be_redirected_by_candidate_key():
    snapshot_value, warning, intervals, source, targets = _batch_context()
    target = targets["ORD-TARGET"]
    warning = warning.model_copy(update={"group_key": None})
    candidates = _batch_candidates(
        source,
        targets,
        overflow_candidate("M-01", 10000),
    ).model_copy(
        update={
            "source_group_key": target.group_key,
            "source_order_code": target.order_code,
        }
    )
    _, module = _evaluator()

    with pytest.raises(
        module.MachineSelectionEvaluationError,
        match="candidate source group does not match warning",
    ):
        _select(
            candidates,
            snapshot_value=snapshot_value,
            warning=warning,
            intervals=intervals,
            overflows=[],
        )


def test_batch_target_key_must_match_option_public_identity():
    snapshot_value, warning, intervals, source, targets = _batch_context(
        targets=(
            ("ORD-TARGET", "BUF-TARGET", -1000, 1000, 1950),
            ("ORD-SECOND", "BUF-SECOND", -1000, 1000, 1950),
        )
    )
    candidate = overflow_candidate("M-01", 10000)
    mismatched_option = candidate.target_options[0].model_copy(
        update={"target_group_key": targets["ORD-SECOND"].group_key}
    )
    candidate = candidate.model_copy(
        update={
            "source_group_key": source.group_key,
            "target_options": [mismatched_option],
        }
    )
    candidates = overflow_candidates(candidate).model_copy(
        update={"source_group_key": source.group_key}
    )

    result = _select(
        candidates,
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    assert result.selected_machines == []
    assert result.rejected_machines[0].reason == "target_group_not_found"
