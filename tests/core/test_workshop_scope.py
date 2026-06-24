from datetime import datetime

from app.core.candidate_machine.workshop_scope import WorkshopScopeChecker
from app.schemas.common_schema import (
    CycleMaster,
    LineMaster,
    MachineMaster,
    MachineRuntimeStatus,
)
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import StockoutWarningResult


def _warning(**overrides):
    values = {
        "buffer_code": "BUF",
        "product_code": "MODEL_R",
        "process_from": "EL",
        "process_to": "NEXT",
        "warning_type": "stockout",
        "warning_triggered": True,
        "reason": "test",
        "inventory_quantity": 100,
        "net_rate_per_hour": 100,
        "depletion_minutes": 10,
        "depletion_status": "decreasing",
        "cutline_lead_minutes": 30,
        "cycle_code": "CYCLE_S2_01",
    }
    values.update(overrides)
    return StockoutWarningResult(**values)


def _snapshot():
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
        line_masters=[
            LineMaster(
                line_code="LINE_S2_01",
                workshop_code="s2 ",
                workshop_name="S2 workshop",
            ),
            LineMaster(
                line_code="LINE_S1_01",
                workshop_code="S1",
                workshop_name="S1 workshop",
            ),
        ],
        machine_masters=[
            MachineMaster(
                equipment_code="s2_eq",
                process_code="EL",
                line_code="LINE_S2_01",
            ),
            MachineMaster(
                equipment_code="s1_eq",
                process_code="EL",
                line_code="LINE_S1_01",
            ),
        ],
    )


def _machine(equipment_code):
    return MachineRuntimeStatus(
        equipment_code=equipment_code,
        process_code="EL",
        status="running",
        product_code="MODEL_P",
    )


def test_same_workshop_uses_cycle_and_line_master_workshop_codes():
    checker = WorkshopScopeChecker(_snapshot())

    assert checker.is_same_workshop(_machine("s2_eq"), _warning()) is True
    assert checker.is_same_workshop(_machine("s1_eq"), _warning()) is False


def test_warning_workshop_code_takes_priority_over_cycle_master():
    checker = WorkshopScopeChecker(_snapshot())

    assert (
        checker.is_same_workshop(
            _machine("s2_eq"),
            _warning(cycle_code="CYCLE_S1_01", workshop_code=" S2 "),
        )
        is True
    )


def test_missing_warning_or_machine_workshop_is_not_same_workshop():
    checker = WorkshopScopeChecker(_snapshot())

    assert checker.is_same_workshop(_machine("s2_eq"), _warning(cycle_code="UNKNOWN")) is False
    assert checker.is_same_workshop(_machine("unknown_eq"), _warning()) is False
