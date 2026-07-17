import re

import pytest

from app.adapters.snapshot_adapter import SnapshotAdapter
from app.schemas.request_schema import CutlineAlgorithmRequest
from tests.fixtures.v3_full_route_factory import (
    BUFFER_INTERVALS,
    PROCESS_CODES,
    V3_SCENARIO_BUILDERS,
    build_base_request_payload,
)


BUFFER_CODE_PATTERN = re.compile(r"^[0-9]+$")
MACHINE_CODE_PATTERN = re.compile(r"^EA[0-9]{3}$")
LINE_CODE_PATTERN = re.compile(r"^S2-SW[0-9]+[A-Z]$")


@pytest.fixture(params=sorted(V3_SCENARIO_BUILDERS))
def scenario_payload(request):
    return request.param, V3_SCENARIO_BUILDERS[request.param]()


def test_factory_returns_independent_deep_copies():
    first = build_base_request_payload()
    second = build_base_request_payload()

    first["orders"][0]["order_name"] = "已修改"
    first["process_routes"].reverse()

    assert second["orders"][0]["order_name"] == "至上"
    assert [item["process_code"] for item in second["process_routes"]] == list(
        PROCESS_CODES
    )


def test_all_scenarios_validate_and_convert_without_mutating_payload(
    scenario_payload,
):
    _, payload = scenario_payload
    request = CutlineAlgorithmRequest.model_validate(payload)
    before = request.model_dump()

    snapshot = SnapshotAdapter().to_algorithm_snapshot(request)

    assert snapshot.current_time == request.snapshot_meta.snapshot_time
    assert request.model_dump() == before


def test_all_scenarios_use_strict_eleven_step_route(scenario_payload):
    _, payload = scenario_payload
    routes = payload["process_routes"]

    assert [item["process_code"] for item in routes] == list(PROCESS_CODES)
    assert [item["process_name"] for item in routes] == list(PROCESS_CODES)
    assert [item["sequence"] for item in routes] == list(range(1, 12))
    assert all(item["loop_code"] == "S2-LOOP01" for item in routes)
    assert all(item["loop_name"] == "S2主工艺循环" for item in routes)

    for index, route in enumerate(routes):
        expected_upstream = PROCESS_CODES[index - 1] if index else None
        expected_downstream = (
            PROCESS_CODES[index + 1]
            if index + 1 < len(PROCESS_CODES)
            else None
        )
        assert route["upstream_process_code"] == expected_upstream
        assert route["upstream_process_name"] == expected_upstream
        assert route["downstream_process_code"] == expected_downstream
        assert route["downstream_process_name"] == expected_downstream


def test_all_scenarios_use_adjacent_numeric_buffers(scenario_payload):
    _, payload = scenario_payload
    expected_by_code = dict(BUFFER_INTERVALS)

    assert len(payload["buffer_master"]) == 10
    assert set(expected_by_code) == {
        item["buffer_code"] for item in payload["buffer_master"]
    }
    for buffer in payload["buffer_master"]:
        code = buffer["buffer_code"]
        upstream, downstream = expected_by_code[code]
        assert isinstance(code, str)
        assert BUFFER_CODE_PATTERN.fullmatch(code)
        assert buffer["served_process_codes"] == [upstream, downstream]
        assert buffer["served_process_names"] == [upstream, downstream]
        assert buffer["buffer_name"] == f"{upstream}-{downstream}Buffer"
        assert buffer["loop_code"] == "S2-LOOP01"

    known_codes = set(expected_by_code)
    for realtime in payload["buffer_realtime"]:
        assert isinstance(realtime["buffer_code"], str)
        assert BUFFER_CODE_PATTERN.fullmatch(realtime["buffer_code"])
        assert realtime["buffer_code"] in known_codes
    for relation in payload["agv_relations"]:
        if relation["buffer_code"] is not None:
            assert relation["buffer_code"] in known_codes


def test_all_scenarios_use_s2_lines_ea_machines_and_backend_statuses(
    scenario_payload,
):
    _, payload = scenario_payload
    lines = {item["line_code"]: item for item in payload["lines"]}

    assert payload["snapshot_meta"]["workshop_id"] == "S2"
    assert payload["workshops"] == [
        {"workshop_code": "S2", "workshop_name": "S2车间"}
    ]
    assert {item["wafer_spec"] for item in lines.values()} == {"N", "R", "P"}
    for line in lines.values():
        assert LINE_CODE_PATTERN.fullmatch(line["line_code"])
        assert line["line_code"] == f"S2-{line['line_name']}"
        assert line["workshop_code"] == "S2"

    machine_codes = {item["machine_code"] for item in payload["machine_master"]}
    assert machine_codes
    assert all(MACHINE_CODE_PATTERN.fullmatch(code) for code in machine_codes)
    assert all(
        item["machine_code"] in machine_codes
        and item["status"] in {"运行", "异常"}
        for item in payload["machine_realtime"]
    )
    assert all(
        item["machine_code"] in machine_codes
        and item["line_code"] in lines
        for item in payload["machine_lines"]
    )


def test_all_scenarios_use_unique_nonblank_order_names_and_exact_inventory_binding(
    scenario_payload,
):
    _, payload = scenario_payload
    names_by_workshop: dict[str, set[str]] = {}

    for order in payload["orders"]:
        assert order["order_name"].strip()
        workshop_names = names_by_workshop.setdefault(
            order["workshop_code"], set()
        )
        assert order["order_name"] not in workshop_names
        workshop_names.add(order["order_name"])

    valid_s2_names = names_by_workshop["S2"]
    assert all(
        item["bound_source_name"] in valid_s2_names
        for item in payload["buffer_realtime"]
    )


def test_all_scenarios_keep_wafer_size_and_spec_domains_separate(
    scenario_payload,
):
    _, payload = scenario_payload

    assert {item["wafer_size"] for item in payload["products"]} == {
        "182",
        "210",
    }
    assert {item["source_grade"] for item in payload["products"]} == {
        "A",
        "A-",
    }
    assert all(item["wafer_size"] not in {"N", "R", "P"} for item in payload["products"])
    assert all(item["wafer_spec"] not in {"182", "210"} for item in payload["lines"])


def test_all_scenario_references_resolve_to_master_data(scenario_payload):
    _, payload = scenario_payload
    machines = {item["machine_code"] for item in payload["machine_master"]}
    products = {item["product_code"] for item in payload["products"]}
    orders = {item["order_code"] for item in payload["orders"]}
    lines = {item["line_code"] for item in payload["lines"]}
    buffers = {item["buffer_code"] for item in payload["buffer_master"]}
    processes = {item["process_code"] for item in payload["process_routes"]}

    assert all(item["machine_code"] in machines for item in payload["machine_realtime"])
    assert all(
        not item["order_code"] or item["order_code"] in orders
        for item in payload["machine_realtime"]
    )
    assert all(
        item["machine_code"] in machines and item["line_code"] in lines
        for item in payload["machine_lines"]
    )
    assert all(
        item["machine_code"] in machines and item["product_code"] in products
        for item in payload["machine_process_times"]
    )
    assert all(item["product_code"] in products for item in payload["orders"])
    assert all(item["buffer_code"] in buffers for item in payload["buffer_realtime"])
    assert all(
        item["machine_code"] in machines
        and item["line_code"] in lines
        and (item["buffer_code"] is None or item["buffer_code"] in buffers)
        and (item["process_code"] is None or item["process_code"] in processes)
        for item in payload["agv_relations"]
    )
