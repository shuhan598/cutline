import importlib

import pytest

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
