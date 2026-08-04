from app.service.cutline_pipeline import CutlinePipeline
from tests.fixtures.v3_full_route_factory import (
    MULTILAYER_BUFFER_CODES,
    MULTILAYER_MAIN_ID,
    TARGET_ORDER_CODE,
    build_base_request_payload,
    build_multilayer_buffer_payload,
    build_multilayer_stockout_payload,
)
from tests.integration.helpers import snapshot


def test_v3_multilayer_buffer_is_grouped_once_across_the_full_upper_flow():
    result = CutlinePipeline().evaluate_algorithm(
        snapshot(build_multilayer_buffer_payload())
    )

    target_rate = next(
        item
        for item in result.net_rate_results
        if item.main_id == MULTILAYER_MAIN_ID
        and item.order_code == TARGET_ORDER_CODE
    )
    assert target_rate.current_quantity == 10800
    assert target_rate.buffer_code == MULTILAYER_BUFFER_CODES[0]
    assert target_rate.buffer_codes == list(MULTILAYER_BUFFER_CODES)
    assert sum(
        item.main_id == MULTILAYER_MAIN_ID
        and item.order_code == TARGET_ORDER_CODE
        for item in result.net_rate_results
    ) == 1

    target_depletion = next(
        item
        for item in result.depletion_results
        if item.main_id == MULTILAYER_MAIN_ID
        and item.order_code == TARGET_ORDER_CODE
    )
    assert target_depletion.current_quantity == 10800
    assert target_depletion.buffer_codes == list(MULTILAYER_BUFFER_CODES)

    overflow = next(
        item
        for item in result.overflow_time_results
        if item.main_id == MULTILAYER_MAIN_ID
    )
    assert overflow.buffer_code == MULTILAYER_BUFFER_CODES[0]
    assert overflow.buffer_codes == list(MULTILAYER_BUFFER_CODES)
    assert overflow.max_capacity == 30000
    assert overflow.total_inventory == 10800
    assert sum(
        item.main_id == MULTILAYER_MAIN_ID
        for item in result.overflow_time_results
    ) == 1


def test_v3_buffer_masters_without_realtime_generate_no_upper_flow_results():
    payload = build_base_request_payload()
    payload["buffer_realtime"] = []

    result = CutlinePipeline().evaluate_algorithm(snapshot(payload))

    assert result.net_rate_results == []
    assert result.depletion_results == []
    assert result.overflow_time_results == []
    assert result.stockout_warnings == []
    assert result.overflow_warnings == []


def test_v3_multilayer_stockout_creates_one_plan_without_activity_event():
    result = CutlinePipeline().evaluate_algorithm(
        snapshot(build_multilayer_stockout_payload())
    )

    assert len(result.stockout_warnings) == 1
    warning = result.stockout_warnings[0]
    assert warning.main_id == MULTILAYER_MAIN_ID
    assert warning.buffer_code == MULTILAYER_BUFFER_CODES[0]
    assert warning.buffer_codes == list(MULTILAYER_BUFFER_CODES)
    assert warning.current_quantity == 100
    assert warning.net_consumption_rate == 400
    assert warning.depletion_minutes == 15

    assert len(result.cutline_decisions) == 1
    plan = result.cutline_decisions[0].plan
    assert plan is not None
    assert plan.buffer_code == MULTILAYER_BUFFER_CODES[0]
    assert [item.machine_code for item in plan.selected_machines] == ["EA004"]
    assert result.new_active_cutline_events == []
