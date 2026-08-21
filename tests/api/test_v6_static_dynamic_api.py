from datetime import datetime

from fastapi.testclient import TestClient

from app.api.cutline_api import get_cutline_service
from app.api.v6_api import _missing_references, evaluate_v6
from app.main import create_app
from app.schemas.request_schema import CutlineAlgorithmRequest
from app.schemas.response_schema import (
    CutlineEvaluateResponse,
    PersistenceStateResponse,
)
from app.schemas.v6_schema import V6EvaluateRequest, V6EvaluateResponse


def empty_catalog():
    return {name: [] for name in (
        "machine_master", "machine_process_times", "workshops", "orders",
        "products", "process_routes", "buffer_master",
    )}


def dynamic_request(*, realtime_code="JT001", agv_code="M001"):
    return V6EvaluateRequest.model_validate({
        "catalog_version": "v1",
        "snapshot_meta": {
            "run_id": "r1", "trigger_type": "timer", "workshop_id": "W1",
            "snapshot_time": "2026-08-20T10:00:00Z", "params_version": 1,
            "degraded_flags": [],
        },
        "dynamic": {
            "machine_realtime": [{
                "machine_code": realtime_code,
                "status": "运行",
                "tangent_time": None,
                "input_quantity": 0.0,
                "output_quantity": 0.0,
                "out_time": None,
            }],
            "buffer_realtime": [],
            "agv_relations": [{
                "equipmentid": agv_code,
                "equipmentname": "Machine One",
                "linename": "Product One",
                "lastlinename": None,
                "waferspec": "N",
                "createtime": "2026-08-20T09:59:00Z",
            }],
        },
    })


def machine_catalog():
    catalog = empty_catalog()
    catalog["machine_master"] = [{
        "machine_code": "M001",
        "p166_jt_group": "JT001",
        "machine_name": "Machine One",
        "process_code": "P001",
        "process_name": "Process One",
    }]
    return catalog


def registered_post_routes(app, path):
    routes = []
    for included in app.routes:
        router = getattr(included, "original_router", None)
        candidates = router.routes if router is not None else [included]
        routes.extend(
            route
            for route in candidates
            if route.path == path and "POST" in route.methods
        )
    return routes


def test_formal_evaluate_has_one_v6_route_and_openapi_contract():
    app = create_app()

    routes = registered_post_routes(app, "/cutline/evaluate")
    operation = app.openapi()["paths"]["/cutline/evaluate"]["post"]

    assert len(routes) == 1
    assert routes[0].endpoint is evaluate_v6
    assert operation["operationId"].startswith("evaluate_v6_")
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["title"] == "V6EvaluateRequest"
    assert request_schema["required"] == [
        "catalog_version",
        "snapshot_meta",
        "dynamic",
    ]
    assert set(request_schema["properties"]) == {
        "catalog_version",
        "snapshot_meta",
        "dynamic",
    }
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/V6EvaluateResponse"
    }
    assert V6EvaluateResponse.__name__ in app.openapi()["components"]["schemas"]
    assert len(registered_post_routes(app, "/backend/validate")) == 1
    assert len(registered_post_routes(app, "/stub/algo/run")) == 1


def test_machine_reference_validation_uses_separate_identifier_domains():
    catalog = machine_catalog()

    assert _missing_references(dynamic_request(), catalog) == []

    realtime_missing = _missing_references(
        dynamic_request(realtime_code="M001"),
        catalog,
    )
    assert realtime_missing == [
        {"dataset": "machine_master", "key": {"machine_code": "M001"}}
    ]

    agv_missing = _missing_references(
        dynamic_request(agv_code="JT001"),
        catalog,
    )
    assert agv_missing == [
        {"dataset": "machine_master", "key": {"machine_code": "JT001"}}
    ]


def test_dynamic_request_reaches_v6_service_chain():
    app = create_app()
    received = []

    class StubService:
        def evaluate_algorithm(self, request: CutlineAlgorithmRequest):
            received.append(request)
            return CutlineEvaluateResponse(
                calculation_time=datetime(2026, 8, 20, 10, 0),
                persistence_state=PersistenceStateResponse(),
            )

    app.dependency_overrides[get_cutline_service] = StubService
    client = TestClient(app)
    published = client.post(
        "/cutline/static-data",
        headers={"Idempotency-Key": "v6-success"},
        json={"catalog_version": "v1", "catalog": empty_catalog()},
    )

    response = client.post(
        "/cutline/evaluate",
        json={
            "catalog_version": "v1",
            "snapshot_meta": {
                "run_id": "r1", "trigger_type": "timer", "workshop_id": "W1",
                "snapshot_time": "2026-08-20T10:00:00Z", "params_version": 1,
                "degraded_flags": [],
            },
            "dynamic": {
                "machine_realtime": [],
                "buffer_realtime": [],
                "agv_relations": [],
            },
        },
    )

    assert published.status_code == 200
    assert response.status_code == 200
    assert len(received) == 1
    assert received[0].snapshot_meta.catalog_version == "v1"
    assert response.json()["catalog_version"] == "v1"
    assert "persistence_state" not in response.json()


def test_static_publish_and_patch_endpoints_return_versions():
    client = TestClient(create_app())
    response = client.post(
        "/cutline/static-data",
        headers={"Idempotency-Key": "k1"},
        json={"catalog_version": "v1", "catalog": empty_catalog()},
    )
    assert response.status_code == 200
    assert response.json()["catalog_version"] == "v1"
    response = client.patch(
        "/cutline/static-data",
        headers={"Idempotency-Key": "k2"},
        json={
            "base_catalog_version": "v1", "next_catalog_version": "v2",
            "changes": {"orders": {"upserts": [], "deleted_keys": []}},
        },
    )
    assert response.status_code == 200
    assert response.json()["catalog_version"] == "v2"


def test_evaluate_without_catalog_returns_recoverable_error():
    client = TestClient(create_app())
    response = client.post(
        "/cutline/evaluate",
        json={
            "catalog_version": "missing",
            "snapshot_meta": {
                "run_id": "r1", "trigger_type": "timer", "workshop_id": "W1",
                "snapshot_time": "2026-08-20T10:00:00Z", "params_version": 1,
                "degraded_flags": [],
            },
            "dynamic": {"machine_realtime": [], "buffer_realtime": [], "agv_relations": []},
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "STATIC_CATALOG_REQUIRED"


def test_evaluate_unknown_retained_version_returns_catalog_not_found():
    client = TestClient(create_app())
    client.post(
        "/cutline/static-data",
        headers={"Idempotency-Key": "k1"},
        json={"catalog_version": "v1", "catalog": empty_catalog()},
    )
    response = client.post("/cutline/evaluate", json={"catalog_version": "missing"})
    assert response.status_code == 422
    response = client.post(
        "/cutline/evaluate",
        json={
            "catalog_version": "missing",
            "snapshot_meta": {"run_id": "r", "trigger_type": "t", "workshop_id": "W", "snapshot_time": "2026-01-01T00:00:00Z", "params_version": 1, "degraded_flags": []},
            "dynamic": {"machine_realtime": [], "buffer_realtime": [], "agv_relations": []},
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CATALOG_VERSION_NOT_FOUND"


def test_formal_evaluate_rejects_flat_static_arrays():
    client = TestClient(create_app())
    response = client.post(
        "/cutline/evaluate",
        json={"catalog_version": "v1", "snapshot_meta": {}, "dynamic": {}, "orders": []},
    )
    assert response.status_code == 422


def test_formal_evaluate_invalid_dynamic_request_uses_v6_error_envelope():
    response = TestClient(create_app()).post(
        "/cutline/evaluate",
        json={"catalog_version": "v1"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "DYNAMIC_DATA_INVALID"


def test_invalid_patch_is_422_and_keeps_previous_version():
    client = TestClient(create_app())
    client.post(
        "/cutline/static-data",
        headers={"Idempotency-Key": "k1"},
        json={"catalog_version": "v1", "catalog": empty_catalog()},
    )
    response = client.patch(
        "/cutline/static-data",
        headers={"Idempotency-Key": "k2"},
        json={"base_catalog_version": "v1", "next_catalog_version": "v2", "changes": {"workshops": {"upserts": [{"workshop_code": "W1"}], "deleted_keys": []}}},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "STATIC_DATA_INVALID"
    response = client.patch(
        "/cutline/static-data",
        headers={"Idempotency-Key": "k3"},
        json={"base_catalog_version": "v1", "next_catalog_version": "v2", "changes": {"workshops": {"upserts": [], "deleted_keys": []}}},
    )
    assert response.status_code == 200
