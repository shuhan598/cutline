from pathlib import Path
from datetime import datetime

from app.adapters.mock_adapter import MockAdapter
from app.core.candidate_machine.stockout_candidate_finder import StockoutCandidateFinder
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)
from app.core.warning.stockout_warning import StockoutWarningEvaluator
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
from app.schemas.result_schema import StockoutWarningResult


COMPLEX_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_complex_input.json"


def load_complex_snapshot():
    return MockAdapter().load(COMPLEX_INPUT_PATH)


def build_candidates(snapshot):
    strategy = RealtimeFirstRateStrategy()
    net_rates = NetRateCalculator(strategy).calculate(snapshot)
    depletions = DepletionTimeCalculator().calculate(snapshot, net_rates)
    warnings = StockoutWarningEvaluator().evaluate(snapshot, depletions)
    return StockoutCandidateFinder(strategy).find(snapshot, warnings)


def by_product(results, product_code):
    for result in results:
        if result.product_code == product_code:
            return result
    raise AssertionError(f"Expected result for {product_code} was not found")


def codes(candidate_result):
    return {candidate.equipment_code for candidate in candidate_result.candidates}


def _pr_stockout_snapshot(
    *,
    equipment_code="s2_el_p",
    workshop_code="S2",
    workshop_name="S2 workshop",
    process_name="EL",
):
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
            ProcessRouteStep(
                process_code="EL",
                process_name=process_name,
                sequence_no=1,
            )
        ],
        line_masters=[
            LineMaster(
                line_code="line1",
                workshop_code=workshop_code,
                workshop_name=workshop_name,
            )
        ],
        machine_masters=[
            MachineMaster(
                equipment_code=equipment_code,
                process_code="EL",
                process_name=process_name,
                line_code="line1",
            )
        ],
        machine_statuses=[
            MachineRuntimeStatus(
                equipment_code=equipment_code,
                process_code="EL",
                status="running",
                product_code="MODEL_P",
                output_rate_per_hour=100,
            )
        ],
        capacity_records=[
            MachineCapacityRecord(
                equipment_code=equipment_code,
                product_code="MODEL_P",
                actual_capacity_per_hour=120,
                process_time_minutes=30,
            ),
            MachineCapacityRecord(
                equipment_code=equipment_code,
                product_code="MODEL_R",
                actual_capacity_per_hour=110,
                process_time_minutes=30,
            ),
        ],
    )


def _stockout_warning(product_code="MODEL_R"):
    return StockoutWarningResult(
        buffer_code="BUF_EL_NEXT",
        cycle_code="CYCLE_S2_01",
        cycle_name="S2 cycle",
        workshop_code="S2",
        workshop_name="S2 workshop",
        product_code=product_code,
        process_from="EL",
        process_to="NEXT",
        warning_type="stockout",
        warning_triggered=True,
        reason="test",
        inventory_quantity=100,
        net_rate_per_hour=-100,
        depletion_minutes=10,
        depletion_status="depleting",
        cutline_lead_minutes=30,
    )


def _find_stockout(snapshot):
    return StockoutCandidateFinder(RealtimeFirstRateStrategy()).find(
        snapshot,
        [_stockout_warning()],
    )[0]


def test_returns_results_in_global_depletion_urgency_order():
    results = build_candidates(load_complex_snapshot())

    assert [result.product_code for result in results] == [
        "HG210R",
        "HG182N",
        "HG182T",
    ]
    assert all("priority_rank" not in result.model_dump() for result in results)
    assert all(
        "priority_rank" not in candidate.model_dump()
        for result in results
        for candidate in result.candidates
    )


def test_hg210r_finds_compatible_pk_candidate_and_excludes_invalid_machines():
    hg210r = by_product(build_candidates(load_complex_snapshot()), "HG210R")

    assert hg210r.candidate_found is True
    assert hg210r.candidate_status == "candidate_found"
    assert "pk_hg210t_candidate" in codes(hg210r)
    assert "pk_hg210r_target" not in codes(hg210r)
    assert "pk_hg210t_stopped" not in codes(hg210r)
    assert "pk_hg182r_size_mismatch" not in codes(hg210r)


def test_hg182n_requires_manual_intervention_when_no_compatible_machine_exists():
    hg182n = by_product(build_candidates(load_complex_snapshot()), "HG182N")

    assert hg182n.candidate_found is False
    assert hg182n.candidate_status == "manual_intervention_required"
    assert hg182n.reason == "no_compatible_running_upstream_machine"
    assert hg182n.candidates == []


def test_hg182t_finds_compatible_zr_candidate_and_excludes_invalid_machines():
    hg182t = by_product(build_candidates(load_complex_snapshot()), "HG182T")

    assert hg182t.candidate_found is True
    assert hg182t.candidate_status == "candidate_found"
    assert len(hg182t.candidates) >= 2
    assert "zr_hg182r_candidate" in codes(hg182t)
    assert "zr_hg182r_candidate_2" in codes(hg182t)
    assert "zr_hg182t_target" not in codes(hg182t)
    assert "zr_hg182r_stopped" not in codes(hg182t)
    assert "zr_hg210r_size_mismatch" not in codes(hg182t)
    assert "zr_hg182n_target" not in codes(hg182t)


def test_s2_non_silk_pr_pair_enters_stockout_candidate_list():
    result = _find_stockout(_pr_stockout_snapshot())

    assert result.candidate_found is True
    assert result.cycle_code == "CYCLE_S2_01"
    assert result.workshop_code == "S2"
    assert codes(result) == {"s2_el_p"}
    assert result.candidates[0].workshop_code == "S2"


def test_non_s2_non_silk_pr_pair_does_not_enter_stockout_candidate_list():
    result = _find_stockout(
        _pr_stockout_snapshot(
            equipment_code="s1_el_p",
            workshop_code="S1",
            workshop_name="S1 workshop",
        )
    )

    assert result.candidate_found is False
    assert result.candidates == []


def test_s1_same_process_compatible_machine_is_excluded_from_s2_stockout_warning():
    snapshot = _pr_stockout_snapshot()
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

    result = _find_stockout(snapshot)

    assert result.candidate_found is True
    assert codes(result) == {"s2_el_p"}


def test_s2_silk_screen_process_name_makes_pr_pair_incompatible_for_stockout():
    result = _find_stockout(_pr_stockout_snapshot(process_name="丝网"))

    assert result.candidate_found is False
    assert result.candidates == []


def test_s2_silk_screen_numbered_process_name_makes_pr_pair_incompatible_for_stockout():
    result = _find_stockout(_pr_stockout_snapshot(process_name="丝网01"))

    assert result.candidate_found is False
    assert result.candidates == []
