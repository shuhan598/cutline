import importlib

import pytest

from tests.core.cutline_plan.helpers import (
    algorithm_snapshot,
    default_stockout_intervals,
    interval,
    overflow_state,
    stockout_candidate,
    stockout_candidates,
    stockout_warning,
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
    return evaluator.select_stockout_machines(
        snapshot=snapshot_value or algorithm_snapshot(),
        warning=warning or stockout_warning(),
        candidate_result=candidates,
        interval_results=intervals or default_stockout_intervals(),
        overflow_results=overflows
        or [overflow_state("BUF-SOURCE"), overflow_state("BUF-TARGET")],
    )


def test_first_passing_machine_closes_gap_and_stops_iteration():
    result = _select(
        stockout_candidates(
            stockout_candidate("M-01", 10000),
            stockout_candidate("M-02", 5000),
        )
    )

    assert [item.machine_code for item in result.selected_machines] == ["M-01"]
    assert result.total_contribution_capacity == 10000
    assert result.remaining_capacity_gap == 0
    assert result.risk_resolved is True
    assert result.rejected_machines == []


def test_passing_machines_accumulate_in_input_order_until_gap_is_closed():
    result = _select(
        stockout_candidates(
            stockout_candidate("M-01", 4000, idle_rate=0.9),
            stockout_candidate("M-02", 3500, idle_rate=0.8),
            stockout_candidate("M-03", 3000, idle_rate=0.7),
        )
    )

    assert [item.machine_code for item in result.selected_machines] == [
        "M-01",
        "M-02",
        "M-03",
    ]
    assert result.total_contribution_capacity == 10500
    assert result.remaining_capacity_gap == 0
    assert result.risk_resolved is True


def test_failed_first_machine_is_recorded_and_second_machine_is_tried():
    intervals = default_stockout_intervals()
    intervals.insert(
        0,
        interval(
            buffer_code="BUF-BAD",
            order_code="ORD-BAD",
            downstream_process_code="P08",
            current_quantity=0,
            net_consumption_rate=0,
        ),
    )
    result = _select(
        stockout_candidates(
            stockout_candidate("M-BAD", 10000, source_order_code="ORD-BAD"),
            stockout_candidate("M-OK", 10000),
        ),
        intervals=intervals,
        overflows=[
            overflow_state("BUF-BAD"),
            overflow_state("BUF-SOURCE"),
            overflow_state("BUF-TARGET"),
        ],
    )

    assert [item.machine_code for item in result.selected_machines] == ["M-OK"]
    assert result.rejected_machines[0].machine_code == "M-BAD"
    assert result.rejected_machines[0].reason == "source_order_stockout_risk"


def test_all_safe_contributions_can_still_be_insufficient():
    result = _select(
        stockout_candidates(
            stockout_candidate("M-01", 2000),
            stockout_candidate("M-02", 3000),
        )
    )

    assert result.risk_resolved is False
    assert result.total_contribution_capacity == 5000
    assert result.remaining_capacity_gap == 5000
    assert result.failure_reason == "insufficient_contribution_capacity"


@pytest.mark.parametrize(
    ("source_net_rate", "quantity", "capacity", "expected_selected"),
    [
        (-10000, 100, 5000, True),
        (0, 1000, 1000, True),
        (0, 500, 1000, False),
        (0, 400, 1000, False),
    ],
)
def test_source_stockout_check_uses_exact_lead_time_boundary(
    source_net_rate,
    quantity,
    capacity,
    expected_selected,
):
    result = _select(
        stockout_candidates(stockout_candidate("M-01", capacity), capacity_gap=capacity),
        intervals=default_stockout_intervals(
            source_net_rate=source_net_rate,
            source_quantity=quantity,
        ),
    )

    assert bool(result.selected_machines) is expected_selected
    if not expected_selected:
        assert result.rejected_machines[0].reason == "source_order_stockout_risk"


@pytest.mark.parametrize("remaining_capacity", [499, 500])
def test_target_buffer_overflow_at_or_inside_lead_time_is_rejected(
    remaining_capacity,
):
    result = _select(
        stockout_candidates(stockout_candidate("M-01", 1000), capacity_gap=1000),
        overflows=[
            overflow_state("BUF-SOURCE"),
            overflow_state(
                "BUF-TARGET",
                total_inventory=1000 - remaining_capacity,
                max_capacity=1000,
            ),
        ],
    )

    assert result.selected_machines == []
    assert result.rejected_machines[0].reason == "target_buffer_overflow_risk"


def test_source_risk_uses_stockout_config_not_warning_or_overflow_lead():
    result = _select(
        stockout_candidates(
            stockout_candidate("M-01", 1000),
            capacity_gap=1000,
        ),
        warning=stockout_warning(stockout_warning_lead_minutes=5),
        intervals=default_stockout_intervals(
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


def test_target_risk_uses_overflow_config_not_stockout_warning_lead():
    result = _select(
        stockout_candidates(
            stockout_candidate("M-01", 1000),
            capacity_gap=1000,
        ),
        warning=stockout_warning(stockout_warning_lead_minutes=5),
        overflows=[
            overflow_state("BUF-SOURCE"),
            overflow_state(
                "BUF-TARGET",
                total_inventory=500,
                max_capacity=1000,
            ),
        ],
        snapshot_value=algorithm_snapshot(
            stockout_warning_lead_minutes=5,
            overflow_warning_lead_minutes=30,
        ),
    )

    assert result.selected_machines == []
    assert result.rejected_machines[0].reason == "target_buffer_overflow_risk"


def test_same_source_and_target_buffer_keeps_buffer_growth_unchanged():
    result = _select(
        stockout_candidates(stockout_candidate("M-01", 1000), capacity_gap=1000),
        intervals=default_stockout_intervals(
            source_net_rate=-2000,
            source_buffer_code="BUF-TARGET",
        ),
        overflows=[
            overflow_state(
                "BUF-TARGET",
                total_inventory=0,
                max_capacity=1000,
                buffer_growth_rate=10,
            )
        ],
    )

    assert [item.machine_code for item in result.selected_machines] == ["M-01"]
    assert result.selected_machines[0].target_overflow_minutes_after == 6000


def test_second_machine_uses_virtual_source_net_rate_after_first_selection():
    result = _select(
        stockout_candidates(
            stockout_candidate("M-01", 6000),
            stockout_candidate("M-02", 6000),
            capacity_gap=12000,
        ),
        intervals=default_stockout_intervals(
            source_net_rate=-10000,
            source_quantity=100,
        ),
    )

    assert [item.machine_code for item in result.selected_machines] == ["M-01"]
    assert result.rejected_machines[0].machine_code == "M-02"
    assert result.rejected_machines[0].source_net_rate_before == -4000


def test_zero_contribution_is_rejected_during_selection():
    result = _select(
        stockout_candidates(stockout_candidate("M-01", 0))
    )

    assert result.selected_machines == []
    assert result.rejected_machines[0].reason == "no_effective_contribution"


def test_candidate_input_order_is_preserved_without_resorting():
    result = _select(
        stockout_candidates(
            stockout_candidate("M-02", 4000, idle_rate=0.1),
            stockout_candidate("M-01", 6000, idle_rate=0.9),
        )
    )

    assert [item.machine_code for item in result.selected_machines] == [
        "M-02",
        "M-01",
    ]


def test_same_machine_code_cannot_be_selected_twice():
    result = _select(
        stockout_candidates(
            stockout_candidate("M-01", 4000),
            stockout_candidate("M-01", 4000),
            stockout_candidate("M-02", 6000),
        )
    )

    assert [item.machine_code for item in result.selected_machines] == [
        "M-01",
        "M-02",
    ]
    assert any(
        item.reason == "duplicate_machine_selection"
        for item in result.rejected_machines
    )


def test_missing_source_interval_rejects_only_that_machine():
    result = _select(
        stockout_candidates(
            stockout_candidate("M-MISSING", 10000, source_order_code="ORD-MISSING"),
            stockout_candidate("M-OK", 10000),
        )
    )

    assert [item.machine_code for item in result.selected_machines] == ["M-OK"]
    assert result.rejected_machines[0].reason == "source_interval_not_found"


def test_missing_stockout_target_interval_is_a_task_error():
    _, module = _evaluator()
    with pytest.raises(module.MachineSelectionEvaluationError, match="target interval"):
        _select(
            stockout_candidates(stockout_candidate("M-01", 10000)),
            intervals=default_stockout_intervals()[:1],
        )


def test_duplicate_interval_key_is_rejected_instead_of_overwritten():
    _, module = _evaluator()
    intervals = default_stockout_intervals()
    intervals.append(intervals[0].model_copy(deep=True))

    with pytest.raises(module.MachineSelectionEvaluationError, match="duplicate interval"):
        _select(
            stockout_candidates(stockout_candidate("M-01", 10000)),
            intervals=intervals,
        )


def test_stockout_selection_does_not_mutate_inputs():
    warning = stockout_warning()
    candidates = stockout_candidates(stockout_candidate("M-01", 10000))
    intervals = default_stockout_intervals()
    overflows = [overflow_state("BUF-SOURCE"), overflow_state("BUF-TARGET")]
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
