from datetime import datetime

from app.schemas.common_schema import (
    AlgorithmAgvRelation,
    AlgorithmBufferProcessRelation,
    AlgorithmLine,
    AlgorithmMachineLineRelation,
    AlgorithmMachineMaster,
    AlgorithmMachineRuntime,
    AlgorithmOrder,
    AlgorithmProduct,
)
from app.schemas.request_schema import AlgorithmSnapshot


def agv_relation(
    machine_code: str = "M-01",
    order_code: str = "ORD-CURRENT",
    order_name: str = "Current Order",
    wafer_spec: str = "N",
    binding_time: datetime = datetime(2026, 7, 15, 8, 0),
) -> AlgorithmAgvRelation:
    return AlgorithmAgvRelation(
        machine_code=machine_code,
        machine_name=machine_code,
        order_code=order_code,
        order_name=order_name,
        wafer_spec=wafer_spec,
        binding_time=binding_time,
    )


def line(
    line_code: str = "LINE-1",
    wafer_spec: str = "N",
    workshop_code: str = "S1",
) -> AlgorithmLine:
    return AlgorithmLine(
        line_code=line_code,
        line_name=line_code,
        wafer_spec=wafer_spec,
        workshop_code=workshop_code,
        workshop_name=workshop_code,
    )


def machine(
    machine_code: str = "M-01",
    process_code: str = "P01",
    process_name: str = "制绒",
) -> AlgorithmMachineMaster:
    return AlgorithmMachineMaster(
        machine_code=machine_code,
        machine_name=machine_code,
        process_code=process_code,
        process_name=process_name,
    )


def machine_line(
    machine_code: str = "M-01",
    line_code: str = "LINE-1",
) -> AlgorithmMachineLineRelation:
    return AlgorithmMachineLineRelation(
        machine_code=machine_code,
        line_code=line_code,
    )


def runtime(
    machine_code: str = "M-01",
    order_code: str | None = "ORD-CURRENT",
    status: str = "running",
    input_quantity_30m: float = 10000,
    output_quantity_30m: float = 8000,
) -> AlgorithmMachineRuntime:
    return AlgorithmMachineRuntime(
        machine_code=machine_code,
        status=status,
        current_order_code=order_code,
        tangent_time=None,
        input_quantity_30m=input_quantity_30m,
        output_quantity_30m=output_quantity_30m,
        period_quantity_30m=999999,
        out_time=None,
    )


def order(
    order_code: str = "ORD-CURRENT",
    product_code: str = "PROD-CURRENT",
    workshop_code: str = "S1",
) -> AlgorithmOrder:
    return AlgorithmOrder(
        order_code=order_code,
        order_name=order_code,
        order_status="RUNNING",
        product_code=product_code,
        product_name=product_code,
        workshop_code=workshop_code,
        workshop_name=workshop_code,
        total_quantity=10000,
        produced_quantity=1000,
        piece_source="A",
        estimated_yield="99%",
    )


def product(
    product_code: str = "PROD-CURRENT",
    wafer_size: str = "182",
    source_grade: str = "A",
) -> AlgorithmProduct:
    return AlgorithmProduct(
        product_code=product_code,
        product_name=product_code,
        wafer_size=wafer_size,
        source_grade=source_grade,
        material_code=f"MAT-{product_code}",
        material_name=f"物料-{product_code}",
    )


def buffer_relation(
    buffer_code: str = "BUF-01",
    workshop_code: str = "S1",
    upstream_process_code: str = "P01",
    downstream_process_code: str = "P02",
) -> AlgorithmBufferProcessRelation:
    return AlgorithmBufferProcessRelation(
        buffer_code=buffer_code,
        workshop_code=workshop_code,
        upstream_process_code=upstream_process_code,
        downstream_process_code=downstream_process_code,
    )


def snapshot() -> AlgorithmSnapshot:
    return AlgorithmSnapshot(
        current_time=datetime(2026, 7, 15, 8, 30),
        workshops=[],
        lines=[line()],
        machine_lines=[machine_line()],
        machine_runtimes=[runtime()],
        machine_masters=[machine()],
        machine_product_capacities=[],
        orders=[order()],
        products=[product()],
        process_routes=[],
        buffer_masters=[],
        buffer_process_relations=[buffer_relation()],
        buffer_order_inventories=[],
        agv_relations=[agv_relation()],
    )
