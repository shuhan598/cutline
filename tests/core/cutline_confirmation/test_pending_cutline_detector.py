from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from app.core.cutline_confirmation.pending_cutline_detector import (
    PendingCutlineDetectionError,
    PendingCutlineDetector,
)
from app.core.buffer_aggregation.models import (
    GroupKey,
    MainBufferAggregationBatch,
    MainBufferGroup,
    PhysicalBufferKey,
)

from .helpers import (
    ALTERNATE_BUFFER,
    ALTERNATE_ORDER,
    ALTERNATE_PRODUCT_NAME,
    CREATED_AT,
    CUT_PROCESS,
    DOWNSTREAM_PROCESS,
    EXPIRE_AT,
    INCOMPATIBLE_ORDER,
    INCOMPATIBLE_PRODUCT_NAME,
    MONITORED_ORDER,
    MONITORED_PRODUCT_NAME,
    NOW,
    OTHER_PROCESS,
    SOURCE_BUFFER,
    SOURCE_ORDER,
    SOURCE_PRODUCT_NAME,
    WARNING_BUFFER,
    WORKSHOP,
    make_active_event,
    make_agv_binding,
    make_interval_result,
    make_overflow_plan,
    make_snapshot,
    make_stockout_plan,
)


def _pending_batch(*, map_warning_layer: bool) -> MainBufferAggregationBatch:
    physical_key = PhysicalBufferKey(
        WORKSHOP,
        (CUT_PROCESS, DOWNSTREAM_PROCESS),
    )
    groups = []
    for main_id, order_code, product_code, representative, codes in (
        (
            "MAIN-WARNING",
            MONITORED_ORDER,
            "P-MON",
            "B-WARN-NEW",
            (WARNING_BUFFER, "B-WARN-NEW"),
        ),
        (
            "MAIN-SOURCE",
            SOURCE_ORDER,
            "P-SOURCE",
            SOURCE_BUFFER,
            (SOURCE_BUFFER,),
        ),
    ):
        key = GroupKey(physical_key, main_id, order_code)
        groups.append(
            MainBufferGroup(
                group_key=key,
                main_id=main_id,
                workshop_code=WORKSHOP,
                ordered_service_process_codes=(
                    CUT_PROCESS,
                    DOWNSTREAM_PROCESS,
                ),
                physical_buffer_key=physical_key,
                order_code=order_code,
                product_code=product_code,
                buffer_codes=codes,
                total_inventory=100,
                total_capacity=1000,
                remaining_capacity=900,
                representative_buffer_code=representative,
                stockout_eligible=True,
                overflow_eligible=True,
                stockout_warning_eligible=True,
                overflow_warning_eligible=True,
                auto_receive_eligible=True,
                auto_donate_eligible=True,
            )
        )
    groups_by_key = {group.group_key: group for group in groups}
    key_by_buffer = {
        code: group.group_key
        for group in groups
        for code in group.buffer_codes
        if map_warning_layer or code != WARNING_BUFFER
    }
    return MainBufferAggregationBatch(
        groups=tuple(groups),
        groups_by_group_key=groups_by_key,
        group_keys_by_main_id={
            group.main_id: (group.group_key,) for group in groups
        },
        group_key_by_buffer_code=key_by_buffer,
        group_key_by_representative_buffer_code={
            group.representative_buffer_code: group.group_key
            for group in groups
            if group.representative_buffer_code is not None
        },
        group_keys_by_physical_buffer_key={
            physical_key: tuple(group.group_key for group in groups)
        },
    )


def test_unchanged_binding_keeps_plan_pending_without_transition() -> None:
    plan = make_stockout_plan()
    unchanged = make_agv_binding(
        "M1",
        SOURCE_ORDER,
        NOW,
        previous_product_name=SOURCE_PRODUCT_NAME,
    )

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[plan],
            history=[unchanged],
        ),
        interval_results=[],
    )

    assert result.transitions == []
    assert len(result.plan_evaluations) == 1
    evaluation = result.plan_evaluations[0]
    assert evaluation.plan_id == plan.plan_id
    assert evaluation.status == "PENDING"
    assert evaluation.before_machine_count == 1
    assert evaluation.before_machine_codes == ["M2"]
    assert evaluation.current_machine_count == 1
    assert evaluation.current_machine_codes == ["M2"]
    assert evaluation.expected_machine_count == 2
    assert evaluation.expected_delta_direction == "increase"
    assert evaluation.confirmed_machine_codes == []
    assert evaluation.new_confirmed_machine_codes == []


def test_recommended_stockout_binding_creates_complete_typed_transition() -> None:
    plan = make_stockout_plan()
    binding_time = CREATED_AT + timedelta(minutes=3)
    changed = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        binding_time,
        previous_product_name=SOURCE_PRODUCT_NAME,
    )

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[plan],
            history=[changed],
            current_orders={"M1": MONITORED_ORDER, "M2": MONITORED_ORDER},
        ),
        interval_results=[],
    )

    assert len(result.transitions) == 1
    transition = result.transitions[0]
    assert transition.plan_id == plan.plan_id
    assert transition.warning_id == plan.warning_id
    assert transition.warning_type == "stockout"
    assert transition.machine_code == "M1"
    assert transition.source_order_code == SOURCE_ORDER
    assert transition.target_order_code == MONITORED_ORDER
    assert transition.workshop_code == WORKSHOP
    assert transition.process_code == CUT_PROCESS
    assert transition.source_buffer_code == SOURCE_BUFFER
    assert transition.target_buffer_code == WARNING_BUFFER
    assert transition.target_upstream_process_code == CUT_PROCESS
    assert transition.target_downstream_process_code == DOWNSTREAM_PROCESS
    assert transition.source_wafer_size == "210"
    assert transition.source_wafer_spec == "M10-P"
    assert transition.target_wafer_size == "210"
    assert transition.target_wafer_spec == "M10-P"
    assert transition.cutline_start_time == binding_time
    assert transition.is_recommended_candidate is True

    evaluation = result.plan_evaluations[0]
    assert evaluation.status == "CONFIRMED"
    assert evaluation.confirmed_machine_codes == ["M1"]
    assert evaluation.new_confirmed_machine_codes == ["M1"]


def test_recommended_confirmation_accepts_mapped_old_representative_layer() -> None:
    plan = make_stockout_plan()
    changed = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        CREATED_AT + timedelta(minutes=3),
        previous_product_name=SOURCE_PRODUCT_NAME,
    )
    current_snapshot = make_snapshot(
        pending_plans=[plan],
        history=[changed],
        current_orders={"M1": MONITORED_ORDER, "M2": MONITORED_ORDER},
    ).model_copy(
        update={"main_buffer_batch": _pending_batch(map_warning_layer=True)}
    )

    result = PendingCutlineDetector().detect(
        snapshot=current_snapshot,
        interval_results=[],
    )

    assert result.transitions[0].target_buffer_code == WARNING_BUFFER


def test_recommended_confirmation_blocks_unmapped_persisted_buffer_code() -> None:
    plan = make_stockout_plan()
    changed = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        CREATED_AT + timedelta(minutes=3),
        previous_product_name=SOURCE_PRODUCT_NAME,
    )
    current_snapshot = make_snapshot(
        pending_plans=[plan],
        history=[changed],
        current_orders={"M1": MONITORED_ORDER, "M2": MONITORED_ORDER},
    ).model_copy(
        update={"main_buffer_batch": _pending_batch(map_warning_layer=False)}
    )

    with pytest.raises(PendingCutlineDetectionError) as exc_info:
        PendingCutlineDetector().detect(
            snapshot=current_snapshot,
            interval_results=[],
        )

    assert plan.plan_id in str(exc_info.value)
    assert WARNING_BUFFER in str(exc_info.value)


def test_recommended_overflow_binding_uses_target_interval() -> None:
    plan = make_overflow_plan()
    binding_time = CREATED_AT + timedelta(minutes=4)
    changed = make_agv_binding(
        "M1",
        ALTERNATE_ORDER,
        binding_time,
        previous_product_name=None,
    )

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[plan],
            history=[changed],
            current_orders={"M1": ALTERNATE_ORDER, "M2": MONITORED_ORDER},
        ),
        interval_results=[
            make_interval_result(ALTERNATE_ORDER, ALTERNATE_BUFFER)
        ],
    )

    transition = result.transitions[0]
    assert transition.warning_type == "overflow"
    assert transition.source_order_code == MONITORED_ORDER
    assert transition.target_order_code == ALTERNATE_ORDER
    assert transition.source_buffer_code == WARNING_BUFFER
    assert transition.target_buffer_code == ALTERNATE_BUFFER
    assert transition.target_upstream_process_code == CUT_PROCESS
    assert transition.target_downstream_process_code == DOWNSTREAM_PROCESS
    assert transition.cutline_start_time == binding_time
    assert transition.is_recommended_candidate is True
    assert result.plan_evaluations[0].status == "CONFIRMED"


def test_recommended_machine_overflow_can_confirm_other_legal_target() -> None:
    plan = make_overflow_plan()
    changed = make_agv_binding(
        "M1",
        INCOMPATIBLE_ORDER,
        NOW,
        previous_product_name=MONITORED_PRODUCT_NAME,
    )

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[plan],
            history=[changed],
            current_orders={"M1": INCOMPATIBLE_ORDER, "M2": MONITORED_ORDER},
        ),
        interval_results=[
            make_interval_result(INCOMPATIBLE_ORDER, ALTERNATE_BUFFER)
        ],
    )

    transition = result.transitions[0]
    assert transition.machine_code == "M1"
    assert transition.source_order_code == MONITORED_ORDER
    assert transition.target_order_code == INCOMPATIBLE_ORDER
    assert transition.target_buffer_code == ALTERNATE_BUFFER
    assert transition.is_recommended_candidate is True
    assert result.plan_evaluations[0].status == "CONFIRMED"


def test_nonrecommended_stockout_machine_can_confirm_compatible_choice() -> None:
    plan = make_stockout_plan(
        baseline_orders=(("M1", SOURCE_ORDER), ("M2", SOURCE_ORDER)),
        candidate_machine_codes=("M1",),
        before_machine_codes=(),
        expected_machine_count=1,
    )
    changed = make_agv_binding(
        "M2",
        MONITORED_ORDER,
        NOW,
        previous_product_name=SOURCE_PRODUCT_NAME,
    )

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[plan],
            history=[changed],
            current_orders={"M1": SOURCE_ORDER, "M2": MONITORED_ORDER},
        ),
        interval_results=[
            make_interval_result(SOURCE_ORDER, SOURCE_BUFFER)
        ],
    )

    assert len(result.transitions) == 1
    transition = result.transitions[0]
    assert transition.machine_code == "M2"
    assert transition.source_order_code == SOURCE_ORDER
    assert transition.target_order_code == MONITORED_ORDER
    assert transition.source_buffer_code == SOURCE_BUFFER
    assert transition.target_buffer_code == WARNING_BUFFER
    assert transition.is_recommended_candidate is False


def test_nonrecommended_overflow_machine_reuses_compatible_target_interval() -> None:
    plan = make_overflow_plan(
        candidate_machine_codes=("M1",),
    )
    changed = make_agv_binding(
        "M2",
        ALTERNATE_ORDER,
        NOW,
        previous_product_name=MONITORED_PRODUCT_NAME,
    )

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[plan],
            history=[changed],
            current_orders={"M1": MONITORED_ORDER, "M2": ALTERNATE_ORDER},
        ),
        interval_results=[
            make_interval_result(ALTERNATE_ORDER, ALTERNATE_BUFFER)
        ],
    )

    transition = result.transitions[0]
    assert transition.machine_code == "M2"
    assert transition.source_order_code == MONITORED_ORDER
    assert transition.target_order_code == ALTERNATE_ORDER
    assert transition.source_buffer_code == WARNING_BUFFER
    assert transition.target_buffer_code == ALTERNATE_BUFFER
    assert transition.target_upstream_process_code == CUT_PROCESS
    assert transition.target_downstream_process_code == DOWNSTREAM_PROCESS
    assert transition.is_recommended_candidate is False


def test_count_neutral_one_in_one_out_still_confirms_physical_switch() -> None:
    plan = make_stockout_plan()
    changed = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        NOW,
        previous_product_name=SOURCE_PRODUCT_NAME,
    )

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[plan],
            history=[changed],
            current_orders={"M1": MONITORED_ORDER, "M2": SOURCE_ORDER},
        ),
        interval_results=[],
    )

    assert [item.machine_code for item in result.transitions] == ["M1"]
    evaluation = result.plan_evaluations[0]
    assert evaluation.before_machine_count == 1
    assert evaluation.current_machine_count == 1
    assert evaluation.status == "CONFIRMED"


@pytest.mark.parametrize(
    "previous_product_name",
    [SOURCE_PRODUCT_NAME, None],
)
def test_previous_product_match_or_absence_allows_confirmation(
    previous_product_name: str | None,
) -> None:
    changed = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        NOW,
        previous_product_name=previous_product_name,
    )

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[make_stockout_plan()],
            history=[changed],
        ),
        interval_results=[],
    )

    assert [item.machine_code for item in result.transitions] == ["M1"]


@pytest.mark.parametrize(
    ("binding_time", "snapshot_time", "expected_count", "expected_status"),
    [
        (CREATED_AT, NOW, 0, "PENDING"),
        (EXPIRE_AT, EXPIRE_AT, 1, "CONFIRMED"),
        (
            EXPIRE_AT + timedelta(microseconds=1),
            EXPIRE_AT + timedelta(minutes=1),
            0,
            "EXPIRED",
        ),
        (
            NOW + timedelta(microseconds=1),
            NOW,
            0,
            "PENDING",
        ),
    ],
)
def test_confirmation_window_is_open_at_creation_closed_at_expiry_and_not_future(
    binding_time: datetime,
    snapshot_time: datetime,
    expected_count: int,
    expected_status: str,
) -> None:
    changed = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        binding_time,
        previous_product_name=SOURCE_PRODUCT_NAME,
    )

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[make_stockout_plan()],
            history=[changed],
            current_time=snapshot_time,
        ),
        interval_results=[],
    )

    assert len(result.transitions) == expected_count
    assert result.plan_evaluations[0].status == expected_status


def test_one_of_two_machines_confirmed_marks_plan_partially_confirmed() -> None:
    plan = make_stockout_plan(
        baseline_orders=(
            ("M1", SOURCE_ORDER),
            ("M2", SOURCE_ORDER),
            ("M3", MONITORED_ORDER),
        ),
        candidate_machine_codes=("M1", "M2"),
        before_machine_codes=("M3",),
        expected_machine_count=3,
    )
    changed = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        NOW,
        previous_product_name=SOURCE_PRODUCT_NAME,
    )

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[plan],
            history=[changed],
        ),
        interval_results=[],
    )

    evaluation = result.plan_evaluations[0]
    assert evaluation.status == "PARTIALLY_CONFIRMED"
    assert evaluation.confirmed_machine_codes == ["M1"]
    assert evaluation.new_confirmed_machine_codes == ["M1"]


def test_later_round_ignores_confirmed_active_and_duplicate_history_records() -> None:
    plan = make_stockout_plan(
        baseline_orders=(
            ("M1", SOURCE_ORDER),
            ("M2", SOURCE_ORDER),
            ("M3", MONITORED_ORDER),
        ),
        candidate_machine_codes=("M1", "M2"),
        confirmed_machine_codes=("M1",),
        before_machine_codes=("M3",),
        expected_machine_count=3,
    )
    first_time = CREATED_AT + timedelta(minutes=2)
    second_time = CREATED_AT + timedelta(minutes=7)
    first = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        first_time,
        previous_product_name=SOURCE_PRODUCT_NAME,
    )
    second = make_agv_binding(
        "M2",
        MONITORED_ORDER,
        second_time,
        previous_product_name=SOURCE_PRODUCT_NAME,
    )
    active = make_active_event(
        plan_id=plan.plan_id,
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=first_time,
    )

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[plan],
            history=[first, second, second],
            active_events=[active],
        ),
        interval_results=[],
    )

    assert [item.machine_code for item in result.transitions] == ["M2"]
    evaluation = result.plan_evaluations[0]
    assert evaluation.status == "CONFIRMED"
    assert evaluation.confirmed_machine_codes == ["M1", "M2"]
    assert evaluation.new_confirmed_machine_codes == ["M2"]


@pytest.mark.parametrize("include_plan_id", [True, False])
def test_existing_active_event_id_prevents_duplicate_even_without_plan_metadata(
    include_plan_id: bool,
) -> None:
    plan = make_stockout_plan()
    changed = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        NOW,
        previous_product_name=SOURCE_PRODUCT_NAME,
    )
    active = make_active_event(
        plan_id=plan.plan_id,
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=NOW,
        include_plan_id=include_plan_id,
    )

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[plan],
            history=[changed],
            active_events=[active],
        ),
        interval_results=[],
    )

    assert result.transitions == []
    assert result.plan_evaluations[0].status == "CONFIRMED"
    assert result.plan_evaluations[0].confirmed_machine_codes == ["M1"]
    assert result.plan_evaluations[0].new_confirmed_machine_codes == []


@pytest.mark.parametrize(
    ("event_update", "expected_detail"),
    [
        ({"warning_id": "WARNING-OTHER"}, "WARNING-OTHER"),
        ({"warning_id": None}, "warning_id"),
        ({"source_order_code": ALTERNATE_ORDER}, ALTERNATE_ORDER),
        ({"target_order_code": ALTERNATE_ORDER}, ALTERNATE_ORDER),
        ({"cutline_start_time": CREATED_AT}, CREATED_AT.isoformat()),
        (
            {"cutline_start_time": EXPIRE_AT + timedelta(seconds=1)},
            (EXPIRE_AT + timedelta(seconds=1)).isoformat(),
        ),
    ],
)
def test_owned_active_event_requires_complete_matching_switch_identity(
    event_update: dict[str, object],
    expected_detail: str,
) -> None:
    plan = make_stockout_plan()
    active = make_active_event(
        plan_id=plan.plan_id,
        warning_id=plan.warning_id,
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=NOW,
    ).model_copy(update=event_update)

    with pytest.raises(PendingCutlineDetectionError) as exc_info:
        PendingCutlineDetector().detect(
            snapshot=make_snapshot(
                pending_plans=[plan],
                active_events=[active],
            ),
            interval_results=[],
        )

    message = str(exc_info.value)
    for expected in (
        plan.plan_id,
        plan.warning_id,
        active.event_id,
        "M1",
        expected_detail,
    ):
        assert expected in message


def test_same_machine_can_confirm_a_later_different_plan() -> None:
    plan = make_overflow_plan(
        plan_id="PLAN-LATER",
        warning_id="WARNING-LATER",
        baseline_orders=(("M1", MONITORED_ORDER),),
        candidate_machine_codes=("M1",),
        before_machine_codes=("M1",),
        expected_machine_count=0,
        created_at=CREATED_AT + timedelta(minutes=5),
        expire_at=CREATED_AT + timedelta(minutes=35),
    )
    old_active = make_active_event(
        plan_id="PLAN-EARLIER",
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=CREATED_AT + timedelta(minutes=2),
    )
    later = make_agv_binding(
        "M1",
        ALTERNATE_ORDER,
        CREATED_AT + timedelta(minutes=8),
        previous_product_name=MONITORED_PRODUCT_NAME,
    )

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[plan],
            history=[later],
            active_events=[old_active],
        ),
        interval_results=[
            make_interval_result(ALTERNATE_ORDER, ALTERNATE_BUFFER)
        ],
    )

    assert len(result.transitions) == 1
    assert result.transitions[0].plan_id == "PLAN-LATER"
    assert result.transitions[0].machine_code == "M1"


def test_expired_plan_scans_inclusive_window_before_marking_expired() -> None:
    changed_at_expiry = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        EXPIRE_AT,
        previous_product_name=SOURCE_PRODUCT_NAME,
    )

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[make_stockout_plan()],
            history=[changed_at_expiry],
            current_time=EXPIRE_AT + timedelta(minutes=5),
        ),
        interval_results=[],
    )

    assert [item.machine_code for item in result.transitions] == ["M1"]
    assert result.plan_evaluations[0].status == "CONFIRMED"


def test_expired_plan_without_transition_is_expired() -> None:
    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[make_stockout_plan()],
            current_time=EXPIRE_AT + timedelta(microseconds=1),
        ),
        interval_results=[],
    )

    assert result.transitions == []
    assert result.plan_evaluations[0].status == "EXPIRED"


@pytest.mark.parametrize(
    "status",
    ["CONFIRMED", "EXPIRED", "RETURN_SUGGESTED"],
)
def test_terminal_plan_replay_is_inert_and_preserves_status(status: str) -> None:
    confirmed_codes = () if status == "EXPIRED" else ("M1",)
    plan = make_stockout_plan(
        status=status,
        confirmed_machine_codes=confirmed_codes,
    )
    later_change = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        NOW,
        previous_product_name=SOURCE_PRODUCT_NAME,
    )
    active_events = []
    if confirmed_codes:
        active = make_active_event(
            plan_id=plan.plan_id,
            warning_id=plan.warning_id,
            machine_code="M1",
            source_order_code=SOURCE_ORDER,
            target_order_code=MONITORED_ORDER,
            cutline_start_time=CREATED_AT + timedelta(minutes=1),
        )
        if status == "RETURN_SUGGESTED":
            active = active.model_copy(update={"status": "return_recommended"})
        active_events = [active]

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[plan],
            history=[later_change],
            active_events=active_events,
        ),
        interval_results=[],
    )

    assert result.transitions == []
    evaluation = result.plan_evaluations[0]
    assert evaluation.status.value == status
    assert evaluation.new_confirmed_machine_codes == []


@pytest.mark.parametrize(
    ("target_order", "runtime_target"),
    [
        (ALTERNATE_ORDER, ALTERNATE_ORDER),
        (SOURCE_ORDER, MONITORED_ORDER),
    ],
)
def test_wrong_direction_or_runtime_status_only_does_not_confirm(
    target_order: str,
    runtime_target: str,
) -> None:
    history = []
    if target_order != SOURCE_ORDER:
        history = [
            make_agv_binding(
                "M1",
                target_order,
                NOW,
                previous_product_name=SOURCE_PRODUCT_NAME,
            )
        ]

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[make_stockout_plan()],
            history=history,
            current_orders={"M1": runtime_target, "M2": MONITORED_ORDER},
        ),
        interval_results=[
            make_interval_result(ALTERNATE_ORDER, ALTERNATE_BUFFER)
        ],
    )

    assert result.transitions == []
    assert result.plan_evaluations[0].status == "PENDING"


def test_unrelated_workshop_and_process_history_is_ignored() -> None:
    workshop_noise = make_agv_binding(
        "M-W2",
        ALTERNATE_ORDER,
        NOW,
        previous_product_name=MONITORED_PRODUCT_NAME,
    )
    process_noise = make_agv_binding(
        "M-POTHER",
        ALTERNATE_ORDER,
        NOW,
        previous_product_name=MONITORED_PRODUCT_NAME,
    )

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[make_overflow_plan()],
            history=[workshop_noise, process_noise],
        ),
        interval_results=[
            make_interval_result(ALTERNATE_ORDER, ALTERNATE_BUFFER)
        ],
    )

    assert result.transitions == []
    assert result.plan_evaluations[0].status == "PENDING"


def test_machine_scope_uses_plan_process_not_warning_interval_process() -> None:
    plan = make_stockout_plan().model_copy(
        update={
            "process_code": CUT_PROCESS,
            "upstream_process_code": OTHER_PROCESS,
        }
    )
    changed = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        NOW,
        previous_product_name=SOURCE_PRODUCT_NAME,
    )

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[plan],
            history=[changed],
        ),
        interval_results=[],
    )

    assert [item.machine_code for item in result.transitions] == ["M1"]
    assert result.plan_evaluations[0].status == "CONFIRMED"


def test_previous_product_conflict_reports_complete_transition_context() -> None:
    changed = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        NOW,
        previous_product_name=ALTERNATE_PRODUCT_NAME,
    )

    with pytest.raises(PendingCutlineDetectionError) as exc_info:
        PendingCutlineDetector().detect(
            snapshot=make_snapshot(
                pending_plans=[make_stockout_plan()],
                history=[changed],
            ),
            interval_results=[],
        )

    message = str(exc_info.value)
    assert "PLAN-STOCKOUT" in message
    assert "M1" in message
    assert SOURCE_PRODUCT_NAME in message
    assert ALTERNATE_PRODUCT_NAME in message
    assert NOW.isoformat() in message


def test_current_count_uses_only_running_workshop_process_and_order_scope() -> None:
    plan = make_stockout_plan()
    changed = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        NOW,
        previous_product_name=SOURCE_PRODUCT_NAME,
    )
    current_orders = {
        "M1": MONITORED_ORDER,
        "M2": MONITORED_ORDER,
        "M3": MONITORED_ORDER,
        "M-W2": MONITORED_ORDER,
        "M-POTHER": MONITORED_ORDER,
    }

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[plan],
            history=[changed],
            current_orders=current_orders,
            statuses={"M2": "paused"},
        ),
        interval_results=[],
    )

    evaluation = result.plan_evaluations[0]
    assert evaluation.current_machine_count == 2
    assert evaluation.current_machine_codes == ["M1", "M3"]
    assert evaluation.status == "CONFIRMED"


def test_candidate_and_noncandidate_claims_for_same_switch_are_ambiguous() -> None:
    preferred = make_stockout_plan(
        plan_id="PLAN-PREFERRED",
        warning_id="WARNING-PREFERRED",
        candidate_machine_codes=("M1",),
    )
    fallback = make_stockout_plan(
        plan_id="PLAN-FALLBACK",
        warning_id="WARNING-FALLBACK",
        baseline_orders=(
            ("M1", SOURCE_ORDER),
            ("M2", MONITORED_ORDER),
            ("M3", SOURCE_ORDER),
        ),
        candidate_machine_codes=("M3",),
    )
    changed = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        NOW,
        previous_product_name=SOURCE_PRODUCT_NAME,
    )

    with pytest.raises(PendingCutlineDetectionError) as exc_info:
        PendingCutlineDetector().detect(
            snapshot=make_snapshot(
                pending_plans=[fallback, preferred],
                history=[changed],
            ),
            interval_results=[],
        )

    message = str(exc_info.value)
    for expected in (
        "PLAN-PREFERRED",
        "WARNING-PREFERRED",
        "PLAN-FALLBACK",
        "WARNING-FALLBACK",
        "M1",
        SOURCE_ORDER,
        MONITORED_ORDER,
        NOW.isoformat(),
    ):
        assert expected in message


@pytest.mark.parametrize("claim_kind", ["candidate", "noncandidate"])
def test_equal_priority_claims_for_same_switch_are_explicit_conflicts(
    claim_kind: str,
) -> None:
    candidate_codes = ("M1",) if claim_kind == "candidate" else ("M3",)
    first = make_stockout_plan(
        plan_id="PLAN-A",
        warning_id="WARNING-A",
        baseline_orders=(
            ("M1", SOURCE_ORDER),
            ("M2", MONITORED_ORDER),
            ("M3", SOURCE_ORDER),
        ),
        candidate_machine_codes=candidate_codes,
    )
    second = make_stockout_plan(
        plan_id="PLAN-B",
        warning_id="WARNING-B",
        baseline_orders=(
            ("M1", SOURCE_ORDER),
            ("M2", MONITORED_ORDER),
            ("M3", SOURCE_ORDER),
        ),
        candidate_machine_codes=candidate_codes,
    )
    changed = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        NOW,
        previous_product_name=SOURCE_PRODUCT_NAME,
    )

    with pytest.raises(PendingCutlineDetectionError) as exc_info:
        PendingCutlineDetector().detect(
            snapshot=make_snapshot(
                pending_plans=[first, second],
                history=[changed],
            ),
            interval_results=[],
        )

    message = str(exc_info.value)
    assert "PLAN-A" in message
    assert "PLAN-B" in message
    assert "M1" in message
    assert NOW.isoformat() in message


def test_raw_candidate_conflict_is_detected_before_plan_slot_truncation() -> None:
    first = make_stockout_plan(
        plan_id="PLAN-A",
        warning_id="WARNING-A",
        baseline_orders=(
            ("M1", SOURCE_ORDER),
            ("M2", SOURCE_ORDER),
            ("M3", MONITORED_ORDER),
        ),
        candidate_machine_codes=("M1", "M2"),
        before_machine_codes=("M3",),
        expected_machine_count=2,
    )
    second = make_stockout_plan(
        plan_id="PLAN-B",
        warning_id="WARNING-B",
        baseline_orders=(
            ("M2", SOURCE_ORDER),
            ("M3", MONITORED_ORDER),
        ),
        candidate_machine_codes=("M2",),
        before_machine_codes=("M3",),
        expected_machine_count=2,
    )
    earlier_change = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        CREATED_AT + timedelta(minutes=1),
        previous_product_name=SOURCE_PRODUCT_NAME,
    )
    disputed_change_time = CREATED_AT + timedelta(minutes=2)
    disputed_change = make_agv_binding(
        "M2",
        MONITORED_ORDER,
        disputed_change_time,
        previous_product_name=SOURCE_PRODUCT_NAME,
    )

    with pytest.raises(PendingCutlineDetectionError) as exc_info:
        PendingCutlineDetector().detect(
            snapshot=make_snapshot(
                pending_plans=[first, second],
                history=[earlier_change, disputed_change],
                current_orders={
                    "M1": MONITORED_ORDER,
                    "M2": MONITORED_ORDER,
                    "M3": MONITORED_ORDER,
                },
            ),
            interval_results=[],
        )

    message = str(exc_info.value)
    assert "PLAN-A" in message
    assert "PLAN-B" in message
    assert "M2" in message
    assert disputed_change_time.isoformat() in message


def test_raw_fallback_conflict_is_detected_before_plan_slot_truncation() -> None:
    first = make_stockout_plan(
        plan_id="PLAN-A",
        warning_id="WARNING-A",
        baseline_orders=(
            ("M1", SOURCE_ORDER),
            ("M2", SOURCE_ORDER),
            ("M3", SOURCE_ORDER),
        ),
        candidate_machine_codes=("M3",),
        before_machine_codes=(),
        expected_machine_count=1,
    )
    second = make_stockout_plan(
        plan_id="PLAN-B",
        warning_id="WARNING-B",
        baseline_orders=(("M2", SOURCE_ORDER), ("M3", SOURCE_ORDER)),
        candidate_machine_codes=("M3",),
        before_machine_codes=(),
        expected_machine_count=1,
    )
    earlier_change = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        CREATED_AT + timedelta(minutes=1),
        previous_product_name=SOURCE_PRODUCT_NAME,
    )
    disputed_change_time = CREATED_AT + timedelta(minutes=2)
    disputed_change = make_agv_binding(
        "M2",
        MONITORED_ORDER,
        disputed_change_time,
        previous_product_name=SOURCE_PRODUCT_NAME,
    )

    with pytest.raises(PendingCutlineDetectionError) as exc_info:
        PendingCutlineDetector().detect(
            snapshot=make_snapshot(
                pending_plans=[first, second],
                history=[earlier_change, disputed_change],
                current_orders={
                    "M1": MONITORED_ORDER,
                    "M2": MONITORED_ORDER,
                    "M3": SOURCE_ORDER,
                },
            ),
            interval_results=[make_interval_result(SOURCE_ORDER, SOURCE_BUFFER)],
        )

    message = str(exc_info.value)
    assert "PLAN-A" in message
    assert "PLAN-B" in message
    assert "M2" in message
    assert disputed_change_time.isoformat() in message


def test_nonrecommended_overflow_does_not_apply_candidate_compatibility() -> None:
    changed = make_agv_binding(
        "M2",
        INCOMPATIBLE_ORDER,
        NOW,
        previous_product_name=MONITORED_PRODUCT_NAME,
    )

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[make_overflow_plan()],
            history=[changed],
            current_orders={"M1": MONITORED_ORDER, "M2": INCOMPATIBLE_ORDER},
        ),
        interval_results=[
            make_interval_result(
                INCOMPATIBLE_ORDER,
                ALTERNATE_BUFFER,
                net_consumption_rate=-1.0,
            )
        ],
    )

    assert len(result.transitions) == 1
    transition = result.transitions[0]
    assert transition.machine_code == "M2"
    assert transition.source_order_code == MONITORED_ORDER
    assert transition.target_order_code == INCOMPATIBLE_ORDER
    assert transition.target_buffer_code == ALTERNATE_BUFFER
    assert transition.is_recommended_candidate is False
    assert result.plan_evaluations[0].status == "CONFIRMED"


def test_nonrecommended_stockout_does_not_apply_candidate_compatibility() -> None:
    plan = make_stockout_plan(
        baseline_orders=(
            ("M1", SOURCE_ORDER),
            ("M2", INCOMPATIBLE_ORDER),
        ),
        candidate_machine_codes=("M1",),
        before_machine_codes=(),
        expected_machine_count=1,
    )
    changed = make_agv_binding(
        "M2",
        MONITORED_ORDER,
        NOW,
        previous_product_name=INCOMPATIBLE_PRODUCT_NAME,
    )

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[plan],
            history=[changed],
            current_orders={"M1": SOURCE_ORDER, "M2": MONITORED_ORDER},
        ),
        interval_results=[
            make_interval_result(INCOMPATIBLE_ORDER, SOURCE_BUFFER)
        ],
    )

    assert len(result.transitions) == 1
    transition = result.transitions[0]
    assert transition.machine_code == "M2"
    assert transition.source_order_code == INCOMPATIBLE_ORDER
    assert transition.target_order_code == MONITORED_ORDER
    assert transition.is_recommended_candidate is False
    assert result.plan_evaluations[0].status == "CONFIRMED"


def test_nonrecommended_overflow_without_target_interval_is_explicit_error() -> None:
    plan = make_overflow_plan(candidate_machine_codes=("M1",))
    changed = make_agv_binding(
        "M2",
        ALTERNATE_ORDER,
        NOW,
        previous_product_name=MONITORED_PRODUCT_NAME,
    )

    with pytest.raises(PendingCutlineDetectionError) as exc_info:
        PendingCutlineDetector().detect(
            snapshot=make_snapshot(
                pending_plans=[plan],
                history=[changed],
                current_orders={
                    "M1": MONITORED_ORDER,
                    "M2": ALTERNATE_ORDER,
                },
            ),
            interval_results=[],
        )

    message = str(exc_info.value)
    for expected in (
        plan.plan_id,
        plan.warning_id,
        "M2",
        ALTERNATE_ORDER,
        "target interval",
    ):
        assert expected in message


def test_recommended_confirmation_uses_only_slot_before_noncandidate() -> None:
    plan = make_stockout_plan(
        baseline_orders=(
            ("M1", SOURCE_ORDER),
            ("M2", SOURCE_ORDER),
        ),
        candidate_machine_codes=("M1",),
        before_machine_codes=(),
        expected_machine_count=1,
    )
    recommended = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        CREATED_AT + timedelta(minutes=2),
        previous_product_name=SOURCE_PRODUCT_NAME,
    )
    fallback = make_agv_binding(
        "M2",
        MONITORED_ORDER,
        CREATED_AT + timedelta(minutes=3),
        previous_product_name=SOURCE_PRODUCT_NAME,
    )

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[plan],
            history=[fallback, recommended],
            current_orders={"M1": MONITORED_ORDER, "M2": MONITORED_ORDER},
        ),
        interval_results=[make_interval_result(SOURCE_ORDER, SOURCE_BUFFER)],
    )

    assert [item.machine_code for item in result.transitions] == ["M1"]
    assert result.plan_evaluations[0].new_confirmed_machine_codes == ["M1"]


def test_already_satisfied_partial_plan_does_not_scan_more_machines() -> None:
    plan = make_stockout_plan(
        baseline_orders=(
            ("M1", SOURCE_ORDER),
            ("M2", MONITORED_ORDER),
            ("M3", SOURCE_ORDER),
        ),
        candidate_machine_codes=("M1",),
        confirmed_machine_codes=("M1",),
        before_machine_codes=("M2",),
        expected_machine_count=2,
    )
    extra_change = make_agv_binding(
        "M3",
        MONITORED_ORDER,
        NOW,
        previous_product_name=SOURCE_PRODUCT_NAME,
    )
    confirmed_active = make_active_event(
        plan_id=plan.plan_id,
        warning_id=plan.warning_id,
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=CREATED_AT + timedelta(minutes=1),
    )

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[plan],
            history=[extra_change],
            active_events=[confirmed_active],
            current_orders={
                "M1": MONITORED_ORDER,
                "M2": MONITORED_ORDER,
                "M3": MONITORED_ORDER,
            },
        ),
        interval_results=[make_interval_result(SOURCE_ORDER, SOURCE_BUFFER)],
    )

    assert result.transitions == []
    evaluation = result.plan_evaluations[0]
    assert evaluation.status == "CONFIRMED"
    assert evaluation.confirmed_machine_codes == ["M1"]
    assert evaluation.new_confirmed_machine_codes == []


def test_confirmed_pending_machine_requires_matching_active_event() -> None:
    plan = make_stockout_plan(confirmed_machine_codes=("M1",))

    with pytest.raises(ValidationError) as exc_info:
        make_snapshot(pending_plans=[plan])

    message = str(exc_info.value)
    for expected in (
        plan.plan_id,
        plan.warning_id,
        "M1",
        "active_cutline_events",
    ):
        assert expected in message


def test_foreign_active_same_physical_switch_is_an_explicit_conflict() -> None:
    plan = make_stockout_plan()
    changed = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        NOW,
        previous_product_name=SOURCE_PRODUCT_NAME,
    )
    foreign_active = make_active_event(
        plan_id="PLAN-OTHER",
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=NOW,
    )

    with pytest.raises(PendingCutlineDetectionError) as exc_info:
        PendingCutlineDetector().detect(
            snapshot=make_snapshot(
                pending_plans=[plan],
                history=[changed],
                active_events=[foreign_active],
            ),
            interval_results=[],
        )

    message = str(exc_info.value)
    for expected in (
        plan.plan_id,
        plan.warning_id,
        "PLAN-OTHER",
        "M1",
        SOURCE_ORDER,
        MONITORED_ORDER,
        NOW.isoformat(),
    ):
        assert expected in message


def test_same_plan_active_metadata_counts_without_stable_event_id() -> None:
    plan = make_stockout_plan()
    owned_active = make_active_event(
        plan_id=plan.plan_id,
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=NOW,
    ).model_copy(update={"event_id": "EXTERNAL-ACTIVE-ID"})

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[plan],
            active_events=[owned_active],
        ),
        interval_results=[],
    )

    assert result.transitions == []
    evaluation = result.plan_evaluations[0]
    assert evaluation.status == "CONFIRMED"
    assert evaluation.confirmed_machine_codes == ["M1"]


def test_foreign_active_candidate_conflict_is_checked_before_fallback() -> None:
    plan = make_stockout_plan(
        baseline_orders=(
            ("M1", SOURCE_ORDER),
            ("M2", SOURCE_ORDER),
        ),
        candidate_machine_codes=("M1",),
        before_machine_codes=(),
        expected_machine_count=1,
    )
    candidate_time = CREATED_AT + timedelta(minutes=2)
    candidate_change = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        candidate_time,
        previous_product_name=SOURCE_PRODUCT_NAME,
    )
    fallback_change = make_agv_binding(
        "M2",
        MONITORED_ORDER,
        CREATED_AT + timedelta(minutes=3),
        previous_product_name=SOURCE_PRODUCT_NAME,
    )
    foreign_active = make_active_event(
        plan_id="PLAN-OTHER",
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=candidate_time,
    )

    with pytest.raises(PendingCutlineDetectionError, match="PLAN-OTHER"):
        PendingCutlineDetector().detect(
            snapshot=make_snapshot(
                pending_plans=[plan],
                history=[candidate_change, fallback_change],
                current_orders={"M1": MONITORED_ORDER, "M2": MONITORED_ORDER},
                active_events=[foreign_active],
            ),
            interval_results=[make_interval_result(SOURCE_ORDER, SOURCE_BUFFER)],
        )


def test_stable_event_id_with_wrong_machine_is_explicit_conflict() -> None:
    plan = make_stockout_plan()
    disguised = make_active_event(
        plan_id="PLAN-OTHER",
        machine_code="M2",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=NOW,
    ).model_copy(update={"event_id": f"CUT-{plan.plan_id}-M1"})

    with pytest.raises(PendingCutlineDetectionError) as exc_info:
        PendingCutlineDetector().detect(
            snapshot=make_snapshot(
                pending_plans=[plan],
                active_events=[disguised],
            ),
            interval_results=[],
        )

    message = str(exc_info.value)
    assert plan.plan_id in message
    assert disguised.event_id in message
    assert "M1" in message
    assert "M2" in message


def test_stable_event_id_with_foreign_plan_metadata_is_explicit_conflict() -> None:
    plan = make_stockout_plan()
    disguised = make_active_event(
        plan_id="PLAN-OTHER",
        machine_code="M1",
        source_order_code=SOURCE_ORDER,
        target_order_code=MONITORED_ORDER,
        cutline_start_time=NOW,
    ).model_copy(update={"event_id": f"CUT-{plan.plan_id}-M1"})

    with pytest.raises(PendingCutlineDetectionError) as exc_info:
        PendingCutlineDetector().detect(
            snapshot=make_snapshot(
                pending_plans=[plan],
                active_events=[disguised],
            ),
            interval_results=[],
        )

    message = str(exc_info.value)
    assert plan.plan_id in message
    assert disguised.plan_id in message
    assert disguised.event_id in message
    assert disguised.machine_code in message


def test_recommended_confirmation_uses_observed_target_wafer_spec() -> None:
    changed = make_agv_binding(
        "M1",
        MONITORED_ORDER,
        NOW,
        previous_product_name=SOURCE_PRODUCT_NAME,
    ).model_copy(update={"wafer_spec": "M12-P"})

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[make_stockout_plan()],
            history=[changed],
        ),
        interval_results=[],
    )

    assert len(result.transitions) == 1
    assert result.transitions[0].machine_code == "M1"
    assert result.transitions[0].target_order_code == MONITORED_ORDER
    assert result.transitions[0].target_wafer_spec == "M12-P"
    assert result.transitions[0].is_recommended_candidate is True
    assert result.plan_evaluations[0].status == "CONFIRMED"


def test_stockout_source_duplicate_business_records_are_conflict() -> None:
    plan = make_stockout_plan(
        baseline_orders=(("M1", SOURCE_ORDER), ("M2", SOURCE_ORDER)),
        candidate_machine_codes=("M1",),
        before_machine_codes=(),
        expected_machine_count=1,
    )
    changed = make_agv_binding(
        "M2",
        MONITORED_ORDER,
        NOW,
        previous_product_name=SOURCE_PRODUCT_NAME,
    )
    source = make_interval_result(SOURCE_ORDER, SOURCE_BUFFER)
    conflicting = source.model_copy(update={"current_quantity": 101.0})

    with pytest.raises(PendingCutlineDetectionError) as exc_info:
        PendingCutlineDetector().detect(
            snapshot=make_snapshot(
                pending_plans=[plan],
                history=[changed],
                current_orders={
                    "M1": SOURCE_ORDER,
                    "M2": MONITORED_ORDER,
                },
            ),
            interval_results=[source, conflicting],
        )

    message = str(exc_info.value)
    assert plan.plan_id in message
    assert "M2" in message
    assert "duplicate source interval business records conflict" in message
    assert SOURCE_BUFFER in message


def test_stockout_source_exact_duplicate_records_collapse() -> None:
    plan = make_stockout_plan(
        baseline_orders=(("M1", SOURCE_ORDER), ("M2", SOURCE_ORDER)),
        candidate_machine_codes=("M1",),
        before_machine_codes=(),
        expected_machine_count=1,
    )
    changed = make_agv_binding(
        "M2",
        MONITORED_ORDER,
        NOW,
        previous_product_name=SOURCE_PRODUCT_NAME,
    )
    source = make_interval_result(SOURCE_ORDER, SOURCE_BUFFER)

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[plan],
            history=[changed],
            current_orders={"M1": SOURCE_ORDER, "M2": MONITORED_ORDER},
        ),
        interval_results=[source, source.model_copy(deep=True)],
    )

    assert [item.machine_code for item in result.transitions] == ["M2"]
    assert result.transitions[0].source_buffer_code == SOURCE_BUFFER


def test_overflow_target_duplicate_business_records_are_conflict() -> None:
    changed = make_agv_binding(
        "M2",
        ALTERNATE_ORDER,
        NOW,
        previous_product_name=MONITORED_PRODUCT_NAME,
    )
    target = make_interval_result(ALTERNATE_ORDER, ALTERNATE_BUFFER)
    conflicting = target.model_copy(update={"current_quantity": 101.0})

    with pytest.raises(PendingCutlineDetectionError) as exc_info:
        PendingCutlineDetector().detect(
            snapshot=make_snapshot(
                pending_plans=[make_overflow_plan()],
                history=[changed],
                current_orders={
                    "M1": MONITORED_ORDER,
                    "M2": ALTERNATE_ORDER,
                },
            ),
            interval_results=[target, conflicting],
        )

    message = str(exc_info.value)
    assert "PLAN-OVERFLOW" in message
    assert "M2" in message
    assert ALTERNATE_BUFFER in message


def test_overflow_target_exact_duplicate_records_collapse() -> None:
    changed = make_agv_binding(
        "M2",
        ALTERNATE_ORDER,
        NOW,
        previous_product_name=MONITORED_PRODUCT_NAME,
    )
    target = make_interval_result(ALTERNATE_ORDER, ALTERNATE_BUFFER)

    result = PendingCutlineDetector().detect(
        snapshot=make_snapshot(
            pending_plans=[make_overflow_plan()],
            history=[changed],
            current_orders={
                "M1": MONITORED_ORDER,
                "M2": ALTERNATE_ORDER,
            },
        ),
        interval_results=[target, target.model_copy(deep=True)],
    )

    assert [item.machine_code for item in result.transitions] == ["M2"]
