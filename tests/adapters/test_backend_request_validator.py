import json
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest

from app.adapters.backend_request_loader import BackendRequestLoader
from app.adapters.backend_request_validator import (
    BackendRequestCompletenessValidator,
    BackendRequestValidationResult,
)
from app.core.workshop.process_loop_catalog import resolve_process_loop


ROOT = Path(__file__).resolve().parents[2]
SAMPLE_PATH = ROOT / "examples" / "backend_ingestion_request_sample.json"
REAL_SHAPE_PATH = ROOT / "docs" / "algo-request.json"


def sample_payload() -> dict:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


def validate_payload(payload: dict) -> BackendRequestValidationResult:
    request = BackendRequestLoader().load_dict(payload)
    return BackendRequestCompletenessValidator().validate(request)


def issue_counts(result: BackendRequestValidationResult) -> Counter:
    return Counter(issue.code for issue in result.issues)


def test_closed_sample_is_complete():
    result = validate_payload(sample_payload())

    assert result.valid is True
    assert result.issues == []


def test_validator_accepts_nonempty_persisted_event_id_lists():
    payload = sample_payload()
    payload["return_suggested_event_ids"] = ["CUT-RETURN-001"]
    payload["mixed_cutline_event_ids"] = ["CUT-MIXED-001"]

    result = validate_payload(payload)

    assert result.valid is True
    assert result.issues == []


def test_same_product_historical_order_does_not_make_current_order_ambiguous():
    payload = sample_payload()
    historical_order = deepcopy(payload["orders"][0])
    historical_order.update(
        {
            "order_code": "O-HISTORICAL",
            "order_status": "WAITING",
        }
    )
    payload["orders"].append(historical_order)

    result = validate_payload(payload)

    assert result.valid is True
    assert result.issues == []


def test_same_product_multiple_active_orders_are_allowed_for_buffer_mapping_but_agv_remains_strict():
    payload = sample_payload()
    second_active_order = deepcopy(payload["orders"][0])
    second_active_order.update(
        {
            "order_code": "O-ACTIVE-2",
            "order_status": "RUNNING",
        }
    )
    payload["orders"].append(second_active_order)

    result = validate_payload(payload)

    assert result.valid is False
    assert not any(
        issue.code == "duplicate_key"
        and issue.dataset == "orders"
        and issue.field == "product_name"
        for issue in result.issues
    )
    assert any(
        issue.code == "ambiguous_reference"
        and issue.dataset == "agv_relations"
        and issue.field == "linename"
        for issue in result.issues
    )


@pytest.mark.parametrize(
    "dataset",
    [
        "machine_realtime",
        "machine_master",
        "machine_process_times",
        "workshops",
        "orders",
        "products",
        "process_routes",
        "buffer_realtime",
        "buffer_master",
    ],
)
def test_required_empty_dataset_is_reported(dataset: str):
    payload = sample_payload()
    payload[dataset] = []

    result = validate_payload(payload)

    assert result.valid is False
    assert any(
        issue.code == "empty_dataset"
        and issue.dataset == dataset
        and issue.field is None
        for issue in result.issues
    )


@pytest.mark.parametrize(
    ("dataset", "field"),
    [
        ("workshops", "workshop_name"),
    ],
)
def test_required_nullable_business_fields_report_null(dataset: str, field: str):
    payload = sample_payload()
    payload[dataset][0][field] = None

    result = validate_payload(payload)

    assert any(
        issue.code == "null_field"
        and issue.dataset == dataset
        and issue.field == field
        for issue in result.issues
    )

@pytest.mark.parametrize(
    ("dataset", "field", "target_dataset"),
    [
        ("machine_realtime", "machine_code", "machine_master"),
        ("orders", "product_code", "products"),
        ("orders", "workshop_code", "workshops"),
        ("machine_process_times", "machine_code", "machine_master"),
        ("machine_process_times", "product_code", "products"),
    ],
)
def test_missing_references_are_reported(
    dataset: str,
    field: str,
    target_dataset: str,
):
    payload = sample_payload()
    payload[target_dataset] = []

    result = validate_payload(payload)

    assert any(
        issue.code == "missing_reference"
        and issue.dataset == dataset
        and issue.field == field
        for issue in result.issues
    )


def test_route_sequence_must_be_unique_within_workshop_not_loop():
    payload = sample_payload()
    payload["process_routes"][1]["loop_code"] = "LEGACY-OTHER-LOOP"
    payload["process_routes"][1]["sequence"] = 1

    result = validate_payload(payload)

    assert any(
        issue.code == "duplicate_sequence"
        and issue.dataset == "process_routes"
        and issue.field == "sequence"
        for issue in result.issues
    )


def test_validator_reports_unknown_process_name_with_existing_issue_shape():
    payload = sample_payload()
    route = payload["process_routes"][3]
    original_process_code = route["process_code"]
    route["process_name"] = "未知工序"

    result = validate_payload(payload)

    matching_issues = [
        issue
        for issue in result.issues
        if issue.code == "unknown_process_name"
    ]
    assert result.valid is False
    assert len(matching_issues) == 1
    issue = matching_issues[0]
    assert issue.dataset == "process_routes"
    assert issue.field == "process_name"
    assert issue.record_key == original_process_code
    assert issue.message == "工序名称无法映射到内部目录"


@pytest.mark.parametrize("loop_code", [None, "", "WRONG-LEGACY-LOOP"])
def test_validator_ignores_empty_or_wrong_process_route_loop_code(
    loop_code: str | None,
):
    payload = sample_payload()
    payload["process_routes"][0]["loop_code"] = loop_code

    result = validate_payload(payload)

    assert result.valid is True
    assert not any(
        issue.code == "empty_code"
        and issue.dataset == "process_routes"
        and issue.field == "loop_code"
        for issue in result.issues
    )


def test_buffer_main_id_null_is_deferred_to_main_buffer_aggregator():
    payload = sample_payload()
    payload["buffer_realtime"][0]["main_id"] = None

    result = validate_payload(payload)

    assert not any(
        issue.dataset == "buffer_realtime" and issue.field == "main_id"
        for issue in result.issues
    )


def test_buffer_static_reference_is_deferred_to_main_buffer_aggregator():
    payload = sample_payload()
    payload["buffer_realtime"][0]["buffer_code"] = "UNKNOWN-BUFFER"

    result = validate_payload(payload)

    assert not any(
        issue.dataset == "buffer_realtime" and issue.field == "buffer_code"
        for issue in result.issues
    )


def test_process_route_must_contain_silk_screen_process():
    payload = sample_payload()
    silk_route = next(
        route for route in payload["process_routes"]
        if route["process_name"] == "丝网"
    )
    silk_route["process_name"] = "后续工序"

    result = validate_payload(payload)

    assert any(
        issue.code == "missing_silk_screen_process"
        and issue.dataset == "process_routes"
        and issue.field == "process_name"
        and "S2" in str(issue.record_key)
        for issue in result.issues
    )


def test_process_route_cannot_contain_duplicate_silk_screen_processes():
    payload = sample_payload()
    payload["process_routes"][-2]["process_name"] = "丝网"

    result = validate_payload(payload)

    assert any(
        issue.code == "duplicate_silk_screen_process"
        and issue.dataset == "process_routes"
        and issue.field == "process_name"
        and "丝网" in issue.message
        for issue in result.issues
    )


def test_silk_screen_process_must_have_maximum_sequence():
    payload = sample_payload()
    payload["process_routes"][-2]["process_name"] = "丝网"
    payload["process_routes"][-1]["process_name"] = "后续工序"

    result = validate_payload(payload)

    assert any(
        issue.code == "silk_screen_not_last"
        and issue.dataset == "process_routes"
        and issue.field == "sequence"
        and "丝网" in issue.message
        for issue in result.issues
    )


def test_one_to_four_loops_do_not_each_require_silk_screen():
    payload = sample_payload()
    silk_route = next(
        route for route in payload["process_routes"]
        if route["process_name"] == "丝网"
    )
    silk_route["process_name"] = " 丝网 "
    previous_route = next(
        route for route in payload["process_routes"]
        if route["downstream_process_code"] == silk_route["process_code"]
    )
    previous_route["downstream_process_name"] = " 丝网 "
    for route in payload["process_routes"]:
        assignment = resolve_process_loop(route["process_name"])
        route["loop_code"] = assignment.loop_code
        route["loop_name"] = assignment.loop_name

    result = validate_payload(payload)

    assert result.valid is True
    assert result.issues == []


def test_non_consecutive_unique_route_sequences_are_allowed():
    payload = sample_payload()
    for index, route in enumerate(payload["process_routes"], start=1):
        route["sequence"] = index * 10

    result = validate_payload(payload)

    assert result.valid is True
    assert result.issues == []


def test_cross_loop_route_edges_are_valid_within_one_workshop():
    payload = sample_payload()
    process_names = (
        "发料机",
        "制绒",
        "硼扩",
        "氧化",
        "碱抛",
        "POLY",
        "退火",
        "RCA",
        "ALD",
        "正膜",
        "背膜",
        "丝网",
    )
    routes = payload["process_routes"]
    for index, (route, process_name) in enumerate(
        zip(routes, process_names, strict=True),
    ):
        previous = process_names[index - 1] if index else None
        following = (
            process_names[index + 1]
            if index + 1 < len(process_names)
            else None
        )
        assignment = resolve_process_loop(process_name)
        route.update(
            {
                "process_name": process_name,
                "sequence": (index + 1) * 10,
                "loop_code": assignment.loop_code,
                "loop_name": assignment.loop_name,
                "upstream_process_name": previous,
                "downstream_process_name": following,
            }
        )

    result = validate_payload(payload)

    assert any(
        route["process_name"] == "氧化"
        and route["downstream_process_name"] == "碱抛"
        for route in routes
    )
    assert any(
        route["process_name"] == "RCA"
        and route["downstream_process_name"] == "ALD"
        for route in routes
    )
    assert result.valid is True
    assert result.issues == []


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("upstream_process_code", "碱抛"),
        ("upstream_process_name", "碱抛"),
        ("downstream_process_code", "发料机"),
        ("downstream_process_name", "发料机"),
    ],
)
def test_route_neighbor_fields_must_match_sorted_adjacency(
    field: str,
    invalid_value: str,
):
    payload = sample_payload()
    payload["process_routes"][1][field] = invalid_value

    result = validate_payload(payload)

    assert any(
        issue.code == "broken_process_route"
        and issue.dataset == "process_routes"
        and issue.field == field
        and "sequence:2" in str(issue.record_key)
        for issue in result.issues
    )


def test_first_process_upstream_fields_must_be_empty():
    payload = sample_payload()
    first = payload["process_routes"][0]
    first["upstream_process_code"] = payload["process_routes"][1][
        "process_code"
    ]
    first["upstream_process_name"] = payload["process_routes"][1][
        "process_name"
    ]

    result = validate_payload(payload)

    assert {
        issue.field
        for issue in result.issues
        if issue.code == "broken_process_route"
    } >= {"upstream_process_code", "upstream_process_name"}


def test_last_silk_screen_downstream_fields_must_be_empty():
    payload = sample_payload()
    last = payload["process_routes"][-1]
    last["downstream_process_code"] = payload["process_routes"][-2][
        "process_code"
    ]
    last["downstream_process_name"] = payload["process_routes"][-2][
        "process_name"
    ]

    result = validate_payload(payload)

    assert {
        issue.field
        for issue in result.issues
        if issue.code == "invalid_last_process_downstream"
    } == {"downstream_process_code", "downstream_process_name"}


def test_route_validation_keeps_workshop_groups_isolated():
    payload = sample_payload()
    second_group = deepcopy(payload["process_routes"])
    for route in second_group:
        route["workshop_code"] = "S3"
        route["workshop_name"] = "S3车间"
        route["loop_code"] = "S3-LOOP01"
        route["loop_name"] = "S3主工艺循环"
        route["process_code"] = f"S3-{route['process_code']}"
        if route["upstream_process_code"] is not None:
            route["upstream_process_code"] = (
                f"S3-{route['upstream_process_code']}"
            )
        if route["downstream_process_code"] is not None:
            route["downstream_process_code"] = (
                f"S3-{route['downstream_process_code']}"
            )
    payload["workshops"].append(
        {"workshop_code": "S3", "workshop_name": "S3车间"}
    )
    payload["process_routes"].extend(second_group)

    result = validate_payload(payload)

    assert result.valid is True
    assert result.issues == []


def test_non_edge_route_null_and_unknown_neighbors_are_reported():
    payload = sample_payload()
    middle = deepcopy(payload["process_routes"][0])
    middle.update(
        {
            "process_code": "P-MID",
            "process_name": "中间工序",
            "sequence": 2,
            "upstream_process_code": None,
            "upstream_process_name": None,
            "downstream_process_code": "P-UNKNOWN",
            "downstream_process_name": "未知",
        }
    )
    payload["process_routes"][1]["sequence"] = 3
    payload["process_routes"].insert(1, middle)

    result = validate_payload(payload)

    assert any(
        issue.code == "null_field"
        and issue.dataset == "process_routes"
        and issue.field == "upstream_process_code"
        for issue in result.issues
    )
    assert any(
        issue.code == "missing_reference"
        and issue.dataset == "process_routes"
        and issue.field == "downstream_process_code"
        for issue in result.issues
    )


def test_served_process_code_must_exist_globally():
    payload = sample_payload()
    payload["buffer_master"][0]["served_process_codes"][1] = "P-UNKNOWN"

    result = validate_payload(payload)

    assert any(
        issue.code == "missing_reference"
        and issue.dataset == "buffer_master"
        and issue.field == "served_process_codes[1]"
        for issue in result.issues
    )


def test_buffer_served_process_reference_does_not_depend_on_buffer_loop():
    payload = sample_payload()
    payload["buffer_master"][0]["loop_code"] = "WRONG-LEGACY-LOOP"

    result = validate_payload(payload)

    assert result.valid is True
    assert not any(
        issue.code == "missing_reference"
        and issue.dataset == "buffer_master"
        and issue.field.startswith("served_process_codes[")
        for issue in result.issues
    )


def test_real_api_sample_loads_but_reports_incomplete_inputs():
    payload = json.loads(REAL_SHAPE_PATH.read_text(encoding="utf-8"))

    request = BackendRequestLoader().load_dict(payload)
    result = BackendRequestCompletenessValidator().validate(request)

    assert len(request.machine_realtime) == 439
    assert result.valid is False
    assert issue_counts(result) == {
        "empty_dataset": 6,
        "null_field": 1,
        "missing_reference": 439,
        "missing_agv_binding": 138,
    }
    assert not any(
        issue.dataset == "buffer_realtime"
        for issue in result.issues
    )


def test_backend_request_symbols_are_available_from_package_exports():
    from app.adapters import (
        BackendRequestCompletenessValidator as ExportedValidator,
    )
    from app.adapters import BackendRequestLoader as ExportedLoader
    from app.schemas import BackendAlgorithmRequest as ExportedRequest

    assert ExportedLoader is BackendRequestLoader
    assert ExportedValidator is BackendRequestCompletenessValidator
    assert ExportedRequest.__name__ == "BackendAlgorithmRequest"
