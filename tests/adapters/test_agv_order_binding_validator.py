from app.adapters.backend_request_loader import BackendRequestLoader
from app.adapters.backend_request_validator import (
    BackendRequestCompletenessValidator,
)


def payload() -> dict:
    return {
        "snapshot_meta": {
            "run_id": "run-1",
            "trigger_type": "manual",
            "workshop_id": "S1",
            "snapshot_time": "2026-07-23T10:30:00+08:00",
            "params_version": 1,
            "catalog_version": "catalog-1",
            "catalog_loaded_at": "2026-07-23T10:00:00+08:00",
            "degraded_flags": [],
        },
        "machine_realtime": [
            {
                "machine_code": "EA003",
                "status": "运行",
                "tangent_time": None,
                "input_quantity": 10,
                "output_quantity": 9,
                "completed_quantity": 100,
            }
        ],
        "machine_master": [
            {
                "machine_code": "EA003",
                "machine_name": "EA003制绒机",
                "process_code": "P-ZR",
                "process_name": "制绒",
            }
        ],
        "machine_process_times": [],
        "workshops": [
            {"workshop_code": "S1", "workshop_name": "一车间"}
        ],
        "lines": [],
        "machine_lines": [],
        "orders": [
            {
                "order_code": "ORD-S2-001",
                "order_status": "生产中",
                "total_quantity": 1000,
                "piece_source": "A",
                "estimated_yield": "99%",
                "product_code": "PROD-1",
                "product_name": "产品一",
                "workshop_code": "S1",
                "workshop_name": "一车间",
                "produced_quantity": 100,
                "remaining_quantity": 900,
            }
        ],
        "products": [
            {
                "product_code": "PROD-1",
                "product_name": "产品一",
                "wafer_size": "182",
                "source_grade": "A",
                "material_code": "MAT-1",
                "material_name": "物料一",
            }
        ],
        "process_routes": [],
        "buffer_realtime": [],
        "buffer_master": [],
        "agv_relations": [
            {
                "equipmentid": "EA003",
                "equipmentname": "EA003制绒机",
                "lastlinecode": "ORD-S2-001",
                "lastlinename": "至上",
                "createtime": "2026-07-23 10:20:00",
            }
        ],
    }


def validate(source: dict):
    request = BackendRequestLoader().load_dict(source)
    return BackendRequestCompletenessValidator().validate(request)


def agv_issues(result):
    return [
        issue
        for issue in result.issues
        if issue.dataset == "agv_relations"
    ]


def test_validator_accepts_known_agv_machine_and_order_codes():
    assert agv_issues(validate(payload())) == []


def test_validator_reports_unknown_agv_machine_code():
    source = payload()
    source["agv_relations"][0]["equipmentid"] = "UNKNOWN"

    result = validate(source)

    assert any(
        issue.code == "missing_reference"
        and issue.dataset == "agv_relations"
        and issue.field == "machine_code"
        for issue in result.issues
    )


def test_validator_reports_unknown_agv_order_code():
    source = payload()
    source["agv_relations"][0]["lastlinecode"] = "UNKNOWN"

    result = validate(source)

    assert any(
        issue.code == "missing_reference"
        and issue.dataset == "agv_relations"
        and issue.field == "order_code"
        for issue in result.issues
    )


def test_running_machine_without_any_agv_record_is_reported():
    source = payload()
    source["agv_relations"] = []

    result = validate(source)

    assert any(
        issue.code == "missing_agv_binding"
        and issue.dataset == "machine_realtime"
        and issue.field == "machine_code"
        and issue.record_key == "EA003"
        for issue in result.issues
    )


def test_stopped_machine_without_agv_record_is_allowed():
    source = payload()
    source["machine_realtime"][0]["status"] = "停机"
    source["agv_relations"] = []

    result = validate(source)

    assert not any(
        issue.code == "missing_agv_binding" for issue in result.issues
    )


def test_agv_process_fields_are_filtered_and_never_validated():
    source = payload()
    source["agv_relations"][0].update(
        {
            "processcode": "NOT-IN-ROUTES",
            "processname": "错误工序",
        }
    )

    request = BackendRequestLoader().load_dict(source)
    result = BackendRequestCompletenessValidator().validate(request)

    assert set(request.agv_relations[0].__class__.model_fields) == {
        "equipmentid",
        "equipmentname",
        "lastlinecode",
        "lastlinename",
        "createtime",
    }
    assert not any(
        issue.field in {"process_code", "process_name"}
        for issue in result.issues
    )


def test_validator_ignores_unknown_older_binding_when_latest_is_valid():
    source = payload()
    older = dict(source["agv_relations"][0])
    older["lastlinecode"] = "UNKNOWN"
    older["createtime"] = "2026-07-23 10:10:00"
    source["agv_relations"].insert(0, older)

    result = validate(source)

    assert not any(
        issue.dataset == "agv_relations"
        and issue.field == "order_code"
        for issue in result.issues
    )


def test_validator_ignores_unknown_future_binding():
    source = payload()
    future = dict(source["agv_relations"][0])
    future["equipmentid"] = "UNKNOWN"
    future["lastlinecode"] = "UNKNOWN"
    future["createtime"] = "2026-07-23 10:40:00"
    source["agv_relations"].append(future)

    result = validate(source)

    assert not any(
        issue.dataset == "agv_relations" for issue in result.issues
    )


def test_validator_treats_only_future_binding_as_missing_for_running_machine():
    source = payload()
    source["agv_relations"][0]["createtime"] = "2026-07-23 10:40:00"

    result = validate(source)

    assert any(
        issue.code == "missing_agv_binding"
        and issue.record_key == "EA003"
        for issue in result.issues
    )


def test_validator_checks_selected_machine_name_against_master():
    source = payload()
    source["agv_relations"][0]["equipmentname"] = "错误机台名"

    result = validate(source)

    assert any(
        issue.code == "name_mismatch"
        and issue.dataset == "agv_relations"
        and issue.field == "machine_name"
        for issue in result.issues
    )


def test_validator_reports_latest_same_time_order_conflict():
    source = payload()
    conflict = dict(source["agv_relations"][0])
    conflict["lastlinecode"] = "ORD-S2-002"
    conflict["lastlinename"] = "另一订单"
    source["agv_relations"].append(conflict)

    result = validate(source)

    assert any(
        issue.code == "binding_conflict"
        and issue.dataset == "agv_relations"
        and issue.field == "order_code"
        for issue in result.issues
    )
