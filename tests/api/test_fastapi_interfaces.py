import json
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.cutline_api import get_cutline_service
from app.main import create_app
from app.schemas.request_schema import CutlineAlgorithmRequest
from app.schemas.response_schema import CutlineAlgorithmResponse
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
                "machine_code": "M1",
                "status": "运行",
                "tangent_time": None,
                "input_quantity": 0,
                "output_quantity": 1,
                "completed_quantity": 0,
                "period_quantity": 2,
                "out_time": "2026-07-13T08:00:00Z",
            }
        ],
        "machine_master": [
            {
                "machine_code": "M1",
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
                "order_name": "source",
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
                "bound_source_name": "source",
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
                "lastlinecode": "O1",
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
    payload["machine_realtime"][0]["period_quantity"] = 10
    payload["machine_realtime"][0]["out_time"] = "2026-07-14T08:30:00+08:00"

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

    class StubService:
        def evaluate_algorithm(self, request: CutlineAlgorithmRequest):
            calls.append(request)
            return CutlineAlgorithmResponse(
                calculation_time=datetime(2026, 7, 18, 12, 0)
            )

    app.dependency_overrides[get_cutline_service] = StubService
    client = TestClient(app)

    response = client.post("/cutline/evaluate", json=cutline_payload())

    assert response.status_code == 200
    assert response.json()["calculation_time"] == "2026-07-18T12:00:00"
    assert len(calls) == 1
    assert isinstance(calls[0], CutlineAlgorithmRequest)
    assert calls[0].machine_realtime[0].machine_code == "M1"
    assert calls[0].agv_relations[0].machine_code == "M1"
    assert calls[0].agv_relations[0].order_code == "O1"
    assert calls[0].agv_relations[0].wafer_spec == "N"
    assert calls[0].machine_master[0].process_code == "P1"

def test_stub_algo_run_delegates_synchronously_to_cutline_service():
    app = create_app()
    calls = []

    class StubService:
        def evaluate_algorithm(self, request: CutlineAlgorithmRequest):
            calls.append(request)
            return CutlineAlgorithmResponse(
                calculation_time=datetime(2026, 7, 18, 12, 30)
            )

    app.dependency_overrides[get_cutline_service] = StubService
    client = TestClient(app)

    response = client.post("/stub/algo/run", json=cutline_payload())

    assert response.status_code == 200
    assert response.json()["calculation_time"] == "2026-07-18T12:30:00"
    assert len(calls) == 1
    assert isinstance(calls[0], CutlineAlgorithmRequest)
    assert calls[0].agv_relations[0].machine_name == "机台1"
    assert calls[0].agv_relations[0].order_name == "source"
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


def test_calculation_route_returns_422_for_raw_standard_agv_conflict():
    payload = cutline_payload()
    payload["agv_relations"][0]["machine_code"] = "OTHER"

    response = make_client().post("/cutline/evaluate", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "agv_relations[0]" in str(detail)
    assert "equipmentid" in str(detail)
    assert "machine_code" in str(detail)

