from datetime import datetime

import pytest

import app.core.net_rate.net_rate_calculator as net_rate_module
from app.schemas.common_schema import (
    AlgorithmAgvRelation,
    AlgorithmBufferOrderInventory,
    AlgorithmBufferProcessRelation,
    AlgorithmLine,
    AlgorithmMachineLineRelation,
    AlgorithmMachineMaster,
    AlgorithmMachineRuntime,
    AlgorithmOrder,
    AlgorithmProcessRoute,
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


def _route(
    process_code: str,
    *,
    workshop_code: str = "S1",
    loop_code: str = "LOOP-01",
) -> AlgorithmProcessRoute:
    return AlgorithmProcessRoute(
        process_code=process_code,
        process_name=process_code,
        sequence=1,
        cache_type="BUFFER",
        workshop_code=workshop_code,
        workshop_name=workshop_code,
        loop_code=loop_code,
        loop_name=loop_code,
        upstream_process_code=None,
        upstream_process_name=None,
        downstream_process_code=None,
        downstream_process_name=None,
    )


def _runtime(
    machine_code: str,
    order_code: str = "ORD-001",
    status: str = "running",
    input_quantity: float = 0,
    output_quantity: float = 0,
) -> AlgorithmMachineRuntime:
    return AlgorithmMachineRuntime(
        machine_code=machine_code,
        status=status,
        current_order_code=order_code,
        tangent_time=None,
        input_quantity_30m=input_quantity,
        output_quantity_30m=output_quantity,
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
    agv_order_code: str | None = None,
    agv_wafer_spec: str = "N",
    input_quantity: float = 0,
    output_quantity: float = 0,
    route_workshop_code: str = "S1",
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
        )
    )
    if not any(
        route.process_code == process_code
        for route in snapshot.process_routes
    ):
        snapshot.process_routes.append(
            _route(
                process_code,
                workshop_code=route_workshop_code,
            )
        )
    effective_order_code = (
        order_code if agv_order_code is None else agv_order_code
    )
    snapshot.agv_relations.append(
        AlgorithmAgvRelation(
            machine_code=machine_code,
            machine_name=machine_code,
            order_code=effective_order_code,
            product_code="PROD-001",
            product_name="产品一",
            wafer_spec=agv_wafer_spec,
            binding_time=snapshot.current_time,
        )
    )


def _snapshot(
    *,
    upstream_output: float = 100,
    downstream_input: float = 160,
    agv_wafer_spec: str = "N",
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
                main_id="MAIN-01",
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
        agv_wafer_spec=agv_wafer_spec,
        output_quantity=upstream_output,
    )
    _add_machine(
        snapshot,
        "PK-01",
        "PK",
        agv_wafer_spec=agv_wafer_spec,
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
        "main_id": "MAIN-01",
        "buffer_code": "BUF-01",
        "buffer_codes": ["BUF-01"],
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


def test_wafer_spec_comes_from_agv_when_line_spec_differs():
    snapshot = _snapshot(agv_wafer_spec="R")

    result = _calculate(snapshot)[0]

    assert snapshot.lines[0].wafer_spec == "N"
    assert result.wafer_spec == "R"
    assert result.upstream_output_rate == 200
    assert result.downstream_input_rate == 320


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


def test_runtime_rates_are_filtered_by_agv_order_and_wafer_spec():
    snapshot = _snapshot(agv_wafer_spec="R")
    snapshot.orders.append(_order("ORD-002"))
    _add_machine(
        snapshot,
        "ZR-AGV-OTHER-ORDER",
        "ZR",
        agv_order_code="ORD-002",
        agv_wafer_spec="R",
        output_quantity=50000,
    )
    _add_machine(
        snapshot,
        "ZR-AGV-OTHER-SPEC",
        "ZR",
        agv_wafer_spec="N",
        output_quantity=50000,
    )

    result = _calculate(snapshot)[0]

    assert result.wafer_spec == "R"
    assert result.upstream_output_rate == 200


def test_runtime_current_order_code_does_not_override_agv_order():
    snapshot = _snapshot()
    for runtime in snapshot.machine_runtimes:
        runtime.current_order_code = "STALE-RUNTIME-ORDER"

    result = _calculate(snapshot)[0]

    assert result.upstream_output_rate == 200
    assert result.downstream_input_rate == 320


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
        agv_wafer_spec="R",
        output_quantity=50000,
    )

    assert _calculate(snapshot)[0].upstream_output_rate == 200


def test_route_workshop_overrides_line_workshop_for_matching_rates():
    snapshot = _snapshot()
    snapshot.process_routes = [
        route.model_copy(update={"workshop_code": "S2"})
        for route in snapshot.process_routes
    ]
    snapshot.buffer_process_relations[0] = (
        snapshot.buffer_process_relations[0].model_copy(
            update={"workshop_code": "S2"}
        )
    )

    result = _calculate(snapshot)[0]

    assert snapshot.lines[0].workshop_code == "S1"
    assert result.workshop_code == "S2"
    assert result.upstream_output_rate == 200
    assert result.downstream_input_rate == 320


def test_line_workshop_does_not_make_route_workshop_machine_match():
    snapshot = _snapshot()
    snapshot.lines[0] = snapshot.lines[0].model_copy(
        update={"workshop_code": "S2"}
    )
    snapshot.buffer_process_relations[0] = (
        snapshot.buffer_process_relations[0].model_copy(
            update={"workshop_code": "S2"}
        )
    )

    result = _calculate(snapshot)[0]

    assert result.upstream_output_rate == 0
    assert result.downstream_input_rate == 0


def test_runtime_machine_process_without_route_fails_without_line_fallback():
    snapshot = _snapshot()
    snapshot.process_routes = [
        route for route in snapshot.process_routes
        if route.process_code != "ZR"
    ]

    _assert_calculation_error(
        snapshot,
        r"Machine ZR-01 process ZR has no process route",
    )


def test_runtime_machine_process_with_cross_workshop_routes_fails_stably():
    snapshot = _snapshot()
    snapshot.process_routes.append(
        _route("ZR", workshop_code="S2", loop_code="LOOP-02")
    )

    _assert_calculation_error(
        snapshot,
        (
            r"Machine ZR-01 process ZR belongs to multiple "
            r"workshops: S1, S2"
        ),
    )


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


def test_runtime_quantity_fields_are_limited_to_rate_inputs():
    snapshot = _snapshot()

    result = _calculate(snapshot)[0]
    assert {
        "input_quantity_30m",
        "output_quantity_30m",
    } <= type(snapshot.machine_runtimes[0]).model_fields.keys()
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


def test_same_main_order_in_different_buffers_aggregates_3600_and_7200():
    snapshot = _snapshot()
    snapshot.buffer_order_inventories[0] = (
        snapshot.buffer_order_inventories[0].model_copy(
            update={"current_quantity": 3600}
        )
    )
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
            main_id="MAIN-01",
            buffer_code="BUF-02",
            order_code="ORD-001",
            current_quantity=7200,
        )
    )

    results = _calculate(snapshot)

    assert len(results) == 1
    assert results[0].main_id == "MAIN-01"
    assert results[0].buffer_code == "BUF-01"
    assert results[0].buffer_codes == ["BUF-01", "BUF-02"]
    assert results[0].current_quantity == 10800
    assert results[0].upstream_output_rate == 200
    assert results[0].downstream_input_rate == 320
    assert results[0].net_consumption_rate == 120


def test_group_buffer_codes_and_representative_are_sorted_not_input_order():
    snapshot = _snapshot()
    snapshot.buffer_process_relations.append(
        AlgorithmBufferProcessRelation(
            buffer_code="BUF-02",
            workshop_code="S1",
            upstream_process_code="ZR",
            downstream_process_code="PK",
        )
    )
    snapshot.buffer_order_inventories.insert(
        0,
        AlgorithmBufferOrderInventory(
            main_id="MAIN-01",
            buffer_code="BUF-02",
            order_code="ORD-001",
            current_quantity=800,
        ),
    )

    result = _calculate(snapshot)[0]

    assert result.buffer_codes == ["BUF-01", "BUF-02"]
    assert result.buffer_code == "BUF-01"


def test_same_group_order_calculates_machine_rates_exactly_once(monkeypatch):
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
            main_id="MAIN-01",
            buffer_code="BUF-02",
            order_code="ORD-001",
            current_quantity=7200,
        )
    )
    calculator = net_rate_module.NetRateCalculator()
    original_upstream = calculator._calculate_upstream_output_rate
    original_downstream = calculator._calculate_downstream_input_rate
    calls = {"upstream": 0, "downstream": 0}

    def count_upstream(*args, **kwargs):
        calls["upstream"] += 1
        return original_upstream(*args, **kwargs)

    def count_downstream(*args, **kwargs):
        calls["downstream"] += 1
        return original_downstream(*args, **kwargs)

    monkeypatch.setattr(
        calculator,
        "_calculate_upstream_output_rate",
        count_upstream,
    )
    monkeypatch.setattr(
        calculator,
        "_calculate_downstream_input_rate",
        count_downstream,
    )

    results = calculator.calculate(snapshot)

    assert len(results) == 1
    assert calls == {"upstream": 1, "downstream": 1}


def test_different_main_ids_with_same_interval_and_order_stay_separate():
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
            main_id="MAIN-02",
            buffer_code="BUF-02",
            order_code="ORD-001",
            current_quantity=800,
        )
    )

    results = _calculate(snapshot)

    assert [
        (item.main_id, item.buffer_code, item.current_quantity)
        for item in results
    ] == [
        ("MAIN-01", "BUF-01", 1600),
        ("MAIN-02", "BUF-02", 800),
    ]


def test_different_orders_with_same_wafer_spec_are_not_aggregated():
    snapshot = _snapshot()
    snapshot.orders.append(_order("ORD-002"))
    snapshot.buffer_order_inventories.append(
        AlgorithmBufferOrderInventory(
            main_id="MAIN-01",
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


def test_same_order_multiple_agv_specs_selects_smallest_machine_code():
    snapshot = _snapshot()
    _add_machine(
        snapshot,
        "AA-R",
        "OX",
        agv_wafer_spec="R",
    )

    result = _calculate(snapshot)[0]

    assert result.wafer_spec == "R"
    assert result.upstream_output_rate == 0
    assert result.downstream_input_rate == 0


def test_order_wafer_spec_is_resolved_from_agv_without_current_runtime():
    snapshot = _snapshot()
    snapshot.machine_runtimes = []

    result = _calculate(snapshot)[0]

    assert result.wafer_spec == "N"
    assert result.upstream_output_rate == 0
    assert result.downstream_input_rate == 0


def test_stopped_runtime_does_not_contribute_to_agv_resolved_order():
    snapshot = _snapshot()
    for runtime in snapshot.machine_runtimes:
        runtime.status = "stopped"

    result = _calculate(snapshot)[0]

    assert result.wafer_spec == "N"
    assert result.upstream_output_rate == 0
    assert result.downstream_input_rate == 0


def test_inventory_order_without_effective_agv_relation_fails_without_line_fallback():
    snapshot = _snapshot()
    snapshot.agv_relations = []

    _assert_calculation_error(
        snapshot,
        r"ORD-001.*wafer_spec.*snapshot\.agv_relations.*effective AGV",
    )


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
        main_id="MAIN-01",
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


def test_net_rate_calculates_without_compatibility_line_data():
    snapshot = _snapshot()
    snapshot.lines = []
    snapshot.machine_lines = []

    result = _calculate(snapshot)[0]

    assert result.wafer_spec == "N"
    assert result.upstream_output_rate == 200
    assert result.downstream_input_rate == 320
    assert result.net_consumption_rate == 120


def test_net_rate_ignores_invalid_compatibility_line_relations():
    snapshot = _snapshot()
    snapshot.machine_lines[0] = AlgorithmMachineLineRelation(
        machine_code="ZR-01",
        line_code="UNKNOWN",
    )
    snapshot.machine_lines.append(
        AlgorithmMachineLineRelation(
            machine_code="ZR-01",
            line_code="LINE-N-S1",
        )
    )

    result = _calculate(snapshot)[0]

    assert result.net_consumption_rate == 120


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
