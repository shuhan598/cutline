from __future__ import annotations

from datetime import datetime, timedelta, timezone
from app.schemas.common_schema import (
    AlgorithmActiveCutlineEvent,
    AlgorithmAgvRelation,
    AlgorithmBufferMaster,
    AlgorithmBufferOrderInventory,
    AlgorithmBufferProcessRelation,
    AlgorithmConfig,
    AlgorithmMachineMaster,
    AlgorithmMachineProductCapacity,
    AlgorithmMachineRuntime,
    AlgorithmOrder,
    AlgorithmProcessRoute,
    AlgorithmProduct,
    AlgorithmWorkshop,
)
from app.schemas.pending_cutline_schema import (
    BaselineMachineBinding,
    PendingCandidateMachine,
    PendingCutlinePlan,
    PendingCutlinePlanStatus,
)
from app.schemas.request_schema import AlgorithmSnapshot
from app.schemas.result_schema import AlgorithmIntervalNetRateResult


UTC = timezone.utc
CREATED_AT = datetime(2026, 8, 2, 8, 0, tzinfo=UTC)
EXPIRE_AT = CREATED_AT + timedelta(minutes=30)
NOW = CREATED_AT + timedelta(minutes=10)

WORKSHOP = "W1"
OTHER_WORKSHOP = "W2"
CUT_PROCESS = "P-CUT"
OTHER_PROCESS = "P-OTHER"
DOWNSTREAM_PROCESS = "P-DOWN"

WARNING_BUFFER = "B-WARN"
SOURCE_BUFFER = "B-SOURCE"
ALTERNATE_BUFFER = "B-ALT"

MONITORED_ORDER = "O-MON"
SOURCE_ORDER = "O-SOURCE"
ALTERNATE_ORDER = "O-ALT"
INCOMPATIBLE_ORDER = "O-BAD"

MONITORED_PRODUCT = "P-MON"
SOURCE_PRODUCT = "P-SOURCE"
ALTERNATE_PRODUCT = "P-ALT"
INCOMPATIBLE_PRODUCT = "P-BAD"

MONITORED_PRODUCT_NAME = "Monitored Product"
SOURCE_PRODUCT_NAME = "Source Product"
ALTERNATE_PRODUCT_NAME = "Alternate Product"
INCOMPATIBLE_PRODUCT_NAME = "Incompatible Product"


def make_baseline(
    machine_code: str,
    order_code: str,
    *,
    process_code: str = CUT_PROCESS,
    workshop_code: str = WORKSHOP,
    observed_at: datetime = CREATED_AT - timedelta(minutes=1),
    machine_status: str | None = "running",
) -> BaselineMachineBinding:
    product_code, product_name, wafer_size, wafer_spec, source_grade = (
        product_identity(order_code)
    )
    return BaselineMachineBinding(
        machine_code=machine_code,
        order_code=order_code,
        product_code=product_code,
        product_name=product_name,
        wafer_size=wafer_size,
        wafer_spec=wafer_spec,
        source_grade=source_grade,
        process_code=process_code,
        workshop_code=workshop_code,
        machine_status=machine_status,
        observed_at=observed_at,
    )


def make_candidate(
    machine_code: str,
    baseline_order_code: str,
    target_order_code: str,
    *,
    source_buffer_code: str | None,
    target_buffer_code: str,
    target_upstream_process_code: str = CUT_PROCESS,
    target_downstream_process_code: str = DOWNSTREAM_PROCESS,
) -> PendingCandidateMachine:
    (
        baseline_product_code,
        baseline_product_name,
        baseline_wafer_size,
        baseline_wafer_spec,
        baseline_source_grade,
    ) = product_identity(baseline_order_code)
    (
        target_product_code,
        target_product_name,
        target_wafer_size,
        target_wafer_spec,
        target_source_grade,
    ) = product_identity(target_order_code)
    return PendingCandidateMachine(
        machine_code=machine_code,
        baseline_order_code=baseline_order_code,
        baseline_product_code=baseline_product_code,
        baseline_product_name=baseline_product_name,
        baseline_wafer_size=baseline_wafer_size,
        baseline_wafer_spec=baseline_wafer_spec,
        baseline_source_grade=baseline_source_grade,
        expected_target_order_code=target_order_code,
        expected_target_product_code=target_product_code,
        expected_target_product_name=target_product_name,
        expected_target_wafer_size=target_wafer_size,
        expected_target_wafer_spec=target_wafer_spec,
        expected_target_source_grade=target_source_grade,
        process_code=CUT_PROCESS,
        workshop_code=WORKSHOP,
        source_buffer_code=source_buffer_code,
        target_buffer_code=target_buffer_code,
        target_upstream_process_code=target_upstream_process_code,
        target_downstream_process_code=target_downstream_process_code,
    )


def make_stockout_plan(
    *,
    plan_id: str = "PLAN-STOCKOUT",
    warning_id: str = "WARNING-STOCKOUT",
    baseline_orders: tuple[tuple[str, str], ...] = (
        ("M1", SOURCE_ORDER),
        ("M2", MONITORED_ORDER),
    ),
    candidate_machine_codes: tuple[str, ...] = ("M1",),
    confirmed_machine_codes: tuple[str, ...] = (),
    before_machine_codes: tuple[str, ...] = ("M2",),
    expected_machine_count: int = 2,
    created_at: datetime = CREATED_AT,
    expire_at: datetime = EXPIRE_AT,
    status: PendingCutlinePlanStatus | str | None = None,
    process_code: str | None = CUT_PROCESS,
    source_order_code: str | None = SOURCE_ORDER,
    target_order_code: str | None = MONITORED_ORDER,
    source_product_code: str | None = SOURCE_PRODUCT,
    target_product_code: str | None = MONITORED_PRODUCT,
) -> PendingCutlinePlan:
    baseline = [
        make_baseline(machine_code, order_code)
        for machine_code, order_code in baseline_orders
    ]
    baseline_by_machine = {
        binding.machine_code: binding for binding in baseline
    }
    candidates = [
        make_candidate(
            machine_code,
            baseline_by_machine[machine_code].order_code,
            MONITORED_ORDER,
            source_buffer_code=SOURCE_BUFFER,
            target_buffer_code=WARNING_BUFFER,
        )
        for machine_code in candidate_machine_codes
    ]
    required_confirmations = abs(
        expected_machine_count - len(before_machine_codes)
    )
    if status is not None:
        resolved_status = status
    elif len(confirmed_machine_codes) == required_confirmations:
        resolved_status = PendingCutlinePlanStatus.CONFIRMED
    elif confirmed_machine_codes:
        resolved_status = PendingCutlinePlanStatus.PARTIALLY_CONFIRMED
    else:
        resolved_status = PendingCutlinePlanStatus.PENDING
    return PendingCutlinePlan(
        plan_id=plan_id,
        warning_id=warning_id,
        warning_type="stockout",
        warning_time=created_at,
        created_at=created_at,
        expire_at=expire_at,
        status=resolved_status,
        workshop_code=WORKSHOP,
        buffer_code=WARNING_BUFFER,
        upstream_process_code=CUT_PROCESS,
        downstream_process_code=DOWNSTREAM_PROCESS,
        monitored_order_code=MONITORED_ORDER,
        process_code=process_code,
        source_order_code=source_order_code,
        target_order_code=target_order_code,
        source_product_code=source_product_code,
        target_product_code=target_product_code,
        before_machine_count=len(before_machine_codes),
        before_machine_codes=list(before_machine_codes),
        expected_machine_count=expected_machine_count,
        expected_delta_direction="increase",
        candidate_machines=candidates,
        baseline_machine_bindings=baseline,
        confirmed_machine_codes=list(confirmed_machine_codes),
    )


def make_overflow_plan(
    *,
    plan_id: str = "PLAN-OVERFLOW",
    warning_id: str = "WARNING-OVERFLOW",
    baseline_orders: tuple[tuple[str, str], ...] = (
        ("M1", MONITORED_ORDER),
        ("M2", MONITORED_ORDER),
    ),
    candidate_machine_codes: tuple[str, ...] = ("M1",),
    confirmed_machine_codes: tuple[str, ...] = (),
    before_machine_codes: tuple[str, ...] = ("M1", "M2"),
    expected_machine_count: int = 1,
    created_at: datetime = CREATED_AT,
    expire_at: datetime = EXPIRE_AT,
    status: PendingCutlinePlanStatus | str | None = None,
    process_code: str | None = CUT_PROCESS,
    source_order_code: str | None = MONITORED_ORDER,
    target_order_code: str | None = ALTERNATE_ORDER,
    source_product_code: str | None = MONITORED_PRODUCT,
    target_product_code: str | None = ALTERNATE_PRODUCT,
) -> PendingCutlinePlan:
    baseline = [
        make_baseline(machine_code, order_code)
        for machine_code, order_code in baseline_orders
    ]
    baseline_by_machine = {
        binding.machine_code: binding for binding in baseline
    }
    candidates = [
        make_candidate(
            machine_code,
            baseline_by_machine[machine_code].order_code,
            ALTERNATE_ORDER,
            source_buffer_code=(
                WARNING_BUFFER
                if baseline_by_machine[machine_code].order_code == MONITORED_ORDER
                else SOURCE_BUFFER
            ),
            target_buffer_code=ALTERNATE_BUFFER,
        )
        for machine_code in candidate_machine_codes
    ]
    required_confirmations = abs(
        expected_machine_count - len(before_machine_codes)
    )
    if status is not None:
        resolved_status = status
    elif len(confirmed_machine_codes) == required_confirmations:
        resolved_status = PendingCutlinePlanStatus.CONFIRMED
    elif confirmed_machine_codes:
        resolved_status = PendingCutlinePlanStatus.PARTIALLY_CONFIRMED
    else:
        resolved_status = PendingCutlinePlanStatus.PENDING
    return PendingCutlinePlan(
        plan_id=plan_id,
        warning_id=warning_id,
        warning_type="overflow",
        warning_time=created_at,
        created_at=created_at,
        expire_at=expire_at,
        status=resolved_status,
        workshop_code=WORKSHOP,
        buffer_code=WARNING_BUFFER,
        upstream_process_code=CUT_PROCESS,
        downstream_process_code=DOWNSTREAM_PROCESS,
        monitored_order_code=MONITORED_ORDER,
        process_code=process_code,
        source_order_code=source_order_code,
        target_order_code=target_order_code,
        source_product_code=source_product_code,
        target_product_code=target_product_code,
        before_machine_count=len(before_machine_codes),
        before_machine_codes=list(before_machine_codes),
        expected_machine_count=expected_machine_count,
        expected_delta_direction="decrease",
        candidate_machines=candidates,
        baseline_machine_bindings=baseline,
        confirmed_machine_codes=list(confirmed_machine_codes),
    )


def make_agv_binding(
    machine_code: str,
    order_code: str,
    binding_time: datetime,
    *,
    previous_product_name: str | None,
) -> AlgorithmAgvRelation:
    product_code, product_name, _, wafer_spec, _ = product_identity(order_code)
    return AlgorithmAgvRelation(
        machine_code=machine_code,
        machine_name=f"Machine {machine_code}",
        order_code=order_code,
        product_code=product_code,
        product_name=product_name,
        previous_product_code=product_code_for_name(previous_product_name),
        previous_product_name=previous_product_name,
        wafer_spec=wafer_spec,
        binding_time=binding_time,
    )


def make_active_event(
    *,
    plan_id: str,
    machine_code: str,
    source_order_code: str,
    target_order_code: str,
    cutline_start_time: datetime,
    include_plan_id: bool = True,
    warning_id: str | None = None,
) -> AlgorithmActiveCutlineEvent:
    _, _, source_wafer_size, source_wafer_spec, _ = product_identity(
        source_order_code
    )
    _, _, target_wafer_size, target_wafer_spec, _ = product_identity(
        target_order_code
    )
    return AlgorithmActiveCutlineEvent(
        event_id=f"CUT-{plan_id}-{machine_code}",
        plan_id=plan_id if include_plan_id else None,
        warning_id=(
            warning_id
            or plan_id.replace("PLAN-", "WARNING-", 1)
        )
        if include_plan_id
        else None,
        machine_code=machine_code,
        source_order_code=source_order_code,
        target_order_code=target_order_code,
        workshop_code=WORKSHOP,
        source_buffer_code=SOURCE_BUFFER,
        target_buffer_code=WARNING_BUFFER,
        upstream_process_code=CUT_PROCESS,
        downstream_process_code=DOWNSTREAM_PROCESS,
        source_wafer_size=source_wafer_size,
        source_wafer_spec=source_wafer_spec,
        target_wafer_size=target_wafer_size,
        target_wafer_spec=target_wafer_spec,
        cutline_start_time=cutline_start_time,
        negative_start_time=None,
        status="active",
        contribution_capacity=12.0,
        warning_type="stockout",
        process_code=CUT_PROCESS,
        warning_buffer_code=WARNING_BUFFER,
        warning_upstream_process_code=CUT_PROCESS,
        warning_downstream_process_code=DOWNSTREAM_PROCESS,
        is_recommended_candidate=True,
    )


def make_interval_result(
    order_code: str,
    buffer_code: str,
    *,
    workshop_code: str = WORKSHOP,
    upstream_process_code: str = CUT_PROCESS,
    downstream_process_code: str = DOWNSTREAM_PROCESS,
    net_consumption_rate: float = 5.0,
) -> AlgorithmIntervalNetRateResult:
    _, _, wafer_size, wafer_spec, _ = product_identity(order_code)
    return AlgorithmIntervalNetRateResult(
        main_id=f"MAIN-{buffer_code}",
        buffer_code=buffer_code,
        buffer_codes=[buffer_code],
        order_code=order_code,
        wafer_size=wafer_size,
        wafer_spec=wafer_spec,
        workshop_code=workshop_code,
        upstream_process_code=upstream_process_code,
        downstream_process_code=downstream_process_code,
        current_quantity=100.0,
        upstream_output_rate=5.0,
        downstream_input_rate=10.0,
        net_consumption_rate=net_consumption_rate,
    )


def make_snapshot(
    *,
    pending_plans: list[PendingCutlinePlan],
    history: list[AlgorithmAgvRelation] | None = None,
    current_orders: dict[str, str | None] | None = None,
    statuses: dict[str, str] | None = None,
    active_events: list[AlgorithmActiveCutlineEvent] | None = None,
    current_time: datetime = NOW,
) -> AlgorithmSnapshot:
    runtime_orders = current_orders or {
        "M1": SOURCE_ORDER,
        "M2": MONITORED_ORDER,
        "M3": SOURCE_ORDER,
        "M-W2": MONITORED_ORDER,
        "M-POTHER": MONITORED_ORDER,
    }
    runtime_statuses = statuses or {}
    machine_processes = {
        "M1": CUT_PROCESS,
        "M2": CUT_PROCESS,
        "M3": CUT_PROCESS,
        "M-W2": "P-CUT-W2",
        "M-POTHER": OTHER_PROCESS,
    }
    machine_workshops = {
        "M1": WORKSHOP,
        "M2": WORKSHOP,
        "M3": WORKSHOP,
        "M-W2": OTHER_WORKSHOP,
        "M-POTHER": WORKSHOP,
    }
    binding_history = history or []
    latest_by_machine: dict[str, AlgorithmAgvRelation] = {}
    for relation in binding_history:
        previous = latest_by_machine.get(relation.machine_code)
        if previous is None or previous.binding_time < relation.binding_time:
            latest_by_machine[relation.machine_code] = relation
    for plan in pending_plans:
        for baseline in plan.baseline_machine_bindings:
            if baseline.machine_code not in latest_by_machine:
                latest_by_machine[baseline.machine_code] = make_agv_binding(
                    baseline.machine_code,
                    baseline.order_code,
                    baseline.observed_at,
                    previous_product_name=None,
                )

    return AlgorithmSnapshot(
        current_time=current_time,
        workshops=[
            AlgorithmWorkshop(workshop_code=WORKSHOP, workshop_name="W1"),
            AlgorithmWorkshop(
                workshop_code=OTHER_WORKSHOP,
                workshop_name="W2",
            ),
        ],
        machine_runtimes=[
            AlgorithmMachineRuntime(
                machine_code=machine_code,
                status=runtime_statuses.get(machine_code, "running"),
                current_order_code=order_code,
                tangent_time=None,
                input_quantity_30m=10.0,
                output_quantity_30m=10.0,
                out_time=current_time,
            )
            for machine_code, order_code in runtime_orders.items()
        ],
        machine_masters=[
            AlgorithmMachineMaster(
                machine_code=machine_code,
                machine_name=f"Machine {machine_code}",
                process_code=process_code,
                process_name=process_code,
            )
            for machine_code, process_code in machine_processes.items()
        ],
        machine_product_capacities=[
            AlgorithmMachineProductCapacity(
                machine_code=machine_code,
                product_code=product_code,
                proc_seconds=30.0,
                actual_capacity=120.0,
            )
            for machine_code in machine_processes
            for product_code in (
                MONITORED_PRODUCT,
                SOURCE_PRODUCT,
                ALTERNATE_PRODUCT,
            )
        ],
        orders=[make_order(order_code) for order_code in all_order_codes()],
        products=[
            make_product(order_code) for order_code in all_order_codes()
        ],
        process_routes=[
            make_route(CUT_PROCESS, WORKSHOP),
            make_route(OTHER_PROCESS, WORKSHOP),
            make_route("P-CUT-W2", OTHER_WORKSHOP),
        ],
        buffer_masters=[
            make_buffer(WARNING_BUFFER),
            make_buffer(SOURCE_BUFFER),
            make_buffer(ALTERNATE_BUFFER),
        ],
        buffer_process_relations=[
            make_buffer_relation(WARNING_BUFFER),
            make_buffer_relation(SOURCE_BUFFER),
            make_buffer_relation(ALTERNATE_BUFFER),
        ],
        buffer_order_inventories=[
            AlgorithmBufferOrderInventory(
                main_id=f"MAIN-{buffer_code}",
                buffer_code=buffer_code,
                order_code=order_code,
                current_quantity=100.0,
            )
            for buffer_code, order_code in (
                (WARNING_BUFFER, MONITORED_ORDER),
                (SOURCE_BUFFER, SOURCE_ORDER),
                (ALTERNATE_BUFFER, ALTERNATE_ORDER),
            )
        ],
        agv_relations=list(latest_by_machine.values()),
        pending_cutline_plans=pending_plans,
        agv_binding_history=binding_history,
        active_cutline_events=active_events or [],
        config=AlgorithmConfig(),
    )


def make_order(order_code: str) -> AlgorithmOrder:
    product_code, product_name, _, _, _ = product_identity(order_code)
    workshop_code = OTHER_WORKSHOP if order_code == "O-W2" else WORKSHOP
    return AlgorithmOrder(
        order_code=order_code,
        order_status="running",
        product_code=product_code,
        product_name=product_name,
        workshop_code=workshop_code,
        workshop_name=workshop_code,
        total_quantity=1000.0,
        produced_quantity=100.0,
        piece_source="SOURCE-A",
        estimated_yield="A",
    )


def make_product(order_code: str) -> AlgorithmProduct:
    product_code, product_name, wafer_size, _, source_grade = (
        product_identity(order_code)
    )
    return AlgorithmProduct(
        product_code=product_code,
        product_name=product_name,
        wafer_size=wafer_size,
        source_grade=source_grade,
        material_code=f"MAT-{product_code}",
        material_name=f"Material {product_code}",
    )


def make_route(
    process_code: str,
    workshop_code: str,
) -> AlgorithmProcessRoute:
    return AlgorithmProcessRoute(
        process_code=process_code,
        process_name=process_code,
        sequence=2,
        cache_type="buffer",
        workshop_code=workshop_code,
        workshop_name=workshop_code,
        loop_code=f"LOOP-{workshop_code}",
        loop_name=f"Loop {workshop_code}",
        upstream_process_code="P-UP",
        upstream_process_name="P-UP",
        downstream_process_code=DOWNSTREAM_PROCESS,
        downstream_process_name=DOWNSTREAM_PROCESS,
    )


def make_buffer(buffer_code: str) -> AlgorithmBufferMaster:
    return AlgorithmBufferMaster(
        buffer_code=buffer_code,
        buffer_name=buffer_code,
        buffer_type="material",
        buffer_type_title="Material",
        max_capacity=1000.0,
        safety_low=10.0,
        served_process_codes=[CUT_PROCESS],
        served_process_names=[CUT_PROCESS],
        loop_code="LOOP-W1",
        loop_name="Loop W1",
    )


def make_buffer_relation(
    buffer_code: str,
) -> AlgorithmBufferProcessRelation:
    return AlgorithmBufferProcessRelation(
        buffer_code=buffer_code,
        workshop_code=WORKSHOP,
        upstream_process_code=CUT_PROCESS,
        downstream_process_code=DOWNSTREAM_PROCESS,
    )


def all_order_codes() -> tuple[str, ...]:
    return (
        MONITORED_ORDER,
        SOURCE_ORDER,
        ALTERNATE_ORDER,
        INCOMPATIBLE_ORDER,
    )


def product_identity(
    order_code: str,
) -> tuple[str, str, str, str, str]:
    identities = {
        MONITORED_ORDER: (
            MONITORED_PRODUCT,
            MONITORED_PRODUCT_NAME,
            "210",
            "M10-P",
            "A-",
        ),
        SOURCE_ORDER: (
            SOURCE_PRODUCT,
            SOURCE_PRODUCT_NAME,
            "210",
            "M10-P",
            "A",
        ),
        ALTERNATE_ORDER: (
            ALTERNATE_PRODUCT,
            ALTERNATE_PRODUCT_NAME,
            "210",
            "M10-P",
            "A-",
        ),
        INCOMPATIBLE_ORDER: (
            INCOMPATIBLE_PRODUCT,
            INCOMPATIBLE_PRODUCT_NAME,
            "220",
            "M12-P",
            "A-",
        ),
    }
    return identities[order_code]


def product_code_for_name(product_name: str | None) -> str | None:
    if product_name is None or not product_name.strip():
        return None
    product_codes_by_name = {
        MONITORED_PRODUCT_NAME: MONITORED_PRODUCT,
        SOURCE_PRODUCT_NAME: SOURCE_PRODUCT,
        ALTERNATE_PRODUCT_NAME: ALTERNATE_PRODUCT,
        INCOMPATIBLE_PRODUCT_NAME: INCOMPATIBLE_PRODUCT,
    }
    return product_codes_by_name[product_name]
