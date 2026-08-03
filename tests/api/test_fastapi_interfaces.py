import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.cutline_api as cutline_api_module
from app.api.cutline_api import get_cutline_service
from app.main import create_app
from app.schemas.backend_request_schema import BackendAlgorithmRequest
from app.schemas.request_schema import CutlineAlgorithmRequest
from app.schemas.response_schema import (
    CutlineAlgorithmResponse,
    CutlineEvaluateResponse,
    PersistenceStateResponse,
)
from tests.fixtures.v3_full_route_factory import build_stockout_auto_payload


ROOT = Path(__file__).resolve().parents[2]
BACKEND_SAMPLE_PATH = ROOT / "examples" / "backend_ingestion_request_sample.json"


def backend_payload() -> dict:
    return json.loads(BACKEND_SAMPLE_PATH.read_text(encoding="utf-8"))


def cutline_payload() -> dict:
    return {
        "snapshot_meta": {
            "run_id": "run-1",
            "trigger_type": "manual",
            "workshop_id": "S1",
            "snapshot_time": "2026-07-13T16:21:55Z",
            "params_version": 3,
            "catalog_version": "foundation",
            "catalog_loaded_at": "2026-07-13T16:21:23Z",
            "degraded_flags": [],
        },
        "machine_realtime": [
            {
                "machine_code": "P166-M1",
                "status": "运行",
                "tangent_time": None,
                "input_quantity": 0,
                "output_quantity": 1,
                "out_time": "2026-07-13T08:00:00Z",
            }
        ],
        "machine_master": [
            {
                "machine_code": "M1",
                "p166_jt_group": "P166-M1",
                "machine_name": "机台1",
                "process_code": "P1",
                "process_name": "工序1",
            }
        ],
        "machine_process_times": [
            {
                "machine_code": "M1",
                "machine_name": "机台1",
                "product_code": "PR1",
                "product_name": "产品1",
                "proc_seconds": 1,
                "actual_capacity": 1,
            }
        ],
        "workshops": [{"workshop_code": "S1", "workshop_name": None}],
        "lines": [
            {
                "line_code": "L1",
                "line_name": "产线1",
                "wafer_spec": "182",
                "workshop_code": "S1",
                "workshop_name": "车间1",
            }
        ],
        "machine_lines": [
            {
                "machine_code": "M1",
                "machine_name": "机台1",
                "line_code": "L1",
                "line_name": "产线1",
                "wafer_spec": "182",
            }
        ],
        "orders": [
            {
                "order_code": "O1",
                "order_status": "open",
                "total_quantity": 10,
                "piece_source": "A",
                "estimated_yield": "99%",
                "product_code": "PR1",
                "product_name": "产品1",
                "workshop_code": "S1",
                "workshop_name": "车间1",
                "produced_quantity": 1,
                "remaining_quantity": 9,
            }
        ],
        "products": [
            {
                "product_code": "PR1",
                "product_name": "产品1",
                "wafer_size": "182",
                "source_grade": "A",
                "material_code": "MAT1",
                "material_name": "物料1",
            }
        ],
        "process_routes": [
            {
                "process_code": "P1",
                "process_name": "工序1",
                "sequence": 1,
                "cache_type": "BUFFER",
                "workshop_code": "S1",
                "workshop_name": "车间1",
                "loop_code": "LOOP1",
                "loop_name": "循环1",
                "upstream_process_code": None,
                "upstream_process_name": None,
                "downstream_process_code": None,
                "downstream_process_name": None,
            }
        ],
        "buffer_realtime": [
            {
                "main_id": None,
                "buffer_code": "B1",
                "bound_source_name": "产品1",
                "current_quantity": 0,
                "current_utilization_rate": 0,
            }
        ],
        "buffer_master": [
            {
                "buffer_code": "B1",
                "buffer_name": "缓存1",
                "buffer_type": "LINE",
                "buffer_type_title": "线边库",
                "max_capacity": 1,
                "safety_low": 0,
                "served_process_codes": [],
                "served_process_names": [],
                "loop_code": "LOOP1",
                "loop_name": "循环1",
            }
        ],
        "agv_relations": [
            {
                "equipmentid": "M1",
                "equipmentname": "机台1",
                "linename": "产品1",
                "lastlinename": "source",
                "waferspec": "N",
                "createtime": "2026-07-13 16:20:00",
                "processcode": "DO-NOT-USE",
                "processname": "错误工序",
            }
        ],
    }


def make_client() -> TestClient:
    app = create_app()
    return TestClient(app)


def test_health_endpoint_returns_ok():
    response = make_client().get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_backend_validate_accepts_transitional_backend_payload():
    payload = backend_payload()
    payload["machine_realtime"][0]["out_time"] = "2026-07-14T08:30:00+08:00"

    response = make_client().post("/backend/validate", json=payload)

    assert response.status_code == 200
    assert response.json() == {"valid": True, "issues": []}


@pytest.mark.parametrize("field", ("completed_quantity", "period_quantity"))
def test_backend_validate_rejects_removed_runtime_fields(field: str):
    payload = backend_payload()
    payload["machine_realtime"][0][field] = 10

    response = make_client().post("/backend/validate", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == [
        "machine_realtime",
        0,
        field,
    ]
    assert response.json()["detail"][0]["type"] == "extra_forbidden"


@pytest.mark.parametrize("line_input_mode", ["omitted", "empty"])
def test_backend_validate_accepts_optional_line_collections(
    line_input_mode: str,
):
    payload = backend_payload()
    if line_input_mode == "omitted":
        payload.pop("lines", None)
        payload.pop("machine_lines", None)
    else:
        payload["lines"] = []
        payload["machine_lines"] = []

    response = make_client().post("/backend/validate", json=payload)

    assert response.status_code == 200
    assert response.json() == {"valid": True, "issues": []}


def test_backend_validate_uses_raw_agv_mapping_and_ignores_process_fields():
    payload = backend_payload()
    payload["agv_relations"][0].update(
        {
            "processcode": "DO-NOT-USE",
            "processname": "错误工序",
            "equipmentcode": "WRONG-MACHINE",
        }
    )

    response = make_client().post("/backend/validate", json=payload)

    assert response.status_code == 200
    assert response.json() == {"valid": True, "issues": []}


def test_backend_validate_returns_business_issues_as_successful_response():
    payload = backend_payload()
    payload["orders"] = []

    response = make_client().post("/backend/validate", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert any(
        issue["code"] == "empty_dataset" and issue["dataset"] == "orders"
        for issue in body["issues"]
    )


def test_backend_validate_rejects_unknown_fields_with_422():
    payload = backend_payload()
    payload["unexpected"] = True

    response = make_client().post("/backend/validate", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "extra_forbidden"


def test_cutline_evaluate_delegates_to_cutline_service():
    app = create_app()
    calls = []
    payload = build_stockout_auto_payload()

    class StubService:
        def evaluate_algorithm(self, request: CutlineAlgorithmRequest):
            calls.append(request)
            return CutlineEvaluateResponse(
                calculation_time=datetime(2026, 7, 18, 12, 0),
                persistence_state=PersistenceStateResponse(
                    completed_pending_plan_ids=["PLAN-DONE"]
                ),
            )

    app.dependency_overrides[get_cutline_service] = StubService
    client = TestClient(app)

    response = client.post("/cutline/evaluate", json=payload)

    assert response.status_code == 200
    assert response.json()["calculation_time"] == "2026-07-18T12:00:00"
    assert response.json()["persistence_state"][
        "completed_pending_plan_ids"
    ] == ["PLAN-DONE"]
    assert len(calls) == 1
    assert isinstance(calls[0], CutlineAlgorithmRequest)
    assert calls[0].machine_realtime[0].machine_code == (
        payload["machine_realtime"][0]["machine_code"]
    )
    assert calls[0].agv_relations[0].machine_code == (
        payload["agv_relations"][0]["equipmentid"]
    )
    assert calls[0].agv_relations[0].product_name == (
        payload["agv_relations"][0]["linename"]
    )
    assert calls[0].agv_relations[0].wafer_spec == (
        payload["agv_relations"][0]["waferspec"]
    )
    assert calls[0].machine_master[0].process_code == (
        payload["machine_master"][0]["process_code"]
    )


@pytest.mark.parametrize("field", ("completed_quantity", "period_quantity"))
def test_cutline_evaluate_rejects_removed_runtime_fields(field: str):
    payload = build_stockout_auto_payload()
    payload["machine_realtime"][0][field] = 10

    response = make_client().post("/cutline/evaluate", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "BACKEND_DATA_INVALID"
    assert any(
        issue["code"] == "extra_forbidden"
        and issue["dataset"] == "machine_realtime"
        and issue["field"] == field
        and issue["record_key"] == "index:0"
        for issue in detail["issues"]
    )


def test_machine_realtime_openapi_components_omit_removed_fields():
    schema_app = FastAPI()

    @schema_app.post("/schema/backend")
    def accept_backend(payload: BackendAlgorithmRequest):
        return payload

    @schema_app.post("/schema/cutline")
    def accept_cutline(payload: CutlineAlgorithmRequest):
        return payload

    schemas = schema_app.openapi()["components"]["schemas"]

    for component_name in (
        "BackendMachineRealtime",
        "MachineRealtimeRequest",
    ):
        properties = schemas[component_name]["properties"]
        assert {"input_quantity", "output_quantity"} <= properties.keys()
        assert {"completed_quantity", "period_quantity"}.isdisjoint(
            properties
        )


def test_stub_algo_run_delegates_synchronously_to_cutline_service():
    app = create_app()
    calls = []

    class StubService:
        def evaluate_algorithm(self, request: CutlineAlgorithmRequest):
            calls.append(request)
            return CutlineEvaluateResponse(
                calculation_time=datetime(2026, 7, 18, 12, 30),
                persistence_state=PersistenceStateResponse(
                    completed_pending_plan_ids=["PLAN-HIDDEN"]
                ),
            )

    app.dependency_overrides[get_cutline_service] = StubService
    client = TestClient(app)

    response = client.post("/stub/algo/run", json=cutline_payload())

    assert response.status_code == 200
    assert response.json()["calculation_time"] == "2026-07-18T12:30:00"
    assert "persistence_state" not in response.json()
    assert len(calls) == 1
    assert isinstance(calls[0], CutlineAlgorithmRequest)
    assert calls[0].agv_relations[0].machine_name == "机台1"
    assert calls[0].agv_relations[0].product_name == "产品1"
    assert calls[0].agv_relations[0].previous_product_name == "source"
    assert calls[0].agv_relations[0].wafer_spec == "N"


def test_cutline_evaluate_uses_raw_agv_spec_through_the_real_service_chain():
    payload = build_stockout_auto_payload()
    candidate_line = next(
        item
        for item in payload["machine_lines"]
        if item["machine_code"] == "EA004"
    )
    candidate_line["wafer_spec"] = "R"
    next(
        item
        for item in payload["lines"]
        if item["line_code"] == candidate_line["line_code"]
    )["wafer_spec"] = "R"
    candidate_binding = next(
        item
        for item in payload["agv_relations"]
        if item["equipmentid"] == "EA004"
    )

    assert candidate_binding["waferspec"] == "N"
    response = make_client().post("/cutline/evaluate", json=payload)

    assert response.status_code == 200
    decision = response.json()["cutline_decisions"][0]
    assert decision["plan"]["selected_machines"][0]["machine_code"] == "EA004"


@pytest.mark.parametrize(
    ("endpoint", "line_input_mode"),
    [
        ("/cutline/evaluate", "omitted"),
        ("/cutline/evaluate", "empty"),
        ("/stub/algo/run", "omitted"),
        ("/stub/algo/run", "empty"),
    ],
)
def test_cutline_evaluate_accepts_optional_line_collections_through_real_chain(
    endpoint: str,
    line_input_mode: str,
):
    payload = build_stockout_auto_payload()
    if line_input_mode == "omitted":
        payload.pop("lines")
        payload.pop("machine_lines")
    else:
        payload["lines"] = []
        payload["machine_lines"] = []

    response = make_client().post(endpoint, json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["cutline_decisions"][0]["plan"]["selected_machines"][0][
        "machine_code"
    ] == "EA004"


def test_cutline_evaluate_uses_route_workshop_through_real_service_chain():
    payload = build_stockout_auto_payload()
    payload["workshops"].append(
        {"workshop_code": "S1", "workshop_name": "S1车间"}
    )
    candidate_line_code = next(
        item["line_code"]
        for item in payload["machine_lines"]
        if item["machine_code"] == "EA004"
    )
    candidate_line = next(
        item
        for item in payload["lines"]
        if item["line_code"] == candidate_line_code
    )
    candidate_line.update(
        workshop_code="S1",
        workshop_name="S1车间",
    )

    candidate_master = next(
        item
        for item in payload["machine_master"]
        if item["machine_code"] == "EA004"
    )
    route_workshops = {
        item["workshop_code"]
        for item in payload["process_routes"]
        if item["process_code"] == candidate_master["process_code"]
    }
    assert route_workshops == {"S2"}
    assert candidate_line["workshop_code"] == "S1"

    response = make_client().post("/cutline/evaluate", json=payload)

    assert response.status_code == 200
    selected_machine = response.json()["cutline_decisions"][0]["plan"][
        "selected_machines"
    ][0]
    assert selected_machine["machine_code"] == "EA004"
    assert selected_machine["workshop_code"] == "S2"


def test_calculation_route_returns_422_for_raw_standard_agv_conflict():
    payload = cutline_payload()
    payload["agv_relations"][0]["machine_code"] = "OTHER"

    response = make_client().post("/cutline/evaluate", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "agv_relations[0]" in str(detail)
    assert "equipmentid" in str(detail)
    assert "machine_code" in str(detail)


def test_cutline_evaluate_rejects_empty_orders_with_backend_issues():
    payload = build_stockout_auto_payload()
    payload["orders"] = []
    client = TestClient(create_app(), raise_server_exceptions=False)

    response = client.post("/cutline/evaluate", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "BACKEND_DATA_INVALID"
    assert any(
        issue["code"] == "empty_dataset"
        and issue["dataset"] == "orders"
        for issue in detail["issues"]
    )


def test_cutline_evaluate_rejects_order_with_unknown_product():
    payload = build_stockout_auto_payload()
    payload["orders"][0]["product_code"] = "UNKNOWN-PRODUCT"
    client = TestClient(create_app(), raise_server_exceptions=False)

    response = client.post("/cutline/evaluate", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "BACKEND_DATA_INVALID"
    assert any(
        issue["code"] == "missing_reference"
        and issue["dataset"] == "orders"
        and issue["field"] == "product_code"
        for issue in detail["issues"]
    )


def test_cutline_evaluate_maps_pydantic_error_to_backend_data_invalid():
    payload = build_stockout_auto_payload()
    payload.pop("products")

    response = make_client().post("/cutline/evaluate", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "BACKEND_DATA_INVALID"
    assert any(
        issue["dataset"] == "products"
        and issue["code"] == "missing"
        for issue in detail["issues"]
    )


def test_cutline_evaluate_maps_field_type_error_to_backend_data_invalid():
    payload = build_stockout_auto_payload()
    payload["orders"][0]["total_quantity"] = "not-a-number"

    response = make_client().post("/cutline/evaluate", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "BACKEND_DATA_INVALID"
    assert any(
        issue["dataset"] == "orders"
        and issue["record_key"] == "index:0"
        and issue["field"] == "total_quantity"
        and issue["code"] == "float_parsing"
        for issue in detail["issues"]
    )


def test_cutline_evaluate_maps_non_object_root_to_backend_data_invalid():
    response = make_client().post("/cutline/evaluate", json=[])

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "BACKEND_DATA_INVALID"
    assert any(
        issue["dataset"] == "request"
        and issue["code"] == "model_type"
        for issue in detail["issues"]
    )


@pytest.mark.parametrize(
    "request_kwargs",
    [{"json": None}, {}],
)
def test_cutline_evaluate_maps_null_or_missing_body_to_backend_data_invalid(
    request_kwargs: dict,
):
    response = make_client().post("/cutline/evaluate", **request_kwargs)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "BACKEND_DATA_INVALID"
    assert any(
        issue["dataset"] == "request"
        and issue["code"] == "model_type"
        for issue in detail["issues"]
    )


def test_cutline_evaluate_maps_loader_error_to_backend_data_invalid():
    payload = build_stockout_auto_payload()
    payload["agv_relations"][0]["machine_code"] = "OTHER-MACHINE"

    response = make_client().post("/cutline/evaluate", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "BACKEND_DATA_INVALID"
    assert any(
        issue["code"] == "load_error"
        and issue["dataset"] == "agv_relations"
        for issue in detail["issues"]
    )


def test_cutline_evaluate_maps_snapshot_conversion_error_to_422():
    payload = build_stockout_auto_payload()
    assert payload["machine_lines"]
    payload["lines"] = []
    client = TestClient(create_app(), raise_server_exceptions=False)

    response = client.post("/cutline/evaluate", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "SNAPSHOT_CONVERSION_FAILED",
        "message": "machine_lines were provided but lines are empty",
        "issues": [],
    }


def test_cutline_evaluate_keeps_unknown_runtime_error_as_500():
    app = create_app()

    class FailingService:
        def evaluate_algorithm(self, request: CutlineAlgorithmRequest):
            raise RuntimeError("unexpected program failure")

    app.dependency_overrides[get_cutline_service] = FailingService
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/cutline/evaluate",
        json=deepcopy(build_stockout_auto_payload()),
    )

    assert response.status_code == 500


def test_cutline_evaluate_loads_cutline_payload_once(monkeypatch):
    calls = 0
    original = cutline_api_module._backend_loader.load_cutline_dict

    def counting_load(payload):
        nonlocal calls
        calls += 1
        return original(payload)

    monkeypatch.setattr(
        cutline_api_module._backend_loader,
        "load_cutline_dict",
        counting_load,
    )

    response = make_client().post(
        "/cutline/evaluate",
        json=build_stockout_auto_payload(),
    )

    assert response.status_code == 200
    assert calls == 1

