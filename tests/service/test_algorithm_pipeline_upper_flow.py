from datetime import datetime

import pytest

from app.core.mixing_trace.mixing_trace_calculator import MixingTraceCalculator
from app.core.net_rate.net_rate_calculator import NetRateCalculationError
from app.core.return_judge.return_evaluator import ReturnEvaluator
from app.core.silk_screen.order_transition_planner import (
    SilkScreenOrderTransitionPlanner,
)
from app.schemas.common_schema import (
    AlgorithmAgvRelation,
    AlgorithmBufferMaster,
    AlgorithmBufferOrderInventory,
    AlgorithmBufferProcessRelation,
    AlgorithmLine,
    AlgorithmMachineLineRelation,
    AlgorithmMachineMaster,
    AlgorithmMachineRuntime,
    AlgorithmOrder,
    AlgorithmProduct,
)
from app.schemas.request_schema import AlgorithmSnapshot
from app.schemas.result_schema import (
    AlgorithmBufferOverflowTimeResult,
    AlgorithmEvaluateResult,
    AlgorithmIntervalNetRateResult,
    AlgorithmMixingTraceBatchResult,
)
from app.service.cutline_pipeline import CutlinePipeline


NOW = datetime(2026, 7, 16, 8, 30)


@pytest.fixture(autouse=True)
def _isolate_remaining_algorithm_stages(monkeypatch):
    monkeypatch.setattr(
        ReturnEvaluator,
        "evaluate_algorithm",
        lambda self, **kwargs: [],
    )
    monkeypatch.setattr(
        SilkScreenOrderTransitionPlanner,
        "evaluate",
        lambda self, **kwargs: [],
    )
    monkeypatch.setattr(
        MixingTraceCalculator,
        "calculate_for_decision",
        lambda self, **kwargs: AlgorithmMixingTraceBatchResult(),
    )


def _order(order_code: str) -> AlgorithmOrder:
    return AlgorithmOrder(
        order_code=order_code,
        order_name=order_code,
        order_status="RUNNING",
        product_code="PROD-001",
        product_name="Product 001",
        workshop_code="S1",
        workshop_name="Workshop 1",
        total_quantity=10000,
        produced_quantity=1000,
        piece_source="A",
        estimated_yield="99%",
    )


def _runtime(
    machine_code: str,
    order_code: str,
    *,
    input_quantity_30m: float = 0,
    output_quantity_30m: float = 0,
) -> AlgorithmMachineRuntime:
    return AlgorithmMachineRuntime(
        machine_code=machine_code,
        status="running",
        current_order_code=order_code,
        tangent_time=None,
        input_quantity_30m=input_quantity_30m,
        output_quantity_30m=output_quantity_30m,
        period_quantity_30m=0,
        out_time=None,
    )


def _buffer(buffer_code: str) -> AlgorithmBufferMaster:
    return AlgorithmBufferMaster(
        buffer_code=buffer_code,
        buffer_name=buffer_code,
        buffer_type="LINE",
        buffer_type_title="Line buffer",
        max_capacity=1000,
        safety_low=0,
        served_process_codes=["ZR", "PK"],
        served_process_names=["Upstream", "Downstream"],
        loop_code="LOOP-1",
        loop_name="Loop 1",
    )


def _snapshot(
    *,
    stockout_minutes: float = 30,
    overflow_minutes: float = 30,
    warning_lead_minutes: float = 30,
) -> AlgorithmSnapshot:
    machine_codes = (
        ("ZR-STOCK", "ZR"),
        ("PK-STOCK", "PK"),
        ("ZR-OVER", "ZR"),
        ("PK-OVER", "PK"),
    )
    return AlgorithmSnapshot(
        current_time=NOW,
        workshops=[],
        lines=[
            AlgorithmLine(
                line_code="LINE-N-S1",
                line_name="N line",
                wafer_spec="N",
                workshop_code="S1",
                workshop_name="Workshop 1",
            )
        ],
        machine_lines=[
            AlgorithmMachineLineRelation(
                machine_code=machine_code,
                line_code="LINE-N-S1",
            )
            for machine_code, _ in machine_codes
        ],
        machine_runtimes=[
            _runtime("ZR-STOCK", "ORD-STOCK", output_quantity_30m=50),
            _runtime("PK-STOCK", "ORD-STOCK", input_quantity_30m=150),
            _runtime("ZR-OVER", "ORD-OVER", output_quantity_30m=150),
            _runtime("PK-OVER", "ORD-OVER", input_quantity_30m=50),
        ],
        machine_masters=[
            AlgorithmMachineMaster(
                machine_code=machine_code,
                machine_name=machine_code,
                process_code=process_code,
                process_name=process_code,
            )
            for machine_code, process_code in machine_codes
        ],
        machine_product_capacities=[],
        orders=[_order("ORD-STOCK"), _order("ORD-OVER")],
        products=[
            AlgorithmProduct(
                product_code="PROD-001",
                product_name="Product 001",
                wafer_size="182",
                source_grade="A",
                material_code="MAT-001",
                material_name="Material 001",
            )
        ],
        process_routes=[],
        buffer_masters=[_buffer("BUF-STOCK"), _buffer("BUF-OVER")],
        buffer_process_relations=[
            AlgorithmBufferProcessRelation(
                buffer_code=buffer_code,
                workshop_code="S1",
                upstream_process_code="ZR",
                downstream_process_code="PK",
            )
            for buffer_code in ("BUF-STOCK", "BUF-OVER")
        ],
        buffer_order_inventories=[
            AlgorithmBufferOrderInventory(
                main_id="MAIN-BUF-STOCK",
                buffer_code="BUF-STOCK",
                order_code="ORD-STOCK",
                current_quantity=200 * stockout_minutes / 60,
            ),
            AlgorithmBufferOrderInventory(
                main_id="MAIN-BUF-OVER",
                buffer_code="BUF-OVER",
                order_code="ORD-OVER",
                current_quantity=1000 - 200 * overflow_minutes / 60,
            ),
        ],
        agv_relations=[
            AlgorithmAgvRelation(
                machine_code=machine_code,
                machine_name=machine_code,
                order_code=order_code,
                order_name=order_code,
                wafer_spec="N",
                binding_time=NOW,
            )
            for machine_code, order_code in (
                ("ZR-STOCK", "ORD-STOCK"),
                ("PK-STOCK", "ORD-STOCK"),
                ("ZR-OVER", "ORD-OVER"),
                ("PK-OVER", "ORD-OVER"),
            )
        ],
        config={
            "stockout_warning_lead_minutes": warning_lead_minutes,
            "overflow_warning_lead_minutes": warning_lead_minutes,
        },
    )


def _by_buffer(results):
    return {result.buffer_code: result for result in results}


def test_evaluate_algorithm_calls_public_components_in_required_order(monkeypatch):
    pipeline = CutlinePipeline()
    snapshot = _snapshot()
    calls = []

    monkeypatch.setattr(
        pipeline._net_rate,
        "calculate",
        lambda value: calls.append(("net_rate", value)) or [],
    )
    monkeypatch.setattr(
        pipeline._net_rate,
        "_calculate_algorithm_snapshot",
        lambda value: pytest.fail("private net-rate method must not be called"),
    )
    monkeypatch.setattr(
        pipeline._depletion,
        "calculate_algorithm",
        lambda values: calls.append(("depletion", values)) or [],
    )
    monkeypatch.setattr(
        pipeline._overflow_time,
        "calculate_algorithm",
        lambda value, rates: calls.append(("overflow_time", value, rates)) or [],
    )
    monkeypatch.setattr(
        pipeline._stockout,
        "evaluate_algorithm",
        lambda value, results: calls.append(("stockout", value, results)) or [],
    )
    monkeypatch.setattr(
        pipeline._overflow,
        "evaluate_algorithm",
        lambda value, results: calls.append(("overflow", value, results)) or [],
    )

    pipeline.evaluate_algorithm(snapshot)

    assert [call[0] for call in calls] == [
        "net_rate",
        "depletion",
        "overflow_time",
        "stockout",
        "overflow",
    ]


def test_evaluate_algorithm_returns_upper_flow_result_with_snapshot_time():
    snapshot = _snapshot()

    result = CutlinePipeline().evaluate_algorithm(snapshot)

    assert isinstance(result, AlgorithmEvaluateResult)
    assert result.calculation_time == snapshot.current_time


def test_evaluate_algorithm_calculates_interval_rates_and_depletion():
    result = CutlinePipeline().evaluate_algorithm(_snapshot())
    rates = _by_buffer(result.net_rate_results)
    depletions = _by_buffer(result.depletion_results)

    stock_rate = rates["BUF-STOCK"]
    assert isinstance(stock_rate, AlgorithmIntervalNetRateResult)
    assert stock_rate.order_code == "ORD-STOCK"
    assert stock_rate.current_quantity == 100
    assert stock_rate.upstream_output_rate == 100
    assert stock_rate.downstream_input_rate == 300
    assert stock_rate.net_consumption_rate == 200

    stock_depletion = depletions["BUF-STOCK"]
    assert stock_depletion.order_code == stock_rate.order_code
    assert stock_depletion.current_quantity == stock_rate.current_quantity
    assert stock_depletion.net_consumption_rate == stock_rate.net_consumption_rate
    assert stock_depletion.depletion_minutes == 30


def test_evaluate_algorithm_calculates_physical_buffer_overflow_with_details():
    result = CutlinePipeline().evaluate_algorithm(_snapshot())
    overflow = _by_buffer(result.overflow_time_results)["BUF-OVER"]

    assert isinstance(overflow, AlgorithmBufferOverflowTimeResult)
    assert overflow.total_inventory == 900
    assert overflow.max_capacity == 1000
    assert overflow.remaining_capacity == 100
    assert overflow.buffer_growth_rate == 200
    assert overflow.overflow_minutes == 30
    assert len(overflow.order_growth_details) == 1
    assert overflow.order_growth_details[0].order_code == "ORD-OVER"
    assert overflow.order_growth_details[0].growth_rate == 200


def test_evaluate_algorithm_emits_only_warnings_within_configured_lead():
    result = CutlinePipeline().evaluate_algorithm(_snapshot())

    assert [warning.buffer_code for warning in result.stockout_warnings] == [
        "BUF-STOCK"
    ]
    assert result.stockout_warnings[0].depletion_minutes == 30
    assert [warning.buffer_code for warning in result.overflow_warnings] == [
        "BUF-OVER"
    ]
    assert result.overflow_warnings[0].overflow_minutes == 30
    assert [
        detail.order_code
        for detail in result.overflow_warnings[0].order_growth_details
    ] == ["ORD-OVER"]


def test_evaluate_algorithm_keeps_predictions_when_warnings_are_outside_lead():
    result = CutlinePipeline().evaluate_algorithm(
        _snapshot(stockout_minutes=60, overflow_minutes=60)
    )

    assert len(result.net_rate_results) == 2
    assert len(result.depletion_results) == 2
    assert len(result.overflow_time_results) == 2
    assert result.stockout_warnings == []
    assert result.overflow_warnings == []


def test_evaluate_algorithm_keeps_explicitly_stubbed_lower_flow_fields_empty():
    result = CutlinePipeline().evaluate_algorithm(_snapshot())

    assert result.return_results == []
    assert result.silk_screen_results == []
    assert result.mixing_trace_records == []
    assert result.mixing_trace_failures == []
    assert result.errors == []


def test_evaluate_algorithm_does_not_mutate_snapshot():
    snapshot = _snapshot()
    before = snapshot.model_dump()

    CutlinePipeline().evaluate_algorithm(snapshot)

    assert snapshot.model_dump() == before


def test_evaluate_algorithm_propagates_core_calculation_errors():
    snapshot = _snapshot()
    snapshot.products = []

    with pytest.raises(NetRateCalculationError, match="PROD-001.*product"):
        CutlinePipeline().evaluate_algorithm(snapshot)
