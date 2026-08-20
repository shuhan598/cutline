from app.adapters.v6_request_adapter import V6RequestAdapter
from app.schemas.v6_schema import V6EvaluateRequest
from app.service.catalog_store import CatalogRecord
from datetime import datetime, timezone


def test_adapter_injects_catalog_metadata_and_maps_dynamic_payload():
    catalog = {
        "machine_master": [], "machine_process_times": [], "workshops": [],
        "orders": [], "products": [], "process_routes": [], "buffer_master": [],
    }
    record = CatalogRecord("v1", catalog, "sha256:x", datetime.now(timezone.utc))
    payload = V6EvaluateRequest.model_validate({
        "catalog_version": "v1",
        "snapshot_meta": {
            "run_id": "r1", "trigger_type": "timer", "workshop_id": "W1",
            "snapshot_time": "2026-08-20T10:00:00Z", "params_version": 1,
            "degraded_flags": [],
        },
        "dynamic": {"machine_realtime": [], "buffer_realtime": [], "agv_relations": []},
    })
    internal = V6RequestAdapter().to_internal(payload, record)
    assert internal.snapshot_meta.catalog_version == "v1"
    assert internal.snapshot_meta.catalog_loaded_at == record.published_at
    assert internal.machine_realtime == []

