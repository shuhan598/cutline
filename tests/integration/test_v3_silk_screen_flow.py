from tests.fixtures.v3_full_route_factory import (
    build_silk_not_ready_payload,
    build_silk_prepare_payload,
)
from tests.integration.helpers import evaluate, snapshot
from app.service.cutline_pipeline import CutlinePipeline


def _internal_result(payload):
    return CutlinePipeline().evaluate_algorithm(snapshot(payload))


def test_v3_silk_not_ready_returns_compact_customer_clearance_result():
    payload = build_silk_not_ready_payload()
    response = evaluate(payload)
    internal = _internal_result(payload).silk_screen_results[0]

    assert len(response.silk_screen_results) == 1
    result = response.silk_screen_results[0]
    assert result.workshop_code == "S2"
    assert result.current_order_code == "ORD-S2-001"
    assert result.machine_codes == ["EA021"]
    assert result.prepare_clearance is False
    assert result.reason == "not_yet_time_to_prepare"
    assert result.calculation_time == response.calculation_time
    assert "process_code" not in result.model_dump()
    assert "next_order_code" not in result.model_dump()

    assert internal.process_code == internal.process_name == "丝网"
    assert internal.current_order_output_rate == 200
    assert internal.estimated_finish_time is not None
    assert internal.clearance_prepare_time is not None


def test_v3_silk_prepare_uses_running_output_only_without_exposing_next_order():
    payload = build_silk_prepare_payload()
    response = evaluate(payload)
    internal = _internal_result(payload).silk_screen_results[0]

    result = response.silk_screen_results[0]
    assert result.machine_codes == ["EA021"]
    assert internal.current_order_output_rate == 100
    assert internal.remaining_quantity == 25
    assert result.prepare_clearance is True
    assert result.reason == "clearance_preparation_required"
    assert internal.next_order_code is None
    assert "next_order_code" not in result.model_dump()
    assert response.errors == []
