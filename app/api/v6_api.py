"""提供 V6 静态目录发布、增量更新和动态切线评估接口。

V6 将变化频率低的主数据保存为带版本的静态目录，将每轮变化的设备、
缓存区和 AGV 信息作为动态快照提交。本模块负责在两类数据之间建立引用，
并保证同一车间的跨轮持久化状态不会被并发评估交叉覆盖。
"""

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
    """将目录存储层的可恢复异常转换为 HTTP 错误响应。

    静态目录内容本身不合法时返回 422；其余错误通常表示调用方需要重试、
    切换版本或重新发布目录，因此返回 409 以表达资源状态冲突。
    """
    status = 422 if exc.code == "STATIC_DATA_INVALID" else 409
    return HTTPException(
        status_code=status,
        detail={"code": exc.code, "message": str(exc), "retryable": status == 409},
    )


def _response(record, store: CatalogStore) -> CatalogResponse:
    """将内部目录记录整理为发布和更新接口共用的响应模型。"""
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
    """全量发布一个新的静态目录版本。

    ``Idempotency-Key`` 与目录版本、内容哈希共同决定幂等性：重复的同一
    请求返回原记录，而同一键携带不同内容会被目录存储层拒绝。
    """
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
    """以当前静态目录为基准，原子地发布下一个目录版本。

    每个数据集可同时包含新增或覆盖记录的 ``upserts``，以及按主键删除的
    ``deleted_keys``。存储层会校验基准版本仍是当前版本，防止旧快照覆盖新数据。
    """
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
    """找出动态快照中引用了静态目录不存在机台或缓存区的记录。

    机台实时数据只匹配 ``p166_jt_group``，AGV 关系只匹配标准机台编码。
    返回值直接用于 409 响应，方便调用方补齐目录。
    """
    realtime_machine_codes = {
        item["p166_jt_group"].strip()
        for item in catalog["machine_master"]
        if item["p166_jt_group"].strip()
    }
    agv_machine_codes = {
        item["machine_code"].strip()
        for item in catalog["machine_master"]
        if item["machine_code"].strip()
    }
    buffers = {item["buffer_code"] for item in catalog["buffer_master"]}
    missing = []
    for item in request.dynamic.machine_realtime:
        if item.machine_code.strip() not in realtime_machine_codes:
            missing.append({"dataset": "machine_master", "key": {"machine_code": item.machine_code}})
    for item in request.dynamic.buffer_realtime:
        if item.buffer_code not in buffers:
            missing.append({"dataset": "buffer_master", "key": {"buffer_code": item.buffer_code}})
    for item in request.dynamic.agv_relations:
        if item.equipmentid.strip() not in agv_machine_codes:
            missing.append({"dataset": "machine_master", "key": {"machine_code": item.equipmentid}})
    return missing


@router.post(
    "/cutline/evaluate",
    response_model=V6EvaluateResponse,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": V6EvaluateRequest.model_json_schema()
                }
            },
        }
    },
)
def evaluate_v6(
    payload: Any = Body(...),
    service: CutlineService = Depends(get_cutline_service),
    store: CatalogStore = Depends(get_catalog_store),
    state_store: AlgorithmStateStore = Depends(get_state_store),
) -> V6EvaluateResponse:
    """使用指定静态目录和动态快照执行一次 V6 切线评估。

    处理顺序为：校验动态请求、定位并校验静态目录引用、锁定车间状态、转换为
    既有内部模型、合并上轮持久化状态、执行算法，最后仅在成功时提交新状态。
    任一步失败都会释放车间锁，避免单次异常阻塞后续评估。
    """
    try:
        request = V6EvaluateRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "DYNAMIC_DATA_INVALID",
                "message": str(exc),
                "retryable": False,
            },
        ) from exc
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
            # V6 请求不携带历史状态，必须从该车间上次成功计算结果中恢复。
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
