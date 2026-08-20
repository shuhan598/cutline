"""Formal V6 catalog and dynamic evaluation endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from pydantic import ValidationError

from app.adapters.v6_request_adapter import V6RequestAdapter
from app.adapters.snapshot_adapter import SnapshotConversionError
from app.api.cutline_api import (
    get_catalog_store,
    get_cutline_service,
    get_state_store,
)
from app.schemas.v6_schema import (
    CatalogPatchRequest,
    CatalogResponse,
    FullCatalogRequest,
    V6EvaluateRequest,
    V6EvaluateResponse,
)
from app.schemas.pending_cutline_schema import PendingCutlinePlan
from app.schemas.request_schema import ActiveCutlineEventRequest
from app.schemas.response_schema import PersistenceStateResponse
from app.service.algorithm_state_store import AlgorithmStateStore
from app.service.catalog_store import CatalogStore, CatalogStoreError
from app.service.cutline_service import CutlineService


router = APIRouter(tags=["cutline-v6"])


def _error(exc: CatalogStoreError) -> HTTPException:
    status = 422 if exc.code == "STATIC_DATA_INVALID" else 409
    return HTTPException(
        status_code=status,
        detail={"code": exc.code, "message": str(exc), "retryable": status == 409},
    )


def _response(record, store: CatalogStore) -> CatalogResponse:
    return CatalogResponse(
        catalog_version=record.catalog_version,
        catalog_hash=record.catalog_hash,
        published_at=record.published_at,
        retained_versions=store.retained_versions(),
    )


@router.post("/cutline/static-data", response_model=CatalogResponse)
def publish_static_data(
    payload: Any = Body(...),
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    store: CatalogStore = Depends(get_catalog_store),
) -> CatalogResponse:
    try:
        request = FullCatalogRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "STATIC_DATA_INVALID", "message": str(exc), "retryable": False}) from exc
    try:
        record = store.publish(
            request.catalog_version,
            request.catalog.model_dump(),
            idempotency_key,
        )
    except CatalogStoreError as exc:
        raise _error(exc) from exc
    return _response(record, store)


@router.patch("/cutline/static-data", response_model=CatalogResponse)
def patch_static_data(
    payload: Any = Body(...),
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    store: CatalogStore = Depends(get_catalog_store),
) -> CatalogResponse:
    try:
        request = CatalogPatchRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "STATIC_DATA_INVALID", "message": str(exc), "retryable": False}) from exc
    try:
        record = store.patch(
            request.base_catalog_version,
            request.next_catalog_version,
            {name: change.model_dump() for name, change in request.changes.items()},
            idempotency_key,
        )
    except CatalogStoreError as exc:
        raise _error(exc) from exc
    return _response(record, store)


def _missing_references(request: V6EvaluateRequest, catalog: dict[str, list[dict[str, Any]]]):
    machine_codes = {item["machine_code"] for item in catalog["machine_master"]}
    machine_codes.update(item.get("p166_jt_group") for item in catalog["machine_master"])
    buffers = {item["buffer_code"] for item in catalog["buffer_master"]}
    missing = []
    for item in request.dynamic.machine_realtime:
        if item.machine_code not in machine_codes:
            missing.append({"dataset": "machine_master", "key": {"machine_code": item.machine_code}})
    for item in request.dynamic.buffer_realtime:
        if item.buffer_code not in buffers:
            missing.append({"dataset": "buffer_master", "key": {"buffer_code": item.buffer_code}})
    for item in request.dynamic.agv_relations:
        if item.equipmentid not in machine_codes:
            missing.append({"dataset": "machine_master", "key": {"machine_code": item.equipmentid}})
    return missing


@router.post("/cutline/evaluate", response_model=V6EvaluateResponse)
def evaluate_v6(
    payload: Any = Body(...),
    service: CutlineService = Depends(get_cutline_service),
    store: CatalogStore = Depends(get_catalog_store),
    state_store: AlgorithmStateStore = Depends(get_state_store),
) -> V6EvaluateResponse:
    try:
        request = V6EvaluateRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "DYNAMIC_DATA_INVALID", "message": str(exc), "retryable": False}) from exc
    record = store.get(request.catalog_version)
    if record is None:
        if store.current() is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "STATIC_CATALOG_REQUIRED", "message": "no static catalog is loaded", "catalog_version": request.catalog_version, "retryable": True},
            )
        raise HTTPException(
            status_code=409,
            detail={"code": "CATALOG_VERSION_NOT_FOUND", "message": "requested catalog version is not retained", "catalog_version": request.catalog_version, "retryable": True},
        )
    missing = _missing_references(request, record.catalog)
    if missing:
        raise HTTPException(
            status_code=409,
            detail={"code": "STATIC_CATALOG_DATA_MISSING", "message": "dynamic snapshot references missing static records", "catalog_version": request.catalog_version, "missing_references": missing, "retryable": True},
        )
    workshop_id = request.snapshot_meta.workshop_id
    attempt = state_store.begin(workshop_id)
    try:
        internal = V6RequestAdapter().to_internal(request, record)
        if attempt.state:
            persisted = PersistenceStateResponse.model_validate(attempt.state)
            internal = internal.model_copy(update={
                "pending_cutline_plans": [PendingCutlinePlan.model_validate(item.model_dump()) for item in persisted.pending_cutline_plans],
                "active_cutline_events": [ActiveCutlineEventRequest.model_validate(item.model_dump()) for item in persisted.active_cutline_events],
                "return_suggested_event_ids": list(persisted.return_suggested_event_ids),
                "mixed_cutline_event_ids": list(persisted.mixed_cutline_event_ids),
            })
        result = service.evaluate_algorithm(internal)
        state = result.persistence_state.model_dump(mode="json")
        state_store.commit(workshop_id, state)
    except SnapshotConversionError as exc:
        state_store.abort(workshop_id)
        raise HTTPException(
            status_code=409,
            detail={"code": "STATIC_CATALOG_DATA_MISSING", "message": str(exc), "catalog_version": request.catalog_version, "retryable": True},
        ) from exc
    except ValidationError as exc:
        state_store.abort(workshop_id)
        raise HTTPException(status_code=422, detail={"code": "DYNAMIC_DATA_INVALID", "message": str(exc), "retryable": False}) from exc
    except Exception:
        state_store.abort(workshop_id)
        raise
    return V6EvaluateResponse(
        **result.model_dump(exclude={"persistence_state"}),
        catalog_version=request.catalog_version,
        state_generation=attempt.state_generation,
        state_reset=attempt.state_reset,
    )
