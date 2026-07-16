from datetime import datetime

from app.schemas.common_schema import AlgorithmConfig
from app.schemas.result_schema import (
    AlgorithmBufferOverflowTimeResult,
    AlgorithmIntervalNetRateResult,
    AlgorithmOrderGrowthDetail,
    AlgorithmOverflowCandidateMachine,
    AlgorithmOverflowCandidateResult,
    AlgorithmOverflowTargetOption,
    AlgorithmOverflowWarningResult,
    AlgorithmStockoutCandidateMachine,
    AlgorithmStockoutCandidateResult,
    AlgorithmStockoutWarningResult,
)
from tests.core.candidate_machine.helpers import snapshot


CURRENT_TIME = datetime(2026, 7, 15, 8, 30)


def interval(
    *,
    buffer_code: str,
    order_code: str,
    downstream_process_code: str,
    wafer_size: str = "182",
    wafer_spec: str = "N",
    workshop_code: str = "S1",
    upstream_process_code: str = "P01",
    current_quantity: float = 100000,
    net_consumption_rate: float = 0,
) -> AlgorithmIntervalNetRateResult:
    upstream_output_rate = 10000
    return AlgorithmIntervalNetRateResult(
        buffer_code=buffer_code,
        order_code=order_code,
        wafer_size=wafer_size,
        wafer_spec=wafer_spec,
        workshop_code=workshop_code,
        upstream_process_code=upstream_process_code,
        downstream_process_code=downstream_process_code,
        current_quantity=current_quantity,
        upstream_output_rate=upstream_output_rate,
        downstream_input_rate=(
            upstream_output_rate + net_consumption_rate
        ),
        net_consumption_rate=net_consumption_rate,
    )


def overflow_state(
    buffer_code: str,
    *,
    total_inventory: float = 0,
    max_capacity: float = 1000000,
    buffer_growth_rate: float = 0,
    downstream_process_code: str = "P02",
) -> AlgorithmBufferOverflowTimeResult:
    remaining_capacity = max_capacity - total_inventory
    if total_inventory >= max_capacity:
        overflow_minutes = 0
    elif buffer_growth_rate > 0:
        overflow_minutes = remaining_capacity / buffer_growth_rate * 60
    else:
        overflow_minutes = None
    return AlgorithmBufferOverflowTimeResult(
        buffer_code=buffer_code,
        workshop_code="S1",
        upstream_process_code="P01",
        downstream_process_code=downstream_process_code,
        max_capacity=max_capacity,
        total_inventory=total_inventory,
        remaining_capacity=remaining_capacity,
        buffer_growth_rate=buffer_growth_rate,
        overflow_minutes=overflow_minutes,
        order_growth_details=[],
    )


def stockout_warning(
    *,
    net_consumption_rate: float = 10000,
    stockout_warning_lead_minutes: float = 30,
    buffer_code: str = "BUF-TARGET",
) -> AlgorithmStockoutWarningResult:
    return AlgorithmStockoutWarningResult(
        warning_time=CURRENT_TIME,
        buffer_code=buffer_code,
        order_code="ORD-TARGET",
        wafer_size="182",
        wafer_spec="N",
        workshop_code="S1",
        upstream_process_code="P01",
        downstream_process_code="P02",
        current_quantity=1000,
        upstream_output_rate=1000,
        downstream_input_rate=1000 + net_consumption_rate,
        net_consumption_rate=net_consumption_rate,
        depletion_minutes=6,
        stockout_warning_lead_minutes=stockout_warning_lead_minutes,
    )


def stockout_candidate(
    machine_code: str,
    contribution_capacity: float,
    *,
    source_order_code: str = "ORD-SOURCE",
    idle_rate: float = 0.8,
) -> AlgorithmStockoutCandidateMachine:
    return AlgorithmStockoutCandidateMachine(
        machine_code=machine_code,
        machine_name=machine_code,
        status="running",
        workshop_code="S1",
        process_code="P01",
        process_name="制绒",
        current_order_code=source_order_code,
        current_product_code=f"PROD-{source_order_code}",
        current_wafer_size="182",
        current_wafer_spec="N",
        current_source_grade="A",
        target_order_code="ORD-TARGET",
        target_product_code="PROD-TARGET",
        target_wafer_size="182",
        target_wafer_spec="N",
        target_source_grade="A",
        input_quantity_30m=max(contribution_capacity / 2, 1),
        output_quantity_30m=contribution_capacity / 2,
        current_output_rate_per_hour=contribution_capacity,
        contribution_capacity=contribution_capacity,
        utilization_rate=1 - idle_rate,
        idle_rate=idle_rate,
    )


def stockout_candidates(
    *candidates: AlgorithmStockoutCandidateMachine,
    capacity_gap: float = 10000,
) -> AlgorithmStockoutCandidateResult:
    return AlgorithmStockoutCandidateResult(
        workshop_code="S1",
        buffer_code="BUF-TARGET",
        warning_order_code="ORD-TARGET",
        target_product_code="PROD-TARGET",
        target_wafer_size="182",
        target_wafer_spec="N",
        target_source_grade="A",
        upstream_process_code="P01",
        downstream_process_code="P02",
        capacity_gap=capacity_gap,
        candidates=list(candidates),
    )


def default_stockout_intervals(
    *,
    source_net_rate: float = -20000,
    source_quantity: float = 100000,
    source_buffer_code: str = "BUF-SOURCE",
) -> list[AlgorithmIntervalNetRateResult]:
    return [
        interval(
            buffer_code=source_buffer_code,
            order_code="ORD-SOURCE",
            downstream_process_code="P09",
            current_quantity=source_quantity,
            net_consumption_rate=source_net_rate,
        ),
        interval(
            buffer_code="BUF-TARGET",
            order_code="ORD-TARGET",
            downstream_process_code="P02",
            current_quantity=1000,
            net_consumption_rate=10000,
        ),
    ]


def overflow_detail(
    order_code: str,
    *,
    growth_rate: float,
) -> AlgorithmOrderGrowthDetail:
    return AlgorithmOrderGrowthDetail(
        order_code=order_code,
        wafer_size="182",
        wafer_spec="N",
        current_quantity=1000,
        upstream_output_rate=10000,
        downstream_input_rate=10000 - growth_rate,
        net_consumption_rate=-growth_rate,
        growth_rate=growth_rate,
    )


def overflow_warning(
    *,
    buffer_growth_rate: float = 10000,
    total_inventory: float = 0,
    max_capacity: float = 4000,
    overflow_warning_lead_minutes: float = 30,
) -> AlgorithmOverflowWarningResult:
    overflow_minutes = (
        0
        if total_inventory >= max_capacity
        else (max_capacity - total_inventory) / buffer_growth_rate * 60
    )
    return AlgorithmOverflowWarningResult(
        warning_time=CURRENT_TIME,
        buffer_code="BUF-OVERFLOW",
        workshop_code="S1",
        upstream_process_code="P01",
        downstream_process_code="P02",
        max_capacity=max_capacity,
        total_inventory=total_inventory,
        remaining_capacity=max_capacity - total_inventory,
        buffer_growth_rate=buffer_growth_rate,
        overflow_minutes=overflow_minutes,
        overflow_warning_lead_minutes=overflow_warning_lead_minutes,
        order_growth_details=[
            overflow_detail("ORD-SOURCE", growth_rate=buffer_growth_rate),
            overflow_detail("ORD-TARGET", growth_rate=-1000),
        ],
    )


def overflow_target(
    order_code: str = "ORD-TARGET",
    *,
    buffer_code: str | None = "BUF-TARGET",
    capacity_gap: float = 1000,
    downstream_process_code: str | None = "P03",
) -> AlgorithmOverflowTargetOption:
    return AlgorithmOverflowTargetOption(
        target_order_code=order_code,
        target_product_code=f"PROD-{order_code}",
        target_wafer_size="182",
        target_wafer_spec="N",
        target_source_grade="A",
        target_buffer_code=buffer_code,
        target_workshop_code="S1" if buffer_code is not None else None,
        target_upstream_process_code="P01" if buffer_code is not None else None,
        target_downstream_process_code=downstream_process_code,
        capacity_gap=capacity_gap,
        estimated_contribution_capacity=capacity_gap,
    )


def overflow_candidate(
    machine_code: str,
    reduced_capacity: float,
    *target_options: AlgorithmOverflowTargetOption,
    utilization_rate: float = 0.9,
) -> AlgorithmOverflowCandidateMachine:
    return AlgorithmOverflowCandidateMachine(
        machine_code=machine_code,
        machine_name=machine_code,
        status="running",
        workshop_code="S1",
        process_code="P01",
        process_name="制绒",
        current_order_code="ORD-SOURCE",
        current_product_code="PROD-SOURCE",
        current_wafer_size="182",
        current_wafer_spec="N",
        current_source_grade="A",
        input_quantity_30m=max(reduced_capacity / 2, 1),
        output_quantity_30m=reduced_capacity / 2,
        current_output_rate_per_hour=reduced_capacity,
        reduced_capacity=reduced_capacity,
        utilization_rate=utilization_rate,
        idle_rate=1 - utilization_rate,
        target_options=list(target_options) or [overflow_target()],
    )


def overflow_candidates(
    *candidates: AlgorithmOverflowCandidateMachine,
    source_order_code: str = "ORD-SOURCE",
) -> AlgorithmOverflowCandidateResult:
    return AlgorithmOverflowCandidateResult(
        workshop_code="S1",
        buffer_code="BUF-OVERFLOW",
        upstream_process_code="P01",
        downstream_process_code="P02",
        source_order_code=source_order_code,
        source_product_code="PROD-SOURCE",
        source_wafer_size="182",
        source_wafer_spec="N",
        source_source_grade="A",
        source_growth_rate=10000,
        source_net_consumption_rate=-10000,
        candidates=list(candidates),
    )


def default_overflow_intervals(
    *,
    source_net_rate: float = -10000,
    source_quantity: float = 100000,
    target_net_rate: float = 1000,
) -> list[AlgorithmIntervalNetRateResult]:
    return [
        interval(
            buffer_code="BUF-OVERFLOW",
            order_code="ORD-SOURCE",
            downstream_process_code="P02",
            current_quantity=source_quantity,
            net_consumption_rate=source_net_rate,
        ),
        interval(
            buffer_code="BUF-TARGET",
            order_code="ORD-TARGET",
            downstream_process_code="P03",
            current_quantity=1000,
            net_consumption_rate=target_net_rate,
        ),
    ]


def default_overflow_states(
    *,
    source_total_inventory: float = 0,
    source_max_capacity: float = 4000,
    source_growth_rate: float = 10000,
    target_total_inventory: float = 0,
    target_max_capacity: float = 1000000,
    target_growth_rate: float = 0,
) -> list[AlgorithmBufferOverflowTimeResult]:
    return [
        overflow_state(
            "BUF-OVERFLOW",
            total_inventory=source_total_inventory,
            max_capacity=source_max_capacity,
            buffer_growth_rate=source_growth_rate,
        ),
        overflow_state(
            "BUF-TARGET",
            total_inventory=target_total_inventory,
            max_capacity=target_max_capacity,
            buffer_growth_rate=target_growth_rate,
            downstream_process_code="P03",
        ),
    ]


def algorithm_snapshot(
    *,
    stockout_warning_lead_minutes: float = 30,
    overflow_warning_lead_minutes: float = 30,
):
    value = snapshot()
    return value.model_copy(
        update={
            "config": AlgorithmConfig(
                stockout_warning_lead_minutes=(
                    stockout_warning_lead_minutes
                ),
                overflow_warning_lead_minutes=(
                    overflow_warning_lead_minutes
                ),
            )
        }
    )
