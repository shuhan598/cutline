from datetime import datetime

import pytest

import app.core.net_rate.net_rate_calculator as net_rate_module
from app.schemas.common_schema import (
    AlgorithmBufferOrderInventory,
    AlgorithmBufferProcessRelation,
    AlgorithmLine,
    AlgorithmMachineLineRelation,
    AlgorithmMachineMaster,
    AlgorithmMachineRuntime,
    AlgorithmOrder,
    AlgorithmProduct,
)
from app.schemas.request_schema import AlgorithmSnapshot


def _line(
    line_code: str = "LINE-N-S1",
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


def _order(order_code: str = "ORD-001") -> AlgorithmOrder:
    return AlgorithmOrder(
        order_code=order_code,
        order_name=order_code,
        order_status="RUNNING",
        product_code="PROD-001",
        product_name="产品一",
        workshop_code="S1",
        workshop_name="一车间",
        total_quantity=10000,
        produced_quantity=1000,
        piece_source="A",
        estimated_yield="99%",
    )


def _product(
    product_code: str = "PROD-001",
    wafer_size: str = "182",
) -> AlgorithmProduct:
    return AlgorithmProduct(
        product_code=product_code,
        product_name=product_code,
        wafer_size=wafer_size,
        source_grade="A",
        material_code=f"MAT-{product_code}",
        material_name=f"物料-{product_code}",
    )


def _runtime(
    machine_code: str,
    order_code: str = "ORD-001",
    status: str = "running",
    input_quantity: float = 0,
    output_quantity: float = 0,
    period_quantity: float = 999999,
) -> AlgorithmMachineRuntime:
    return AlgorithmMachineRuntime(
        machine_code=machine_code,
        status=status,
        current_order_code=order_code,
        tangent_time=None,
        input_quantity_30m=input_quantity,
        output_quantity_30m=output_quantity,
        period_quantity_30m=period_quantity,
        out_time=None,
    )


def _add_machine(
    snapshot: AlgorithmSnapshot,
    machine_code: str,
    process_code: str,
    *,
    order_code: str = "ORD-001",
    status: str = "running",
    line_code: str = "LINE-N-S1",
    input_quantity: float = 0,
    output_quantity: float = 0,
    period_quantity: float = 999999,
) -> None:
    snapshot.machine_masters.append(
        AlgorithmMachineMaster(
            machine_code=machine_code,
            machine_name=machine_code,
            process_code=process_code,
            process_name=process_code,
        )
    )
    snapshot.machine_lines.append(
        AlgorithmMachineLineRelation(
            machine_code=machine_code,
            line_code=line_code,
        )
    )
    snapshot.machine_runtimes.append(
        _runtime(
            machine_code,
            order_code,
            status,
            input_quantity,
            output_quantity,
            period_quantity,
        )
    )


def _snapshot(
    *,
    upstream_output: float = 100,
    downstream_input: float = 160,
) -> AlgorithmSnapshot:
    snapshot = AlgorithmSnapshot(
        current_time=datetime(2026, 7, 15, 8, 30),
        workshops=[],
        lines=[_line()],
        machine_lines=[],
        machine_runtimes=[],
        machine_masters=[],
        machine_product_capacities=[],
        orders=[_order()],
        products=[_product()],
        process_routes=[],
        buffer_masters=[],
        buffer_process_relations=[
            AlgorithmBufferProcessRelation(
                buffer_code="BUF-01",
                workshop_code="S1",
                upstream_process_code="ZR",
                downstream_process_code="PK",
            )
        ],
        buffer_order_inventories=[
            AlgorithmBufferOrderInventory(
                buffer_code="BUF-01",
                order_code="ORD-001",
                current_quantity=1600,
            )
        ],
        agv_relations=[],
    )
    _add_machine(
        snapshot,
        "ZR-01",
        "ZR",
        output_quantity=upstream_output,
    )
    _add_machine(
        snapshot,
        "PK-01",
        "PK",
        input_quantity=downstream_input,
    )
    return snapshot


def _calculate(snapshot: AlgorithmSnapshot):
    return net_rate_module.NetRateCalculator().calculate(snapshot)


def _assert_calculation_error(snapshot: AlgorithmSnapshot, match: str) -> None:
    error_type = getattr(net_rate_module, "NetRateCalculationError", ValueError)
    with pytest.raises(error_type, match=match):
        _calculate(snapshot)


def test_single_upstream_and_downstream_machines_are_calculated_per_inventory():
    result = _calculate(_snapshot())[0]

    assert result.model_dump() == {
        "buffer_code": "BUF-01",
        "order_code": "ORD-001",
        "wafer_size": "182",
        "wafer_spec": "N",
        "workshop_code": "S1",
        "upstream_process_code": "ZR",
        "downstream_process_code": "PK",
        "current_quantity": 1600.0,
        "upstream_output_rate": 200.0,
        "downstream_input_rate": 320.0,
        "net_consumption_rate": 120.0,
    }


def test_wafer_size_comes_from_order_product_reference():
    snapshot = _snapshot()
    snapshot.orders[0] = snapshot.orders[0].model_copy(
        update={"product_code": "PROD-210"}
    )
    snapshot.products.append(_product("PROD-210", "210"))

    assert _calculate(snapshot)[0].wafer_size == "210"


def test_inventory_order_product_reference_must_exist():
    snapshot = _snapshot()
    snapshot.products = []

    _assert_calculation_error(snapshot, "PROD-001.*product")


def test_inventory_order_product_wafer_size_must_not_be_blank():
    snapshot = _snapshot()
    snapshot.products[0] = snapshot.products[0].model_copy(
        update={"wafer_size": "  "}
    )

    _assert_calculation_error(snapshot, "PROD-001.*wafer_size")


def test_duplicate_product_code_fails():
    snapshot = _snapshot()
    snapshot.products.append(_product())

    _assert_calculation_error(snapshot, "Duplicate product.*PROD-001")


def test_multiple_matching_machines_are_all_summed():
    snapshot = _snapshot(upstream_output=3000, downstream_input=4000)
    _add_machine(snapshot, "ZR-02", "ZR", output_quantity=2500)
    _add_machine(snapshot, "ZR-03", "ZR", output_quantity=2000)
    _add_machine(snapshot, "PK-02", "PK", input_quantity=4500)

    result = _calculate(snapshot)[0]

    assert result.upstream_output_rate == 15000
    assert result.downstream_input_rate == 17000
    assert result.net_consumption_rate == 2000


def test_different_order_machines_do_not_enter_current_order_rate():
    snapshot = _snapshot()
    snapshot.orders.append(_order("ORD-002"))
    _add_machine(
        snapshot,
        "ZR-OTHER-ORDER",
        "ZR",
        order_code="ORD-002",
        output_quantity=50000,
    )

    assert _calculate(snapshot)[0].upstream_output_rate == 200


def test_different_wafer_spec_for_another_order_does_not_enter_rate():
    snapshot = _snapshot()
    snapshot.orders.append(_order("ORD-002"))
    snapshot.lines.append(_line("LINE-R-S1", "R", "S1"))
    _add_machine(
        snapshot,
        "ZR-R",
        "ZR",
        order_code="ORD-002",
        line_code="LINE-R-S1",
        output_quantity=50000,
    )

    assert _calculate(snapshot)[0].upstream_output_rate == 200


def test_different_workshop_machine_does_not_enter_rate():
    snapshot = _snapshot()
    snapshot.lines.append(_line("LINE-N-S2", "N", "S2"))
    _add_machine(
        snapshot,
        "ZR-S2",
        "ZR",
        line_code="LINE-N-S2",
        output_quantity=50000,
    )

    assert _calculate(snapshot)[0].upstream_output_rate == 200


def test_different_concrete_process_machine_does_not_enter_rate():
    snapshot = _snapshot()
    _add_machine(
        snapshot,
        "OTHER-01",
        "OX",
        input_quantity=50000,
        output_quantity=50000,
    )

    result = _calculate(snapshot)[0]
    assert result.upstream_output_rate == 200
    assert result.downstream_input_rate == 320


@pytest.mark.parametrize("status", ["idle", "RUNNING", "运行"])
def test_non_running_status_machine_does_not_enter_rate(status):
    snapshot = _snapshot()
    _add_machine(
        snapshot,
        f"ZR-{status}",
        "ZR",
        status=status,
        output_quantity=50000,
    )

    assert _calculate(snapshot)[0].upstream_output_rate == 200


def test_period_quantity_does_not_enter_rate():
    snapshot = _snapshot()
    for runtime in snapshot.machine_runtimes:
        runtime.period_quantity_30m = 999999999

    result = _calculate(snapshot)[0]
    assert result.upstream_output_rate == 200
    assert result.downstream_input_rate == 320


def test_missing_matching_upstream_machine_produces_zero_rate():
    snapshot = _snapshot()
    snapshot.machine_runtimes = [
        runtime for runtime in snapshot.machine_runtimes if runtime.machine_code != "ZR-01"
    ]

    assert _calculate(snapshot)[0].upstream_output_rate == 0


def test_missing_matching_downstream_machine_produces_zero_rate():
    snapshot = _snapshot()
    snapshot.machine_runtimes = [
        runtime for runtime in snapshot.machine_runtimes if runtime.machine_code != "PK-01"
    ]

    assert _calculate(snapshot)[0].downstream_input_rate == 0


def test_same_order_in_different_buffers_produces_separate_results():
    snapshot = _snapshot()
    snapshot.buffer_process_relations.append(
        AlgorithmBufferProcessRelation(
            buffer_code="BUF-02",
            workshop_code="S1",
            upstream_process_code="ZR",
            downstream_process_code="PK",
        )
    )
    snapshot.buffer_order_inventories.append(
        AlgorithmBufferOrderInventory(
            buffer_code="BUF-02",
            order_code="ORD-001",
            current_quantity=800,
        )
    )

    results = _calculate(snapshot)
    assert [(item.buffer_code, item.current_quantity) for item in results] == [
        ("BUF-01", 1600),
        ("BUF-02", 800),
    ]


def test_different_orders_with_same_wafer_spec_are_not_aggregated():
    snapshot = _snapshot()
    snapshot.orders.append(_order("ORD-002"))
    snapshot.buffer_order_inventories.append(
        AlgorithmBufferOrderInventory(
            buffer_code="BUF-01",
            order_code="ORD-002",
            current_quantity=800,
        )
    )
    _add_machine(
        snapshot,
        "ZR-ORD-002",
        "ZR",
        order_code="ORD-002",
        output_quantity=1000,
    )
    _add_machine(
        snapshot,
        "PK-ORD-002",
        "PK",
        order_code="ORD-002",
        input_quantity=1500,
    )

    results = {item.order_code: item for item in _calculate(snapshot)}
    assert results["ORD-001"].net_consumption_rate == 120
    assert results["ORD-002"].net_consumption_rate == 1000


def test_same_order_with_multiple_wafer_specs_fails():
    snapshot = _snapshot()
    snapshot.lines.append(_line("LINE-R-S1", "R", "S1"))
    _add_machine(
        snapshot,
        "ZR-R",
        "ZR",
        line_code="LINE-R-S1",
        output_quantity=1,
    )

    _assert_calculation_error(snapshot, "ORD-001.*multiple wafer_spec")


def test_order_wafer_spec_cannot_be_inferred_without_current_runtime():
    snapshot = _snapshot()
    snapshot.machine_runtimes = []

    _assert_calculation_error(snapshot, "ORD-001.*wafer_spec.*no running machine")


def test_order_wafer_spec_cannot_be_inferred_from_stopped_runtime():
    snapshot = _snapshot()
    for runtime in snapshot.machine_runtimes:
        runtime.status = "stopped"

    _assert_calculation_error(snapshot, "ORD-001.*wafer_spec.*no running machine")

@pytest.mark.parametrize(
    ("upstream_output", "downstream_input", "expected"),
    [(100, 150, 100), (100, 100, 0), (150, 100, -100)],
)
def test_net_consumption_rate_signs(
    upstream_output, downstream_input, expected
):
    result = _calculate(
        _snapshot(
            upstream_output=upstream_output,
            downstream_input=downstream_input,
        )
    )[0]

    assert result.net_consumption_rate == expected


def test_inventory_order_reference_must_exist():
    snapshot = _snapshot()
    snapshot.buffer_order_inventories[0] = AlgorithmBufferOrderInventory(
        buffer_code="BUF-01",
        order_code="UNKNOWN",
        current_quantity=1,
    )

    _assert_calculation_error(snapshot, "UNKNOWN.*order")


def test_inventory_buffer_process_relation_must_exist():
    snapshot = _snapshot()
    snapshot.buffer_process_relations = []

    _assert_calculation_error(snapshot, "BUF-01.*process relation")


def test_runtime_machine_master_reference_must_exist():
    snapshot = _snapshot()
    snapshot.machine_masters = [
        master for master in snapshot.machine_masters if master.machine_code != "ZR-01"
    ]

    _assert_calculation_error(snapshot, "ZR-01.*machine master")


def test_runtime_machine_line_reference_must_exist():
    snapshot = _snapshot()
    snapshot.machine_lines = [
        relation
        for relation in snapshot.machine_lines
        if relation.machine_code != "ZR-01"
    ]

    _assert_calculation_error(snapshot, "ZR-01.*machine-line")


def test_machine_line_target_line_reference_must_exist():
    snapshot = _snapshot()
    snapshot.machine_lines[0] = AlgorithmMachineLineRelation(
        machine_code="ZR-01",
        line_code="UNKNOWN",
    )

    _assert_calculation_error(snapshot, "UNKNOWN.*line")


def test_multiple_machine_line_relations_for_same_machine_fail():
    snapshot = _snapshot()
    snapshot.machine_lines.append(
        AlgorithmMachineLineRelation(
            machine_code="ZR-01",
            line_code="LINE-N-S1",
        )
    )

    _assert_calculation_error(snapshot, "ZR-01.*multiple machine-line")


def test_multiple_process_relations_for_same_buffer_fail():
    snapshot = _snapshot()
    snapshot.buffer_process_relations.append(
        AlgorithmBufferProcessRelation(
            buffer_code="BUF-01",
            workshop_code="S1",
            upstream_process_code="ZR",
            downstream_process_code="OX",
        )
    )

    _assert_calculation_error(snapshot, "BUF-01.*multiple process relation")
