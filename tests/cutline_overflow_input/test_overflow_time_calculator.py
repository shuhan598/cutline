from datetime import datetime

from app.core.prediction_time.overflow_time.overflow_time_calculator import (
    OverflowTimeCalculator,
)
from app.schemas.common_schema import BufferInventoryItem, BufferSegment, CycleMaster
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import NetRateResult


def _net_rate(workshop_code="S2"):
    return NetRateResult(
        buffer_code="BUF_ZR_PK",
        cycle_code=f"CYCLE_{workshop_code}",
        cycle_name=f"{workshop_code} cycle",
        workshop_code=workshop_code,
        workshop_name=f"{workshop_code} workshop",
        product_code="MODEL_P",
        process_from="ZR",
        process_to="PK",
        upstream_output_per_hour=3000,
        downstream_input_per_hour=0,
        net_rate_per_hour=-3000,
    )


def _snapshot(*inventories):
    return CutlineSnapshot(
        current_time=datetime(2026, 1, 1),
        config={"cutline_lead_minutes": 60},
        cycle_masters=[
            CycleMaster(
                cycle_code="CYCLE_S2",
                cycle_name="S2 cycle",
                workshop_code="S2",
                workshop_name="S2 workshop",
            ),
            CycleMaster(
                cycle_code="CYCLE_S1",
                cycle_name="S1 cycle",
                workshop_code="S1",
                workshop_name="S1 workshop",
            ),
        ],
        buffer_segments=[
            BufferSegment(
                buffer_code="BUF_ZR_PK",
                service_process_codes=["ZR", "PK"],
                max_capacity=10000,
            )
        ],
        buffer_inventories=list(inventories),
    )


def _inventory(cycle_code, product_code, quantity):
    return BufferInventoryItem(
        buffer_code="BUF_ZR_PK",
        cycle_code=cycle_code,
        product_code=product_code,
        process_from="ZR",
        process_to="PK",
        inventory_quantity=quantity,
    )


def test_overflow_time_calculator_uses_existing_formula():
    snapshot = _snapshot(
        _inventory("CYCLE_S2", "MODEL_P", 5000),
        _inventory("CYCLE_S2", "MODEL_R", 3000),
    )

    result = OverflowTimeCalculator().calculate(snapshot, [_net_rate()])[0]

    assert result.segment_capacity == 10000
    assert result.segment_inventory == 8000
    assert result.net_rate_per_hour == -3000
    assert result.overflow_minutes == 40
    assert result.cutline_lead_minutes == 60


def test_overflow_time_calculator_keeps_workshop_inventory_isolated():
    snapshot = _snapshot(
        _inventory("CYCLE_S2", "MODEL_P", 5000),
        _inventory("CYCLE_S2", "MODEL_R", 3000),
        _inventory("CYCLE_S1", "MODEL_X", 1500),
    )

    result = OverflowTimeCalculator().calculate(snapshot, [_net_rate("S2")])[0]

    assert result.workshop_code == "S2"
    assert result.segment_inventory == 8000
    assert result.overflow_minutes == 40
