import pytest
from pydantic import ValidationError

from app.schemas.v6_schema import (
    DynamicEvaluateRequest,
    FullCatalogRequest,
    V6EvaluateRequest,
)


def empty_catalog():
    return {name: [] for name in (
        "machine_master", "machine_process_times", "workshops", "orders",
        "products", "process_routes", "buffer_master",
    )}


def test_full_catalog_requires_exact_v6_datasets():
    request = FullCatalogRequest(catalog_version="v1", catalog=empty_catalog())
    assert request.catalog.machine_master == []
    with pytest.raises(ValidationError):
        FullCatalogRequest(catalog_version="v1", catalog={**empty_catalog(), "lines": []})


def test_dynamic_request_forbids_flat_static_fields_and_persistence_state():
    valid = {
        "catalog_version": "v1",
        "snapshot_meta": {
            "run_id": "r1", "trigger_type": "timer", "workshop_id": "W1",
            "snapshot_time": "2026-08-20T10:00:00Z", "params_version": 1,
            "degraded_flags": [],
        },
        "dynamic": {"machine_realtime": [], "buffer_realtime": [], "agv_relations": []},
    }
    V6EvaluateRequest.model_validate(valid)
    with pytest.raises(ValidationError):
        V6EvaluateRequest.model_validate({**valid, "orders": []})
    with pytest.raises(ValidationError):
        V6EvaluateRequest.model_validate({**valid, "persistence_state": {}})


def test_agv_wire_fields_are_strict():
    with pytest.raises(ValidationError):
        DynamicEvaluateRequest(
            machine_realtime=[], buffer_realtime=[],
            agv_relations=[{"equipmentid": "M1", "equipmentname": "m", "linename": "p", "lastlinename": None, "waferspec": "N", "createtime": "2026-08-20T10:00:00Z", "legacy": 1}],
        )

