from pathlib import Path
from datetime import datetime

from app.adapters.mock_adapter import MockAdapter
from app.core.candidate_machine.overflow_candidate_finder import OverflowCandidateFinder
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.prediction_time.overflow_time.overflow_time_calculator import (
    OverflowTimeCalculator,
)
from app.core.warning.overflow_warning import OverflowWarningEvaluator
from app.schemas.common_schema import (
    CycleMaster,
    LineMaster,
    MachineCapacityRecord,
    MachineMaster,
    MachineRuntimeStatus,
    ProcessRouteStep,
    ProductModel,
)
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import NetRateResult, OverflowWarningResult


OVERFLOW_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_overflow_input.json"


def build():
    snapshot = MockAdapter().load(OVERFLOW_INPUT_PATH)
    strategy = RealtimeFirstRateStrategy()
    net_rates = NetRateCalculator(strategy).calculate(snapshot)
    overflow_times = OverflowTimeCalculator().calculate(snapshot, net_rates)
    warnings = OverflowWarningEvaluator().evaluate(snapshot, overflow_times)
    return OverflowCandidateFinder(strategy).find(snapshot, warnings, net_rates)


def test_hg182t_overflow_candidate_is_zr_t1_with_target_hg182r():
    results = build()
    assert len(results) == 1
    result = results[0]
    assert result.product_code == "HG182T"
    assert result.candidate_found is True
    codes = {c.equipment_code for c in result.candidates}
    assert codes == {"zr_t1"}
    zr_t1 = result.candidates[0]
    assert zr_t1.current_product_code == "HG182T"
    assert zr_t1.target_product_code == "HG182R"


def _pr_overflow_snapshot(include_r_machine=True):
    machines = [
        MachineRuntimeStatus(
            equipment_code="s2_el_p",
            process_code="EL",
            status="running",
            product_code="MODEL_P",
            output_rate_per_hour=100,
        )
    ]
    masters = [
        MachineMaster(
            equipment_code="s2_el_p",
            process_code="EL",
            process_name="EL",
            line_code="line_s2",
        )
    ]
    capacities = [
        MachineCapacityRecord(
            equipment_code="s2_el_p",
            product_code="MODEL_P",
            actual_capacity_per_hour=120,
            process_time_minutes=30,
        ),
        MachineCapacityRecord(
            equipment_code="s2_el_p",
            product_code="MODEL_R",
            actual_capacity_per_hour=110,
            process_time_minutes=30,
        ),
    ]
    if include_r_machine:
        machines.append(
            MachineRuntimeStatus(
                equipment_code="s2_el_r",
                process_code="EL",
                status="running",
                product_code="MODEL_R",
                output_rate_per_hour=90,
            )
        )
        masters.append(
            MachineMaster(
                equipment_code="s2_el_r",
                process_code="EL",
                process_name="EL",
                line_code="line_s2",
            )
        )
        capacities.append(
            MachineCapacityRecord(
                equipment_code="s2_el_r",
                product_code="MODEL_R",
                actual_capacity_per_hour=90,
                process_time_minutes=30,
            )
        )

    return CutlineSnapshot(
        current_time=datetime(2026, 1, 1),
        cycle_masters=[
            CycleMaster(
                cycle_code="CYCLE_S2_01",
                cycle_name="S2 cycle",
                workshop_code="S2",
                workshop_name="S2 workshop",
            ),
            CycleMaster(
                cycle_code="CYCLE_S1_01",
                cycle_name="S1 cycle",
                workshop_code="S1",
                workshop_name="S1 workshop",
            ),
        ],
        product_models=[
            ProductModel(product_code="MODEL_P", wafer_size="182", shape_code="P"),
            ProductModel(product_code="MODEL_R", wafer_size="182", shape_code="R"),
        ],
        process_route_steps=[
            ProcessRouteStep(process_code="EL", process_name="EL", sequence_no=1)
        ],
        line_masters=[
            LineMaster(
                line_code="line_s2",
                workshop_code="S2",
                workshop_name="S2 workshop",
            )
        ],
        machine_masters=masters,
        machine_statuses=machines,
        capacity_records=capacities,
    )


def _overflow_warning(product_code="MODEL_P"):
    return OverflowWarningResult(
        buffer_code="BUF_EL_NEXT",
        cycle_code="CYCLE_S2_01",
        cycle_name="S2 cycle",
        workshop_code="S2",
        workshop_name="S2 workshop",
        product_code=product_code,
        process_from="EL",
        process_to="NEXT",
        warning_triggered=True,
        reason="test",
        segment_inventory=130,
        segment_capacity=100,
        net_rate_per_hour=100,
        overflow_minutes=10,
        cutline_lead_minutes=30,
    )


def _net_rate(product_code, net_rate_per_hour=100):
    return NetRateResult(
        buffer_code="BUF_EL_NEXT",
        cycle_code="CYCLE_S2_01",
        cycle_name="S2 cycle",
        workshop_code="S2",
        workshop_name="S2 workshop",
        product_code=product_code,
        process_from="EL",
        process_to="NEXT",
        upstream_output_per_hour=100,
        downstream_input_per_hour=0,
        net_rate_per_hour=net_rate_per_hour,
    )


def _find_overflow(snapshot, net_rates):
    return OverflowCandidateFinder(RealtimeFirstRateStrategy()).find(
        snapshot,
        [_overflow_warning()],
        net_rates,
    )[0]


def test_s2_non_silk_overflow_p_can_switch_to_pr_target_r_with_gap():
    result = _find_overflow(_pr_overflow_snapshot(), [_net_rate("MODEL_R")])

    assert result.candidate_found is True
    assert result.cycle_code == "CYCLE_S2_01"
    assert result.workshop_code == "S2"
    assert {candidate.equipment_code for candidate in result.candidates} == {"s2_el_p"}
    assert result.candidates[0].target_product_code == "MODEL_R"
    assert result.candidates[0].workshop_code == "S2"


def test_overflow_candidate_utilization_uses_current_overflow_model_capacity():
    result = _find_overflow(_pr_overflow_snapshot(), [_net_rate("MODEL_R")])

    candidate = result.candidates[0]
    assert candidate.current_output_rate_per_hour == 100
    assert candidate.utilization_rate == 100 / 120
    assert candidate.idle_rate is None
    assert candidate.contribution_capacity_per_hour == 110


def test_current_r_machine_is_not_candidate_when_p_is_overflowing():
    result = _find_overflow(_pr_overflow_snapshot(), [_net_rate("MODEL_R")])

    assert "s2_el_r" not in {
        candidate.equipment_code for candidate in result.candidates
    }


def test_overflow_target_model_must_not_equal_overflow_model():
    result = _find_overflow(
        _pr_overflow_snapshot(include_r_machine=False),
        [_net_rate("MODEL_P")],
    )

    assert result.candidate_found is False
    assert result.candidates == []


def test_s1_current_x_machine_is_excluded_from_s2_overflow_warning():
    snapshot = _pr_overflow_snapshot()
    snapshot.line_masters.append(
        LineMaster(
            line_code="line_s1",
            workshop_code="S1",
            workshop_name="S1 workshop",
        )
    )
    snapshot.machine_masters.append(
        MachineMaster(
            equipment_code="s1_el_p",
            process_code="EL",
            process_name="EL",
            line_code="line_s1",
        )
    )
    snapshot.machine_statuses.append(
        MachineRuntimeStatus(
            equipment_code="s1_el_p",
            process_code="EL",
            status="running",
            product_code="MODEL_P",
            output_rate_per_hour=100,
        )
    )

    result = _find_overflow(snapshot, [_net_rate("MODEL_R")])

    assert {candidate.equipment_code for candidate in result.candidates} == {"s2_el_p"}


def test_overflow_target_gap_must_come_from_same_workshop():
    result = _find_overflow(
        _pr_overflow_snapshot(),
        [
            _net_rate("MODEL_R", net_rate_per_hour=0),
            _net_rate("MODEL_R", net_rate_per_hour=100).model_copy(
                update={"workshop_code": "S1", "cycle_code": "CYCLE_S1_01"}
            ),
        ],
    )

    assert result.candidate_found is False
    assert result.candidates == []
