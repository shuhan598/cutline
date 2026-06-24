from datetime import datetime

from app.core.workshop.workshop_resolver import WorkshopResolver
from app.schemas.common_schema import (
    BufferInventoryItem,
    CycleMaster,
    LineMaster,
    MachineMaster,
    MachineRuntimeStatus,
)
from app.schemas.request_schema import CutlineSnapshot


def _snapshot():
    return CutlineSnapshot(
        current_time=datetime(2026, 1, 1),
        cycle_masters=[
            CycleMaster(
                cycle_code="CYCLE_S2_01",
                cycle_name="S2 cycle",
                workshop_code=" S2 ",
                workshop_name="S2 workshop",
            )
        ],
        line_masters=[
            LineMaster(
                line_code="LINE_S2_01",
                workshop_code="s2",
                workshop_name="S2 workshop",
            )
        ],
        machine_masters=[
            MachineMaster(
                equipment_code="s2_eq",
                process_code="ZR",
                line_code="LINE_S2_01",
            )
        ],
    )


def test_resolves_inventory_workshop_from_inventory_cycle():
    resolver = WorkshopResolver(_snapshot())
    inventory = BufferInventoryItem(
        buffer_code="BUF",
        cycle_code="CYCLE_S2_01",
        product_code="P",
        process_from="ZR",
        process_to="PK",
        inventory_quantity=100,
    )

    assert resolver.resolve_inventory_workshop(inventory) == (
        " S2 ",
        "S2 workshop",
    )


def test_resolves_machine_workshop_through_machine_and_line_master():
    resolver = WorkshopResolver(_snapshot())
    machine = MachineRuntimeStatus(
        equipment_code="s2_eq",
        process_code="ZR",
        status="running",
        product_code="P",
    )

    assert resolver.resolve_machine_workshop(machine) == ("s2", "S2 workshop")


def test_same_workshop_compares_normalized_codes_and_missing_is_false():
    resolver = WorkshopResolver(_snapshot())

    assert resolver.is_same_workshop(" S2 ", "s2") is True
    assert resolver.is_same_workshop("S2", "S1") is False
    assert resolver.is_same_workshop(None, "S2") is False
