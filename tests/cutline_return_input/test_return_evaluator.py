from datetime import datetime
from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)
from app.core.return_judge.return_evaluator import ReturnEvaluator
from app.schemas.common_schema import AlgorithmConfig, CutlineEvent, MachineRuntimeStatus
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import DepletionResult, NetRateResult


RETURN_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_return_input.json"


def build():
    snapshot = MockAdapter().load(RETURN_INPUT_PATH)
    net_rates = NetRateCalculator(RealtimeFirstRateStrategy()).calculate(snapshot)
    depletions = DepletionTimeCalculator().calculate(snapshot, net_rates)
    return ReturnEvaluator().evaluate(snapshot, net_rates, depletions)


def by_equipment(results):
    return {r.equipment_code: r for r in results}


def test_returns_one_result_per_tracked_event():
    results = build()
    assert len(results) == 2


def test_zr03_triggers_return_when_three_conditions_met():
    zr03 = by_equipment(build())["zr03"]
    assert zr03.net_rate_per_hour == -6400
    assert zr03.inventory_quantity == 5000
    assert zr03.negative_duration_minutes == 25
    assert zr03.safety_inventory_quantity == 3200
    assert zr03.triggered is True


def test_zr_r_clears_negative_start_time_when_net_rate_non_negative():
    zr_r = by_equipment(build())["zr_r"]
    assert zr_r.net_rate_per_hour == 0
    assert zr_r.negative_start_time is None
    assert zr_r.triggered is False


def test_return_evaluator_matches_net_rate_and_inventory_by_workshop():
    snapshot = CutlineSnapshot(
        current_time=datetime(2026, 6, 20, 10, 0, 0),
        machine_statuses=[
            MachineRuntimeStatus(
                equipment_code="zr03",
                process_code="ZR",
                status="running",
            )
        ],
        active_cutline_events=[
            CutlineEvent(
                equipment_code="zr03",
                cut_time=datetime(2026, 6, 20, 9, 0, 0),
                previous_product_code="HG182R",
                next_product_code="HG182T",
                negative_start_time=datetime(2026, 6, 20, 9, 30, 0),
                workshop_code="S2",
                workshop_name="S2车间",
            )
        ],
        config=AlgorithmConfig(cutline_lead_minutes=30, stability_window_minutes=20),
    )
    net_rates = [
        NetRateResult(
            buffer_code="BUF_S1",
            workshop_code="S1",
            workshop_name="S1车间",
            product_code="HG182T",
            process_from="ZR",
            process_to="PK",
            inventory_quantity=100,
            upstream_output_per_hour=0,
            downstream_input_per_hour=100,
            net_rate_per_hour=-100,
        ),
        NetRateResult(
            buffer_code="BUF_S2",
            workshop_code="s2 ",
            workshop_name="S2车间",
            product_code="HG182T",
            process_from="ZR",
            process_to="PK",
            inventory_quantity=5000,
            upstream_output_per_hour=0,
            downstream_input_per_hour=6400,
            net_rate_per_hour=-6400,
        ),
    ]
    depletions = [
        DepletionResult(
            buffer_code="BUF_S1",
            workshop_code="S1",
            product_code="HG182T",
            process_from="ZR",
            process_to="PK",
            inventory_quantity=100,
            net_rate_per_hour=-100,
            depletion_status="decreasing",
        ),
        DepletionResult(
            buffer_code="BUF_S2",
            workshop_code=" S2",
            product_code="HG182T",
            process_from="ZR",
            process_to="PK",
            inventory_quantity=5000,
            net_rate_per_hour=-6400,
            depletion_status="decreasing",
        ),
    ]

    result = ReturnEvaluator().evaluate(snapshot, net_rates, depletions)[0]

    assert result.buffer_code == "BUF_S2"
    assert result.net_rate_per_hour == -6400
    assert result.inventory_quantity == 5000
    assert result.workshop_code == "S2"
    assert result.workshop_name == "S2车间"
    assert result.triggered is True
