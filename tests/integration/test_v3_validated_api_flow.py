from fastapi.testclient import TestClient

from tests.fixtures.v3_full_route_factory import build_stockout_auto_payload
from tests.utils.legacy_evaluate_client import (
    LegacyEvaluateTestClient,
    create_legacy_evaluate_test_app,
)


def _client() -> TestClient:
    return LegacyEvaluateTestClient(
        create_legacy_evaluate_test_app(),
        raise_server_exceptions=False,
    )


def test_complete_formal_payload_runs_the_real_service_chain():
    response = _client().post(
        "/cutline/evaluate",
        json=build_stockout_auto_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["calculation_time"] == "2026-07-17T08:00:00+08:00"
    assert "persistence_state" in body


def test_same_missing_orders_payload_is_valid_false_and_evaluate_422():
    payload = build_stockout_auto_payload()
    payload["orders"] = []
    client = _client()

    validation_response = client.post("/backend/validate", json=payload)
    evaluation_response = client.post("/cutline/evaluate", json=payload)

    assert validation_response.status_code == 200
    assert validation_response.json()["valid"] is False
    assert evaluation_response.status_code == 422
    assert evaluation_response.json()["detail"]["code"] == (
        "BACKEND_DATA_INVALID"
    )


def test_evaluate_maps_unknown_process_name_to_backend_data_invalid():
    payload = build_stockout_auto_payload()
    route = payload["process_routes"][3]
    original_process_code = route["process_code"]
    route["process_name"] = "未知工序"
    client = _client()

    validation_response = client.post("/backend/validate", json=payload)
    evaluation_response = client.post("/cutline/evaluate", json=payload)

    assert validation_response.status_code == 200
    validation_body = validation_response.json()
    assert validation_body["valid"] is False
    assert any(
        issue["code"] == "unknown_process_name"
        and issue["dataset"] == "process_routes"
        and issue["field"] == "process_name"
        and issue["record_key"] == original_process_code
        for issue in validation_body["issues"]
    )
    assert evaluation_response.status_code == 422
    detail = evaluation_response.json()["detail"]
    assert detail["code"] == "BACKEND_DATA_INVALID"
    assert any(
        issue["code"] == "unknown_process_name"
        and issue["dataset"] == "process_routes"
        and issue["field"] == "process_name"
        and issue["record_key"] == original_process_code
        for issue in detail["issues"]
    )


def test_duplicate_route_sequence_is_rejected_before_snapshot_conversion():
    payload = build_stockout_auto_payload()
    payload["process_routes"][1]["sequence"] = payload["process_routes"][0][
        "sequence"
    ]

    response = _client().post("/cutline/evaluate", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "BACKEND_DATA_INVALID"
    assert any(
        issue["code"] == "duplicate_sequence"
        for issue in detail["issues"]
    )


def test_silk_screen_not_last_is_rejected_before_service():
    payload = build_stockout_auto_payload()
    payload["process_routes"][-2]["process_name"] = "丝网"
    payload["process_routes"][-1]["process_name"] = "后续工序"

    response = _client().post("/cutline/evaluate", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "BACKEND_DATA_INVALID"
    assert any(
        issue["code"] == "silk_screen_not_last"
        for issue in detail["issues"]
    )


def test_duplicate_silk_screen_is_rejected_before_service():
    payload = build_stockout_auto_payload()
    payload["process_routes"][-2]["process_name"] = "丝网"

    response = _client().post("/cutline/evaluate", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "BACKEND_DATA_INVALID"
    assert any(
        issue["code"] == "duplicate_silk_screen_process"
        for issue in detail["issues"]
    )


def test_missing_silk_screen_is_rejected_before_service():
    payload = build_stockout_auto_payload()
    payload["process_routes"][-1]["process_name"] = "后续工序"

    response = _client().post("/cutline/evaluate", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "BACKEND_DATA_INVALID"
    assert any(
        issue["code"] == "missing_silk_screen_process"
        for issue in detail["issues"]
    )


def test_broken_route_neighbor_is_rejected_before_service():
    payload = build_stockout_auto_payload()
    payload["process_routes"][1]["upstream_process_code"] = "碱抛"

    response = _client().post("/cutline/evaluate", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "BACKEND_DATA_INVALID"
    assert any(
        issue["code"] == "broken_process_route"
        and issue["field"] == "upstream_process_code"
        for issue in detail["issues"]
    )


def test_real_snapshot_conversion_failure_returns_422():
    payload = build_stockout_auto_payload()
    assert payload["machine_lines"]
    payload["lines"] = []

    response = _client().post("/cutline/evaluate", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == (
        "SNAPSHOT_CONVERSION_FAILED"
    )
