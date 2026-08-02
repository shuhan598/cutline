from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.cutline_confirmation.pending_cutline_plan_factory import (
    PendingCutlinePlanCreationError,
    PendingCutlinePlanFactory,
)
from app.schemas.pending_cutline_schema import PendingCutlinePlanStatus
from app.schemas.request_schema import AlgorithmSnapshot
from app.schemas.result_schema import (
    AlgorithmCutlineDecisionResult,
    AlgorithmManualInterventionResult,
    AlgorithmOverflowCutlinePlan,
    AlgorithmSelectedMachineEvaluation,
    AlgorithmStockoutCutlinePlan,
)
from tests.core.cutline_confirmation.helpers import (
    ALTERNATE_BUFFER,
    ALTERNATE_ORDER,
    ALTERNATE_PRODUCT,
    CREATED_AT,
    CUT_PROCESS,
    DOWNSTREAM_PROCESS,
    MONITORED_ORDER,
    MONITORED_PRODUCT,
    SOURCE_BUFFER,
    SOURCE_ORDER,
    SOURCE_PRODUCT,
    WARNING_BUFFER,
    WORKSHOP,
    make_agv_binding,
    make_snapshot,
)


WARNING_TIME = CREATED_AT - timedelta(minutes=5)


def _selected_machine(
    machine_code: str,
    source_order_code: str,
    target_order_code: str,
    source_buffer_code: str,
    target_buffer_code: str,
    *,
    warning_type: str,
) -> AlgorithmSelectedMachineEvaluation:
    capacity = (
        {"contribution_capacity": 12.0}
        if warning_type == "stockout"
        else {"reduced_capacity": 12.0}
    )
    return AlgorithmSelectedMachineEvaluation(
        machine_code=machine_code,
        source_order_code=source_order_code,
        target_order_code=target_order_code,
        source_buffer_code=source_buffer_code,
        target_buffer_code=target_buffer_code,
        process_code=CUT_PROCESS,
        workshop_code=WORKSHOP,
        wafer_size="210",
        source_wafer_spec="M10-P",
        target_wafer_spec="M10-P",
        utilization_rate=0.8,
        idle_rate=0.2,
        source_net_rate_before=-5.0,
        source_net_rate_after=-2.0,
        target_net_rate_before=4.0,
        target_net_rate_after=1.0,
        **capacity,
    )


def _stockout_decision() -> AlgorithmCutlineDecisionResult:
    plan = AlgorithmStockoutCutlinePlan(
        plan_id=(
            f"stockout:{WARNING_TIME.isoformat()}:"
            f"{WARNING_BUFFER}:{MONITORED_ORDER}"
        ),
        calculation_time=WARNING_TIME,
        workshop_code=WORKSHOP,
        buffer_code=WARNING_BUFFER,
        order_code=MONITORED_ORDER,
        wafer_size="210",
        wafer_spec="M10-P",
        upstream_process_code=CUT_PROCESS,
        downstream_process_code=DOWNSTREAM_PROCESS,
        initial_capacity_gap=10.0,
        total_contribution_capacity=12.0,
        remaining_capacity_gap=0.0,
        selected_machines=[
            _selected_machine(
                "M1",
                SOURCE_ORDER,
                MONITORED_ORDER,
                SOURCE_BUFFER,
                WARNING_BUFFER,
                warning_type="stockout",
            )
        ],
    )
    return AlgorithmCutlineDecisionResult(plan=plan, manual_intervention=None)


def _overflow_decision() -> AlgorithmCutlineDecisionResult:
    plan = AlgorithmOverflowCutlinePlan(
        plan_id=f"overflow:{WARNING_TIME.isoformat()}:{WARNING_BUFFER}",
        calculation_time=WARNING_TIME,
        workshop_code=WORKSHOP,
        buffer_code=WARNING_BUFFER,
        source_order_code=MONITORED_ORDER,
        source_wafer_size="210",
        source_wafer_spec="M10-P",
        upstream_process_code=CUT_PROCESS,
        downstream_process_code=DOWNSTREAM_PROCESS,
        initial_growth_rate=10.0,
        total_reduced_capacity=12.0,
        remaining_growth_rate=-2.0,
        selected_machines=[
            _selected_machine(
                "M1",
                MONITORED_ORDER,
                ALTERNATE_ORDER,
                WARNING_BUFFER,
                ALTERNATE_BUFFER,
                warning_type="overflow",
            )
        ],
    )
    return AlgorithmCutlineDecisionResult(plan=plan, manual_intervention=None)


def _snapshot(
    *,
    overflow: bool = False,
    stop_m3: bool = True,
) -> AlgorithmSnapshot:
    current_orders = {
        "M1": MONITORED_ORDER if overflow else SOURCE_ORDER,
        "M2": MONITORED_ORDER,
        "M3": SOURCE_ORDER,
        "M-W2": MONITORED_ORDER,
        "M-POTHER": MONITORED_ORDER,
    }
    snapshot = make_snapshot(
        pending_plans=[],
        current_time=CREATED_AT,
        current_orders=current_orders,
        statuses={"M3": "stopped"} if stop_m3 else {},
    )
    bindings = [
        make_agv_binding(
            machine_code,
            order_code,
            CREATED_AT - timedelta(minutes=1),
            previous_product_name=None,
        )
        for machine_code, order_code in current_orders.items()
        if machine_code in {"M1", "M2", "M3"}
    ]
    return snapshot.model_copy(update={"agv_relations": bindings})


def test_create_stockout_pending_uses_snapshot_time_and_full_scope_baseline(
) -> None:
    pending = PendingCutlinePlanFactory().create(
        _snapshot(),
        _stockout_decision(),
    )

    assert pending is not None
    assert pending.plan_id == _stockout_decision().plan.plan_id
    assert pending.warning_id == (
        f"stockout:{WARNING_TIME.isoformat()}:"
        f"{WARNING_BUFFER}:{MONITORED_ORDER}"
    )
    assert pending.warning_time == WARNING_TIME
    assert pending.created_at == CREATED_AT
    assert pending.expire_at == CREATED_AT + timedelta(minutes=30)
    assert pending.status is PendingCutlinePlanStatus.PENDING
    assert pending.process_code == CUT_PROCESS
    assert pending.monitored_order_code == MONITORED_ORDER
    assert pending.before_machine_codes == ["M2"]
    assert pending.before_machine_count == 1
    assert pending.expected_machine_count == 2
    assert pending.expected_delta_direction == "increase"
    assert pending.candidate_machine_codes == ["M1"]
    assert pending.confirmed_machine_codes == []

    baseline_by_machine = {
        item.machine_code: item for item in pending.baseline_machine_bindings
    }
    assert set(baseline_by_machine) == {"M1", "M2", "M3"}
    assert baseline_by_machine["M3"].machine_status == "stopped"
    assert baseline_by_machine["M1"].order_code == SOURCE_ORDER
    assert baseline_by_machine["M1"].observed_at == (
        CREATED_AT - timedelta(minutes=1)
    )

    candidate = pending.candidate_machines[0]
    assert candidate.machine_code == "M1"
    assert candidate.baseline_order_code == SOURCE_ORDER
    assert candidate.baseline_product_code == SOURCE_PRODUCT
    assert candidate.expected_target_order_code == MONITORED_ORDER
    assert candidate.expected_target_product_code == MONITORED_PRODUCT
    assert candidate.source_buffer_code == SOURCE_BUFFER
    assert candidate.target_buffer_code == WARNING_BUFFER
    assert candidate.target_upstream_process_code == CUT_PROCESS
    assert candidate.target_downstream_process_code == DOWNSTREAM_PROCESS
    assert pending.source_order_code == SOURCE_ORDER
    assert pending.target_order_code == MONITORED_ORDER
    assert pending.source_product_code == SOURCE_PRODUCT
    assert pending.target_product_code == MONITORED_PRODUCT


def test_create_overflow_pending_decreases_the_running_monitored_set() -> None:
    pending = PendingCutlinePlanFactory().create(
        _snapshot(overflow=True),
        _overflow_decision(),
    )

    assert pending is not None
    assert pending.warning_id == (
        f"overflow:{WARNING_TIME.isoformat()}:{WARNING_BUFFER}"
    )
    assert pending.monitored_order_code == MONITORED_ORDER
    assert pending.before_machine_codes == ["M1", "M2"]
    assert pending.before_machine_count == 2
    assert pending.expected_machine_count == 1
    assert pending.expected_delta_direction == "decrease"
    assert pending.candidate_machine_codes == ["M1"]
    candidate = pending.candidate_machines[0]
    assert candidate.baseline_order_code == MONITORED_ORDER
    assert candidate.expected_target_order_code == ALTERNATE_ORDER
    assert candidate.target_buffer_code == ALTERNATE_BUFFER
    assert pending.source_product_code == MONITORED_PRODUCT
    assert pending.target_product_code == ALTERNATE_PRODUCT


def test_create_returns_none_for_manual_intervention() -> None:
    manual = AlgorithmManualInterventionResult(
        warning_type="stockout",
        warning_time=WARNING_TIME,
        workshop_code=WORKSHOP,
        buffer_code=WARNING_BUFFER,
        order_code=MONITORED_ORDER,
        wafer_size="210",
        wafer_spec="M10-P",
        upstream_process_code=CUT_PROCESS,
        downstream_process_code=DOWNSTREAM_PROCESS,
        reason="operator_required",
        initial_risk_value=10.0,
        remaining_risk_value=5.0,
        evaluated_candidate_count=0,
        passed_candidate_count=0,
        rejected_candidate_count=0,
    )
    decision = AlgorithmCutlineDecisionResult(
        plan=None,
        manual_intervention=manual,
    )

    assert PendingCutlinePlanFactory().create(_snapshot(), decision) is None


@pytest.mark.parametrize(
    ("missing_kind", "match"),
    [
        ("agv", r"M3.*AGV.*binding"),
        ("runtime", r"M3.*runtime"),
    ],
)
def test_create_rejects_missing_full_scope_machine_context(
    missing_kind: str,
    match: str,
) -> None:
    snapshot = _snapshot()
    if missing_kind == "agv":
        snapshot = snapshot.model_copy(
            update={
                "agv_relations": [
                    item
                    for item in snapshot.agv_relations
                    if item.machine_code != "M3"
                ]
            }
        )
    else:
        snapshot = snapshot.model_copy(
            update={
                "machine_runtimes": [
                    item
                    for item in snapshot.machine_runtimes
                    if item.machine_code != "M3"
                ]
            }
        )

    with pytest.raises(PendingCutlinePlanCreationError, match=match):
        PendingCutlinePlanFactory().create(snapshot, _stockout_decision())


def test_create_rejects_ambiguous_target_buffer_relation() -> None:
    snapshot = _snapshot()
    duplicate = next(
        item
        for item in snapshot.buffer_process_relations
        if item.buffer_code == WARNING_BUFFER
    )
    snapshot = snapshot.model_copy(
        update={
            "buffer_process_relations": [
                *snapshot.buffer_process_relations,
                duplicate.model_copy(),
            ]
        }
    )

    with pytest.raises(
        PendingCutlinePlanCreationError,
        match=rf"{WARNING_BUFFER}.*multiple.*relation",
    ):
        PendingCutlinePlanFactory().create(snapshot, _stockout_decision())


def test_create_rejects_candidate_that_disagrees_with_agv_baseline() -> None:
    decision = _stockout_decision()
    selected = decision.plan.selected_machines[0].model_copy(
        update={"source_order_code": ALTERNATE_ORDER}
    )
    decision = AlgorithmCutlineDecisionResult(
        plan=decision.plan.model_copy(update={"selected_machines": [selected]}),
        manual_intervention=None,
    )

    with pytest.raises(
        PendingCutlinePlanCreationError,
        match=r"M1.*source_order_code.*O-ALT.*AGV baseline.*O-SOURCE",
    ):
        PendingCutlinePlanFactory().create(_snapshot(), decision)


def test_stockout_rejects_candidate_already_in_monitored_before_set() -> None:
    snapshot = _snapshot(overflow=True)
    decision = _stockout_decision()
    assert decision.plan is not None
    selected = decision.plan.selected_machines[0].model_copy(
        update={
            "source_order_code": MONITORED_ORDER,
            "source_buffer_code": WARNING_BUFFER,
        }
    )
    decision = AlgorithmCutlineDecisionResult(
        plan=decision.plan.model_copy(update={"selected_machines": [selected]}),
        manual_intervention=None,
    )

    with pytest.raises(PendingCutlinePlanCreationError) as exc_info:
        PendingCutlinePlanFactory().create(snapshot, decision)

    message = str(exc_info.value)
    assert decision.plan.plan_id in message
    assert "M1" in message
    assert "stockout direction" in message


def test_stockout_rejects_candidate_targeting_a_nonmonitored_order() -> None:
    decision = _stockout_decision()
    assert decision.plan is not None
    selected = decision.plan.selected_machines[0].model_copy(
        update={
            "target_order_code": ALTERNATE_ORDER,
            "target_buffer_code": ALTERNATE_BUFFER,
        }
    )
    decision = AlgorithmCutlineDecisionResult(
        plan=decision.plan.model_copy(update={"selected_machines": [selected]}),
        manual_intervention=None,
    )

    with pytest.raises(PendingCutlinePlanCreationError) as exc_info:
        PendingCutlinePlanFactory().create(_snapshot(), decision)

    message = str(exc_info.value)
    assert decision.plan.plan_id in message
    assert "M1" in message
    assert "stockout direction" in message


def test_overflow_rejects_stopped_candidate_outside_before_set() -> None:
    snapshot = _snapshot(overflow=True)
    snapshot = snapshot.model_copy(
        update={
            "machine_runtimes": [
                item.model_copy(update={"status": "stopped"})
                if item.machine_code == "M1"
                else item
                for item in snapshot.machine_runtimes
            ]
        }
    )
    decision = _overflow_decision()

    with pytest.raises(PendingCutlinePlanCreationError) as exc_info:
        PendingCutlinePlanFactory().create(snapshot, decision)

    assert decision.plan is not None
    message = str(exc_info.value)
    assert decision.plan.plan_id in message
    assert "M1" in message
    assert "overflow direction" in message


def test_overflow_rejects_candidate_with_nonmonitored_source_baseline() -> None:
    decision = _overflow_decision()
    assert decision.plan is not None
    selected = decision.plan.selected_machines[0].model_copy(
        update={
            "source_order_code": SOURCE_ORDER,
            "source_buffer_code": SOURCE_BUFFER,
        }
    )
    decision = AlgorithmCutlineDecisionResult(
        plan=decision.plan.model_copy(update={"selected_machines": [selected]}),
        manual_intervention=None,
    )

    with pytest.raises(PendingCutlinePlanCreationError) as exc_info:
        PendingCutlinePlanFactory().create(_snapshot(), decision)

    message = str(exc_info.value)
    assert decision.plan.plan_id in message
    assert "M1" in message
    assert "overflow direction" in message


def test_overflow_rejects_candidate_targeting_the_monitored_order() -> None:
    decision = _overflow_decision()
    assert decision.plan is not None
    selected = decision.plan.selected_machines[0].model_copy(
        update={
            "target_order_code": MONITORED_ORDER,
            "target_buffer_code": WARNING_BUFFER,
        }
    )
    decision = AlgorithmCutlineDecisionResult(
        plan=decision.plan.model_copy(update={"selected_machines": [selected]}),
        manual_intervention=None,
    )

    with pytest.raises(PendingCutlinePlanCreationError) as exc_info:
        PendingCutlinePlanFactory().create(_snapshot(overflow=True), decision)

    message = str(exc_info.value)
    assert decision.plan.plan_id in message
    assert "M1" in message
    assert "overflow direction" in message
