from fastapi.testclient import TestClient

from app.main import create_app


def empty_catalog():
    return {name: [] for name in (
        "machine_master", "machine_process_times", "workshops", "orders",
        "products", "process_routes", "buffer_master",
    )}


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
