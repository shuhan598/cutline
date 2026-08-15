import re

import pytest

from app.adapters.backend_request_loader import BackendRequestLoader
from app.adapters.snapshot_adapter import SnapshotAdapter
from tests.fixtures.v3_full_route_factory import (
    BUFFER_INTERVALS,
    MACHINE_CODES_BY_PROCESS,
    MULTILAYER_BUFFER_CODES,
    PROCESS_CODES,
    SUPPORT_BUFFER_CODE,
    TARGET_BUFFER_CODE,
    V3_SCENARIO_BUILDERS,
    _set_agv_binding,
    build_base_request_payload,
)


BUFFER_CODE_PATTERN = re.compile(r"^[0-9]+$")
MACHINE_CODE_PATTERN = re.compile(r"^EA[0-9]{3}$")
LINE_CODE_PATTERN = re.compile(r"^S2-SW[0-9]+[A-Z]$")

EXPECTED_LOOP_BY_PROCESS = {
    "发料机": ("LOOP1", "一循环"),
    "制绒": ("LOOP2", "二循环"),
    "硼扩": ("LOOP2", "二循环"),
    "氧化": ("LOOP2", "二循环"),
    "碱抛": ("LOOP3", "三循环"),
    "POLY": ("LOOP3", "三循环"),
    "退火": ("LOOP3", "三循环"),
    "RCA": ("LOOP4", "四循环"),
    "ALD": ("LOOP5", "五循环"),
    "正膜": ("LOOP5", "五循环"),
    "背膜": ("LOOP5", "五循环"),
    "丝网": ("LOOP5", "五循环"),
}

EXPECTED_MACHINE_CODES_BY_PROCESS = {
    "发料机": ("EA001", "EA002"),
    "制绒": ("EA003", "EA004"),
    "碱抛": ("EA005", "EA006"),
    "背膜": ("EA007", "EA008"),
    "硼扩": ("EA009", "EA010"),
    "POLY": ("EA011", "EA012"),
    "RCA": ("EA013", "EA014"),
    "退火": ("EA015", "EA016"),
    "氧化": ("EA017", "EA018"),
    "正膜": ("EA019", "EA020"),
    "丝网": ("EA021", "EA022"),
    "ALD": ("EA025", "EA026"),
}


@pytest.fixture(params=sorted(V3_SCENARIO_BUILDERS))
def scenario_payload(request):
    return request.param, V3_SCENARIO_BUILDERS[request.param]()


def test_factory_returns_independent_deep_copies():
    first = build_base_request_payload()
    second = build_base_request_payload()

    first["orders"][0]["product_name"] = "已修改"
    first["process_routes"].reverse()

    assert second["orders"][0]["product_name"] == "182N至上产品"
    assert [item["process_code"] for item in second["process_routes"]] == list(
        PROCESS_CODES
    )


def test_base_factory_explicitly_starts_without_pending_or_active_events():
    payload = build_base_request_payload()

    assert payload["pending_cutline_plans"] == []
    assert payload["active_cutline_events"] == []


def test_shared_factory_retains_complete_legacy_line_data():
    payload = build_base_request_payload()
    lines = {item["line_code"] for item in payload["lines"]}

    assert lines
    assert payload["machine_lines"]
    assert all(
        item["machine_code"]
        in {machine["machine_code"] for machine in payload["machine_master"]}
        and item["line_code"] in lines
        for item in payload["machine_lines"]
    )


def test_shared_factory_uses_twelve_processes_and_stable_machine_codes():
    assert len(PROCESS_CODES) == 12
    assert PROCESS_CODES[PROCESS_CODES.index("氧化") + 1] == "ALD"
    assert PROCESS_CODES[PROCESS_CODES.index("ALD") + 1] == "正膜"
    assert MACHINE_CODES_BY_PROCESS == EXPECTED_MACHINE_CODES_BY_PROCESS
    assert MACHINE_CODES_BY_PROCESS["丝网"] == ("EA021", "EA022")
    assert MACHINE_CODES_BY_PROCESS["ALD"] == ("EA025", "EA026")

    payload = build_base_request_payload()
    process_by_machine = {
        item["machine_code"]: item["process_code"]
        for item in payload["machine_master"]
    }
    assert process_by_machine["EA023"] == "制绒"
    assert process_by_machine["EA024"] == "制绒"


def test_shared_factory_adds_only_the_required_ald_buffer_interval():
    intervals = dict(BUFFER_INTERVALS)

    assert len(intervals) == 11
    assert intervals["310110309"] == ("氧化", "ALD")
    assert intervals["310110310"] == ("正膜", "丝网")
    assert intervals["310110311"] == ("ALD", "正膜")
    assert TARGET_BUFFER_CODE == "310110302"


def test_all_scenarios_validate_and_convert_without_mutating_payload(
    scenario_payload,
):
    _, payload = scenario_payload
    request = BackendRequestLoader().load_cutline_dict(payload)
    before = request.model_dump()

    snapshot = SnapshotAdapter().to_algorithm_snapshot(request)

    assert snapshot.current_time == request.snapshot_meta.snapshot_time
    assert request.model_dump() == before


def test_all_scenarios_use_backend_sequence_and_internal_five_loop_route(
    scenario_payload,
):
    _, payload = scenario_payload
    routes = payload["process_routes"]
    request = BackendRequestLoader().load_cutline_dict(payload)
    snapshot = SnapshotAdapter().to_algorithm_snapshot(request)

    assert [item["process_code"] for item in routes] == list(PROCESS_CODES)
    assert [item["process_name"] for item in routes] == list(PROCESS_CODES)
    assert [item["sequence"] for item in routes] == list(range(1, 13))
    assert all(item["loop_code"] == "S2-LOOP01" for item in routes)
    assert all(item["loop_name"] == "S2主工艺循环" for item in routes)
    assert [item.sequence for item in snapshot.process_routes] == [
        item["sequence"] for item in routes
    ]
    assert [
        (item.loop_code, item.loop_name) for item in snapshot.process_routes
    ] == [EXPECTED_LOOP_BY_PROCESS[item] for item in PROCESS_CODES]

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


def test_all_scenarios_use_sequence_directed_numeric_buffers(scenario_payload):
    scenario_name, payload = scenario_payload
    request = BackendRequestLoader().load_cutline_dict(payload)
    snapshot = SnapshotAdapter().to_algorithm_snapshot(request)
    route_sequence = {
        item.process_code: item.sequence for item in snapshot.process_routes
    }
    relations = {
        item.buffer_code: item for item in snapshot.buffer_process_relations
    }
    expected_by_code = dict(BUFFER_INTERVALS)
    if scenario_name == "v3_buffer_main_id_grouping":
        expected_by_code.update(
            {
                buffer_code: expected_by_code[TARGET_BUFFER_CODE]
                for buffer_code in MULTILAYER_BUFFER_CODES
            }
        )
    if any(
        item["buffer_code"] == SUPPORT_BUFFER_CODE
        for item in payload["buffer_master"]
    ):
        expected_by_code[SUPPORT_BUFFER_CODE] = expected_by_code[
            TARGET_BUFFER_CODE
        ]

    assert len(payload["buffer_master"]) == len(expected_by_code)
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
        relation = relations[code]
        assert relation.upstream_process_code == upstream
        assert relation.downstream_process_code == downstream
        assert route_sequence[upstream] < route_sequence[downstream]

    known_codes = set(expected_by_code)
    for realtime in payload["buffer_realtime"]:
        assert isinstance(realtime["buffer_code"], str)
        assert BUFFER_CODE_PATTERN.fullmatch(realtime["buffer_code"])
        assert realtime["buffer_code"] in known_codes


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
    realtime_codes = {
        item["p166_jt_group"] for item in payload["machine_master"]
    }
    assert machine_codes
    assert all(MACHINE_CODE_PATTERN.fullmatch(code) for code in machine_codes)
    assert len(realtime_codes) == len(machine_codes)
    assert realtime_codes.isdisjoint(machine_codes)
    assert all(
        item["machine_code"] in realtime_codes
        and item["status"] in {"运行", "异常"}
        and "order_code" not in item
        for item in payload["machine_realtime"]
    )
    assert all(
        item["machine_code"] in machine_codes
        and item["line_code"] in lines
        for item in payload["machine_lines"]
    )


def test_all_scenarios_use_unique_nonblank_product_names_and_exact_inventory_binding(
    scenario_payload,
):
    _, payload = scenario_payload
    product_names: set[str] = set()

    for order in payload["orders"]:
        assert "order_name" not in order
        assert order["product_name"].strip()
        assert order["product_name"] not in product_names
        product_names.add(order["product_name"])

    assert all(
        item["bound_source_name"] in product_names
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
    standard_by_realtime = {
        item["p166_jt_group"]: item["machine_code"]
        for item in payload["machine_master"]
    }
    products = {item["product_code"] for item in payload["products"]}
    product_names = {item["product_name"] for item in payload["products"]}
    current_product_names = {
        item["product_name"] for item in payload["orders"]
    }
    lines = {item["line_code"] for item in payload["lines"]}
    buffers = {item["buffer_code"] for item in payload["buffer_master"]}
    assert all(
        item["machine_code"] in standard_by_realtime
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
        set(item)
        == {
            "equipmentid",
            "equipmentname",
            "linename",
            "lastlinename",
            "waferspec",
            "createtime",
        }
        and item["equipmentid"] in machines
        and item["linename"] in product_names
        and item["linename"] in current_product_names
        and item["waferspec"] in {"N", "R", "P"}
        for item in payload["agv_relations"]
    )
    assert any(
        item["lastlinename"] is None for item in payload["agv_relations"]
    )

    bound_machines = {
        item["equipmentid"] for item in payload["agv_relations"]
    }
    assert all(
        runtime["status"] != "运行"
        or standard_by_realtime[runtime["machine_code"]] in bound_machines
        for runtime in payload["machine_realtime"]
    )


def test_agv_process_fields_cannot_override_machine_master(scenario_payload):
    _, payload = scenario_payload

    request = BackendRequestLoader().load_cutline_dict(payload)
    snapshot = SnapshotAdapter().to_algorithm_snapshot(request)
    process_by_machine = {
        item["machine_code"]: item["process_code"]
        for item in payload["machine_master"]
    }

    assert all(
        machine.process_code == process_by_machine[machine.machine_code]
        for machine in snapshot.machine_masters
    )
    assert all(
        "processcode" not in relation and "processname" not in relation
        for relation in payload["agv_relations"]
    )


def test_agv_binding_factory_allows_explicit_backend_field_overrides():
    payload = build_base_request_payload()

    _set_agv_binding(
        payload,
        machine_code="EA001",
        order_code="ORD-S2-003",
        product_name="显式产品名",
        previous_product_name="上一产品名",
        wafer_spec="R",
        binding_time="2026-07-17 07:59:00",
    )

    relation = next(
        item
        for item in payload["agv_relations"]
        if item["equipmentid"] == "EA001"
    )
    assert relation == {
        "equipmentid": "EA001",
        "equipmentname": "EA001发料机",
        "linename": "显式产品名",
        "lastlinename": "上一产品名",
        "waferspec": "R",
        "createtime": "2026-07-17 07:59:00",
    }
