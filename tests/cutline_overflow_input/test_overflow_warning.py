from pathlib import Path
from datetime import datetime

from app.adapters.mock_adapter import MockAdapter
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.prediction_time.overflow_time.overflow_time_calculator import (
    OverflowTimeCalculator,
)
from app.core.warning.overflow_warning import OverflowWarningEvaluator
from app.schemas.common_schema import (
    BufferInventoryItem,
    BufferSegment,
    CycleMaster,
    LineMaster,
    MachineMaster,
    MachineRuntimeStatus,
)
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import OverflowTimeResult


OVERFLOW_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_overflow_input.json"


def build_overflow_warnings():
    snapshot = MockAdapter().load(OVERFLOW_INPUT_PATH)
    net_rates = NetRateCalculator(RealtimeFirstRateStrategy()).calculate(snapshot)
    overflow_times = OverflowTimeCalculator().calculate(snapshot, net_rates)
    return OverflowWarningEvaluator().evaluate(snapshot, overflow_times), snapshot


def by_product(results):
    return {r.product_code: r for r in results}


def test_only_negative_net_rate_segments_produce_overflow_results():
    results, _ = build_overflow_warnings()
    products = {r.product_code for r in results}
    assert products == {"HG182T"}


def test_hg182t_overflow_triggers_at_thirty_minutes():
    result = by_product(build_overflow_warnings()[0])["HG182T"]
    assert result.warning_type == "overflow"
    assert result.warning_triggered is True
    assert result.reason == "overflow_time_within_lead_time"
    assert result.segment_inventory == 18000
    assert result.segment_capacity == 20000
    assert result.net_rate_per_hour == -4000
    assert result.overflow_minutes == 30


def test_overflow_warning_evaluator_triggers_from_overflow_time_result():
    snapshot = CutlineSnapshot(
        current_time=datetime(2026, 1, 1),
        config={"cutline_lead_minutes": 60},
    )
    overflow_time = OverflowTimeResult(
        buffer_code="BUF_ZR_PK",
        cycle_code="CYCLE_S2_A",
        cycle_name="S2 cycle A",
        workshop_code="S2",
        workshop_name="S2 workshop",
        product_code="HG182T",
        process_from="ZR",
        process_to="PK",
        segment_inventory=8000,
        segment_capacity=10000,
        net_rate_per_hour=-3000,
        overflow_minutes=40,
        cutline_lead_minutes=60,
    )

    result = OverflowWarningEvaluator().evaluate(snapshot, [overflow_time])[0]

    assert result.warning_type == "overflow"
    assert result.warning_triggered is True
    assert result.reason == "overflow_time_within_lead_time"
    assert result.segment_inventory == 8000
    assert result.segment_capacity == 10000
    assert result.net_rate_per_hour == -3000
    assert result.overflow_minutes == 40


def test_overflow_segment_inventory_aggregates_same_workshop_buffer_only():
    snapshot = CutlineSnapshot(
        current_time=datetime(2026, 1, 1),
        config={"cutline_lead_minutes": 30},
        cycle_masters=[
            CycleMaster(
                cycle_code="CYCLE_S2_A",
                cycle_name="S2 cycle A",
                workshop_code="S2",
                workshop_name="S2 workshop",
            ),
            CycleMaster(
                cycle_code="CYCLE_S2_B",
                cycle_name="S2 cycle B",
                workshop_code="s2 ",
                workshop_name="S2 workshop",
            ),
            CycleMaster(
                cycle_code="CYCLE_S1_A",
                cycle_name="S1 cycle A",
                workshop_code="S1",
                workshop_name="S1 workshop",
            ),
        ],
        line_masters=[
            LineMaster(
                line_code="LINE_S2",
                workshop_code="S2",
                workshop_name="S2 workshop",
            )
        ],
        machine_masters=[
            MachineMaster(
                equipment_code="s2_zr",
                process_code="ZR",
                line_code="LINE_S2",
            ),
            MachineMaster(
                equipment_code="s2_pk",
                process_code="PK",
                line_code="LINE_S2",
            ),
        ],
        machine_statuses=[
            MachineRuntimeStatus(
                equipment_code="s2_zr",
                process_code="ZR",
                status="running",
                product_code="HG182T",
                output_rate_per_hour=8000,
            ),
            MachineRuntimeStatus(
                equipment_code="s2_pk",
                process_code="PK",
                status="running",
                product_code="HG182T",
                input_rate_per_hour=4000,
            ),
        ],
        buffer_segments=[
            BufferSegment(
                buffer_code="BUF_ZR_PK",
                service_process_codes=["ZR", "PK"],
                max_capacity=20000,
            )
        ],
        buffer_inventories=[
            BufferInventoryItem(
                buffer_code="BUF_ZR_PK",
                cycle_code="CYCLE_S2_A",
                product_code="HG182T",
                process_from="ZR",
                process_to="PK",
                inventory_quantity=13000,
            ),
            BufferInventoryItem(
                buffer_code="BUF_ZR_PK",
                cycle_code="CYCLE_S2_B",
                product_code="HG182R",
                process_from="ZR",
                process_to="PK",
                inventory_quantity=5000,
            ),
            BufferInventoryItem(
                buffer_code="BUF_ZR_PK",
                cycle_code="CYCLE_S1_A",
                product_code="HG182N",
                process_from="ZR",
                process_to="PK",
                inventory_quantity=1000,
            ),
        ],
    )
    net_rates = NetRateCalculator(RealtimeFirstRateStrategy()).calculate(snapshot)

    result = next(
        item
        for item in OverflowWarningEvaluator().evaluate(
            snapshot,
            OverflowTimeCalculator().calculate(snapshot, net_rates),
        )
        if item.cycle_code == "CYCLE_S2_A"
    )

    assert result.workshop_code == "S2"
    assert result.segment_inventory == 18000
    assert result.overflow_minutes == 30
    assert result.warning_triggered is True
