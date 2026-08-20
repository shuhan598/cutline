"""Strict wire models for the V6 static/dynamic API split."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.request_schema import (
    AgvRelationRequest,
    BufferMasterRequest,
    BufferRealtimeRequest,
    MachineMasterRequest,
    MachineProcessTimeRequest,
    MachineRealtimeRequest,
    OrderRequest,
    ProcessRouteRequest,
    ProductRequest,
    WorkshopRequest,
)
from app.schemas.response_schema import CutlineAlgorithmResponse


class V6Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StaticCatalog(V6Model):
    machine_master: list[MachineMasterRequest]
    machine_process_times: list[MachineProcessTimeRequest]
    workshops: list[WorkshopRequest]
    orders: list[OrderRequest]
    products: list[ProductRequest]
    process_routes: list[ProcessRouteRequest]
    buffer_master: list[BufferMasterRequest]


class FullCatalogRequest(V6Model):
    catalog_version: str = Field(..., min_length=1)
    catalog: StaticCatalog


class DatasetChange(V6Model):
    upserts: list[dict[str, Any]] = Field(default_factory=list)
    deleted_keys: list[Any] = Field(default_factory=list)


class CatalogPatchRequest(V6Model):
    base_catalog_version: str = Field(..., min_length=1)
    next_catalog_version: str = Field(..., min_length=1)
    changes: dict[str, DatasetChange]


class V6AgvRelation(V6Model):
    equipmentid: str = Field(..., min_length=1)
    equipmentname: str
    linename: str
    lastlinename: str | None = None
    waferspec: str
    createtime: datetime


class SnapshotMetaV6(V6Model):
    run_id: str
    trigger_type: str
    workshop_id: str
    snapshot_time: datetime
    params_version: int
    degraded_flags: list[str]


class DynamicEvaluateRequest(V6Model):
    machine_realtime: list[MachineRealtimeRequest]
    buffer_realtime: list[BufferRealtimeRequest]
    agv_relations: list[V6AgvRelation]


class V6EvaluateRequest(V6Model):
    catalog_version: str = Field(..., min_length=1)
    snapshot_meta: SnapshotMetaV6
    dynamic: DynamicEvaluateRequest


class CatalogResponse(V6Model):
    catalog_version: str
    catalog_hash: str
    published_at: datetime
    retained_versions: list[str]


class CatalogErrorDetail(V6Model):
    code: str
    message: str
    catalog_version: str | None = None
    retryable: bool = False
    missing_references: list[dict[str, Any]] | None = None


class V6EvaluateResponse(CutlineAlgorithmResponse):
    catalog_version: str
    state_generation: str
    state_reset: bool
