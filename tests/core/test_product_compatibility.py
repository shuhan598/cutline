from datetime import datetime

from app.core.candidate_machine.product_compatibility import (
    ProductCompatibilityChecker,
)
from app.schemas.common_schema import (
    LineMaster,
    MachineMaster,
    MachineRuntimeStatus,
    ProductModel,
)
from app.schemas.request_schema import CutlineSnapshot


def _machine(equipment_code="eq1", process_code="EL"):
    return MachineRuntimeStatus(
        equipment_code=equipment_code,
        process_code=process_code,
        status="running",
        product_code="P182",
        output_rate_per_hour=100,
    )


def _model(product_code, wafer_size="182", shape_code="P"):
    return ProductModel(
        product_code=product_code,
        wafer_size=wafer_size,
        shape_code=shape_code,
    )


def _snapshot(
    *,
    machine_masters=None,
    line_masters=None,
    process_route_steps=None,
):
    return CutlineSnapshot(
        current_time=datetime(2026, 1, 1),
        machine_masters=machine_masters or [],
        line_masters=line_masters or [],
        process_route_steps=process_route_steps or [],
    )


def test_same_wafer_size_and_shape_remains_compatible_without_s2_context():
    source = _model("P182", shape_code="P")
    target = _model("P182B", shape_code="P")
    checker = ProductCompatibilityChecker(_snapshot())

    assert checker.is_compatible(_machine(), source, target) is True


def test_different_wafer_size_is_not_compatible():
    source = _model("P182", wafer_size="182", shape_code="P")
    target = _model("P210", wafer_size="210", shape_code="P")
    checker = ProductCompatibilityChecker(_snapshot())

    assert checker.is_compatible(_machine(), source, target) is False


def test_s2_pr_pair_is_not_compatible_when_process_name_cannot_be_resolved():
    source = _model("P182", shape_code="P")
    target = _model("R182", shape_code="R")
    machine = _machine(equipment_code="s2_eq")
    checker = ProductCompatibilityChecker(
        _snapshot(
            machine_masters=[
                MachineMaster(
                    equipment_code="s2_eq",
                    process_code="EL",
                    line_code="line_s2",
                )
            ],
            line_masters=[
                LineMaster(
                    line_code="line_s2",
                    workshop_code="S2",
                    workshop_name="S2 workshop",
                )
            ],
        )
    )

    assert checker.is_compatible(machine, source, target) is False
