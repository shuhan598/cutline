from datetime import datetime

from app.schemas import common_schema
from app.schemas.request_schema import AlgorithmSnapshot
from app.schemas.result_schema import AlgorithmIntervalNetRateResult


CURRENT_TIME = datetime(2026, 7, 15, 10, 0)
CUTLINE_START_TIME = datetime(2026, 7, 15, 9, 0)


def algorithm_snapshot(
    *,
    current_time: datetime = CURRENT_TIME,
    active_cutline_events=None,
    stability_window_minutes: float = 20,
    stockout_warning_lead_minutes: float = 30,
    overflow_warning_lead_minutes: float = 30,
    silk_screen_clear_minutes: float = 30,
) -> AlgorithmSnapshot:
    return AlgorithmSnapshot(
        current_time=current_time,
        workshops=[],
        lines=[],
        machine_lines=[],
        machine_runtimes=[],
        machine_masters=[],
        machine_product_capacities=[],
        orders=[],
        products=[],
        process_routes=[],
        buffer_masters=[],
        buffer_process_relations=[],
        buffer_order_inventories=[],
        agv_relations=[],
        active_cutline_events=list(active_cutline_events or []),
        config=common_schema.AlgorithmConfig(
            stability_window_minutes=stability_window_minutes,
            stockout_warning_lead_minutes=stockout_warning_lead_minutes,
            overflow_warning_lead_minutes=overflow_warning_lead_minutes,
            silk_screen_clear_minutes=silk_screen_clear_minutes,
        ),
    )


def active_event(**updates):
    values = {
        "event_id": "EVENT-01",
        "plan_id": "PLAN-01",
        "machine_code": "MC-01",
        "source_order_code": "ORD-SOURCE",
        "target_order_code": "ORD-TARGET",
        "workshop_code": "WS-01",
        "source_buffer_code": "BUF-SOURCE",
        "target_buffer_code": "BUF-TARGET",
        "upstream_process_code": "P01",
        "downstream_process_code": "P02",
        "source_wafer_size": "182",
        "source_wafer_spec": "R",
        "target_wafer_size": "182",
        "target_wafer_spec": "N",
        "cutline_start_time": CUTLINE_START_TIME,
        "negative_start_time": None,
        "status": "active",
        "contribution_capacity": 8000,
        "warning_type": "stockout",
    }
    values.update(updates)
    return common_schema.AlgorithmActiveCutlineEvent(**values)


def interval(
    *,
    buffer_code: str = "BUF-TARGET",
    order_code: str = "ORD-TARGET",
    wafer_size: str = "182",
    wafer_spec: str = "N",
    workshop_code: str = "WS-01",
    upstream_process_code: str = "P01",
    downstream_process_code: str = "P02",
    current_quantity: float = 5000,
    net_consumption_rate: float = -4800,
) -> AlgorithmIntervalNetRateResult:
    upstream_output_rate = 10000
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
        current_quantity=current_quantity,
        upstream_output_rate=upstream_output_rate,
        downstream_input_rate=upstream_output_rate + net_consumption_rate,
        net_consumption_rate=net_consumption_rate,
    )
