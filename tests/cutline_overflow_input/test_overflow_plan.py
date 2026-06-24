from pathlib import Path
from datetime import datetime

from app.adapters.mock_adapter import MockAdapter
from app.core.candidate_machine.overflow_candidate_finder import OverflowCandidateFinder
from app.core.cutline_plan.plan_builder import CutlinePlanBuilder
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.warning.overflow_warning import OverflowWarningEvaluator
from app.schemas.common_schema import BufferInventoryItem, BufferSegment, CycleMaster
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import (
    CandidateMachine,
    CandidateResult,
    NetRateResult,
    OverflowWarningResult,
)


OVERFLOW_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_overflow_input.json"


def build():
    snapshot = MockAdapter().load(OVERFLOW_INPUT_PATH)
    strategy = RealtimeFirstRateStrategy()
    net_rates = NetRateCalculator(strategy).calculate(snapshot)
    warnings = OverflowWarningEvaluator().evaluate(snapshot, net_rates)
    candidates = OverflowCandidateFinder(strategy).find(snapshot, warnings, net_rates)
    return CutlinePlanBuilder().build_overflow(snapshot, warnings, candidates, net_rates)


def test_overflow_plan_moves_zr_t1_to_hg182r_and_resolves_risk():
    plans, interventions = build()
    assert len(plans) == 1
    plan = plans[0]
    assert plan.warning_type == "overflow"
    assert plan.product_code == "HG182T"
    assert [m.equipment_code for m in plan.selected_machines] == ["zr_t1"]
    assert plan.selected_machines[0].target_product_code == "HG182R"
    assert interventions == []


def test_overflow_plan_target_check_uses_same_workshop_segment_inventory():
    snapshot = CutlineSnapshot(
        current_time=datetime(2026, 1, 1),
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
                product_code="MODEL_X",
                process_from="ZR",
                process_to="PK",
                inventory_quantity=1000,
            ),
            BufferInventoryItem(
                buffer_code="BUF_ZR_PK",
                cycle_code="CYCLE_S2_B",
                product_code="MODEL_Y",
                process_from="ZR",
                process_to="PK",
                inventory_quantity=18900,
            ),
        ],
    )
    warning = OverflowWarningResult(
        buffer_code="BUF_ZR_PK",
        cycle_code="CYCLE_S2_A",
        cycle_name="S2 cycle A",
        workshop_code="S2",
        workshop_name="S2 workshop",
        product_code="MODEL_X",
        process_from="ZR",
        process_to="PK",
        warning_triggered=True,
        reason="overflow_time_within_lead_time",
        segment_inventory=19900,
        segment_capacity=20000,
        net_rate_per_hour=-1000,
        overflow_minutes=6,
        cutline_lead_minutes=30,
    )
    candidate = CandidateMachine(
        equipment_code="s2_zr_x",
        workshop_code="S2",
        workshop_name="S2 workshop",
        process_code="ZR",
        current_product_code="MODEL_X",
        target_product_code="MODEL_Y",
        current_output_rate_per_hour=1000,
        contribution_capacity_per_hour=1000,
        utilization_rate=1.0,
        reason="overflow_switch_away_to_target_with_gap",
    )
    candidate_result = CandidateResult(
        buffer_code="BUF_ZR_PK",
        cycle_code="CYCLE_S2_A",
        cycle_name="S2 cycle A",
        workshop_code="S2",
        workshop_name="S2 workshop",
        product_code="MODEL_X",
        process_from="ZR",
        process_to="PK",
        candidate_found=True,
        candidate_status="candidate_found",
        candidates=[candidate],
    )
    net_rates = [
        NetRateResult(
            buffer_code="BUF_ZR_PK",
            cycle_code="CYCLE_S2_A",
            cycle_name="S2 cycle A",
            workshop_code="S2",
            workshop_name="S2 workshop",
            product_code="MODEL_X",
            process_from="ZR",
            process_to="PK",
            upstream_output_per_hour=1000,
            downstream_input_per_hour=0,
            net_rate_per_hour=-1000,
        ),
        NetRateResult(
            buffer_code="BUF_ZR_PK",
            cycle_code="CYCLE_S2_B",
            cycle_name="S2 cycle B",
            workshop_code="S2",
            workshop_name="S2 workshop",
            product_code="MODEL_Y",
            process_from="ZR",
            process_to="PK",
            upstream_output_per_hour=0,
            downstream_input_per_hour=500,
            net_rate_per_hour=500,
        ),
    ]

    plans, interventions = CutlinePlanBuilder().build_overflow(
        snapshot,
        [warning],
        [candidate_result],
        net_rates,
    )

    assert plans == []
    assert len(interventions) == 1
