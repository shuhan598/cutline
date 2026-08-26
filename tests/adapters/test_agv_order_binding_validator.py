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
                "machine_code": "P166-EA003",
                "status": "运行",
                "tangent_time": None,
                "input_quantity": 10,
                "output_quantity": 9,
            }
        ],
        "machine_master": [
            {
                "machine_code": "EA003",
                "p166_jt_group": "P166-EA003",
                "machine_name": "EA003制绒机",
                "process_code": "P-ZR",
                "process_name": "制绒",
            }
        ],
        "machine_process_times": [],
        "workshops": [
            {"workshop_code": "S1", "workshop_name": "一车间"},
            {"workshop_code": "S2", "workshop_name": "二车间"},
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
            },
            {
                "product_code": "PROD-2",
                "product_name": "产品二",
                "wafer_size": "210",
                "source_grade": "B",
                "material_code": "MAT-2",
                "material_name": "物料二",
            },
        ],
        "process_routes": [
            {
                "process_code": "P-ZR",
                "process_name": "制绒",
                "sequence": 1,
                "cache_type": "BUFFER",
                "workshop_code": "S1",
                "workshop_name": "一车间",
                "loop_code": "LOOP-1",
                "loop_name": "循环一",
                "upstream_process_code": None,
                "upstream_process_name": None,
                "downstream_process_code": None,
                "downstream_process_name": None,
            }
        ],
        "buffer_realtime": [],
        "buffer_master": [],
        "agv_relations": [
            {
                "equipmentid": "EA003",
                "equipmentname": "EA003制绒机",
                "linename": "产品一",
                "lastlinename": None,
                "waferspec": "N",
                "createtime": "2026-07-23 10:20:00",
            }
        ],
    }


def validate(source: dict):
    request = BackendRequestLoader().load_dict(source)
    return BackendRequestCompletenessValidator().validate(request)


def issues_for(result, dataset: str):
    return [issue for issue in result.issues if issue.dataset == dataset]


def add_valid_buffer(source: dict) -> None:
    source["process_routes"][0].update(
        downstream_process_code="P-NEXT",
        downstream_process_name="下一工序",
    )
    source["process_routes"].append(
        {
            "process_code": "P-NEXT",
            "process_name": "下一工序",
            "sequence": 2,
            "cache_type": "BUFFER",
            "workshop_code": "S1",
            "workshop_name": "一车间",
            "loop_code": "LOOP-1",
            "loop_name": "循环一",
            "upstream_process_code": "P-ZR",
            "upstream_process_name": "制绒",
            "downstream_process_code": None,
            "downstream_process_name": None,
        }
    )
    source["buffer_master"] = [
        {
            "buffer_code": "BUF-1",
            "buffer_name": "制绒下一工序Buffer",
            "buffer_type": "LINE",
            "buffer_type_title": "线边库",
            "max_capacity": 1000,
            "safety_low": 10,
            "served_process_codes": ["P-ZR", "P-NEXT"],
            "served_process_names": ["制绒", "下一工序"],
            "loop_code": "LOOP-1",
            "loop_name": "循环一",
        }
    ]
    source["buffer_realtime"] = [
        {
            "main_id": "MAIN-1",
            "buffer_code": "BUF-1",
            "bound_source_name": "产品一",
            "current_quantity": 100,
            "current_utilization_rate": 0.1,
        }
    ]


def test_validator_accepts_known_machine_and_product_binding():
    assert issues_for(validate(payload()), "agv_relations") == []
    assert not any(
        issue.dataset == "machine_realtime"
        and issue.code in {"missing_reference", "missing_agv_binding"}
        for issue in validate(payload()).issues
    )


def test_validator_reports_unknown_agv_equipmentid():
    source = payload()
    source["agv_relations"][0]["equipmentid"] = "UNKNOWN"

    result = validate(source)

    assert any(
        issue.code == "missing_reference"
        and issue.dataset == "agv_relations"
        and issue.field == "equipmentid"
        and issue.message.startswith("切线/混料-")
        and issue.message.endswith("字段引用记录不存在")
        for issue in result.issues
    )


def test_validator_reports_unknown_agv_linename():
    source = payload()
    source["agv_relations"][0]["linename"] = "未知产品"

    result = validate(source)

    assert any(
        issue.code == "missing_reference"
        and issue.dataset == "agv_relations"
        and issue.field == "linename"
        and issue.message.startswith("切线/混料-")
        and issue.message.endswith("字段引用记录不存在")
        for issue in result.issues
    )
    assert any(
        issue.code == "missing_agv_binding"
        and issue.record_key == "P166-EA003"
        for issue in result.issues
    )


def test_running_machine_without_any_agv_record_is_reported_after_mapping():
    source = payload()
    source["agv_relations"] = []

    result = validate(source)

    assert any(
        issue.code == "missing_agv_binding"
        and issue.dataset == "machine_realtime"
        and issue.field == "machine_code"
        and issue.record_key == "P166-EA003"
        and issue.message.startswith("切线/混料-")
        and issue.message.endswith("字段缺少有效 AGV 绑定")
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
        "linename",
        "lastlinename",
        "waferspec",
        "createtime",
    }
    assert not any(
        issue.dataset == "agv_relations"
        and issue.field in {"process_code", "process_name"}
        for issue in result.issues
    )


def test_validator_ignores_unknown_older_product_when_latest_is_valid():
    source = payload()
    older = dict(source["agv_relations"][0])
    older["linename"] = "未知产品"
    older["createtime"] = "2026-07-23 10:10:00"
    source["agv_relations"].insert(0, older)

    result = validate(source)

    assert not any(
        issue.dataset == "agv_relations" and issue.field == "linename"
        for issue in result.issues
    )


def test_validator_ignores_unknown_future_binding():
    source = payload()
    future = dict(source["agv_relations"][0])
    future["equipmentid"] = "UNKNOWN"
    future["linename"] = "未知产品"
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
        and issue.record_key == "P166-EA003"
        for issue in result.issues
    )


def test_validator_checks_selected_machine_name_against_master():
    source = payload()
    source["agv_relations"][0]["equipmentname"] = "错误机台名"

    result = validate(source)

    assert any(
        issue.code == "name_mismatch"
        and issue.dataset == "agv_relations"
        and issue.field == "equipmentname"
        for issue in result.issues
    )


def test_validator_reports_latest_same_time_linename_conflict():
    source = payload()
    conflict = dict(source["agv_relations"][0])
    conflict["linename"] = "产品二"
    source["agv_relations"].append(conflict)

    result = validate(source)

    assert any(
        issue.code == "binding_conflict"
        and issue.dataset == "agv_relations"
        and issue.field == "linename"
        and issue.message.startswith("切线/混料-")
        and issue.message.endswith("字段在同一时刻存在绑定冲突")
        for issue in result.issues
    )


def test_validator_reports_unknown_realtime_p166_code():
    source = payload()
    source["machine_realtime"][0]["machine_code"] = "P166-UNKNOWN"

    result = validate(source)

    assert any(
        issue.code == "missing_reference"
        and issue.dataset == "machine_realtime"
        and issue.field == "machine_code"
        and issue.message.startswith("切线/混料-")
        and issue.message.endswith("字段引用记录不存在")
        for issue in result.issues
    )


def test_validator_reports_agv_machine_order_workshop_conflict():
    source = payload()
    source["orders"][0]["workshop_code"] = "S2"
    source["orders"][0]["workshop_name"] = "二车间"

    result = validate(source)

    assert any(
        issue.code == "workshop_mismatch"
        and issue.dataset == "agv_relations"
        and issue.message.startswith("切线/混料-")
        and issue.message.endswith("所属车间不一致")
        for issue in result.issues
    )


def test_validator_defers_unknown_buffer_product_name_to_main_aggregator():
    source = payload()
    add_valid_buffer(source)
    source["buffer_realtime"][0]["bound_source_name"] = "未知产品"

    result = validate(source)

    assert not any(
        issue.dataset == "buffer_realtime"
        and issue.field == "bound_source_name"
        for issue in result.issues
    )


def test_validator_ignores_multi_value_buffer_bound_source_record():
    source = payload()
    add_valid_buffer(source)
    source["buffer_realtime"][0]["bound_source_name"] = (
        "111510111,111510112,111510211"
    )

    result = validate(source)

    assert not any(
        issue.dataset == "buffer_realtime"
        and issue.field == "bound_source_name"
        for issue in result.issues
    )


def test_validator_skips_all_checks_for_multi_value_buffer_record():
    source = payload()
    add_valid_buffer(source)
    source["buffer_realtime"][0].update(
        buffer_code="",
        bound_source_name="111510111,111510112",
    )

    result = validate(source)

    assert not any(
        issue.dataset == "buffer_realtime" for issue in result.issues
    )


def test_validator_defers_buffer_order_workshop_conflict_to_main_aggregator():
    source = payload()
    add_valid_buffer(source)
    source["orders"][0]["workshop_code"] = "S2"
    source["orders"][0]["workshop_name"] = "二车间"

    result = validate(source)

    assert not any(
        issue.dataset == "buffer_realtime"
        and issue.field == "bound_source_name"
        for issue in result.issues
    )
