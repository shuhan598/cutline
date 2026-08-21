"""定义 V6 静态目录与动态评估接口的严格传输模型。

所有模型禁止未声明字段，以便尽早发现上游接口漂移。静态目录承载低频主数据，
动态请求仅承载本轮实时数据和目录版本号，响应额外返回状态代际信息。
"""

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
    """V6 传输模型基类，统一拒绝额外字段以保持接口契约严格。"""
    model_config = ConfigDict(extra="forbid")


class StaticCatalog(V6Model):
    """一份可独立发布的完整静态目录，必须包含所有约定的数据集。"""
    machine_master: list[MachineMasterRequest]
    machine_process_times: list[MachineProcessTimeRequest]
    workshops: list[WorkshopRequest]
    orders: list[OrderRequest]
    products: list[ProductRequest]
    process_routes: list[ProcessRouteRequest]
    buffer_master: list[BufferMasterRequest]


class FullCatalogRequest(V6Model):
    """全量静态目录发布请求，版本号由调用方负责递增和管理。"""
    catalog_version: str = Field(..., min_length=1)
    catalog: StaticCatalog


class DatasetChange(V6Model):
    """单个目录数据集的增量变更：新增或覆盖记录与按主键删除记录。"""
    upserts: list[dict[str, Any]] = Field(default_factory=list)
    deleted_keys: list[Any] = Field(default_factory=list)


class CatalogPatchRequest(V6Model):
    """从基准目录派生下一目录版本的增量更新请求。"""
    base_catalog_version: str = Field(..., min_length=1)
    next_catalog_version: str = Field(..., min_length=1)
    changes: dict[str, DatasetChange]


class V6AgvRelation(V6Model):
    """V6 动态快照中的 AGV 机台、产品和硅片规格关联记录。"""
    equipmentid: str = Field(..., min_length=1)
    equipmentname: str
    linename: str
    lastlinename: str | None = None
    waferspec: str
    createtime: datetime


class SnapshotMetaV6(V6Model):
    """标识单轮动态快照来源、车间、时间和降级标记的元数据。"""
    run_id: str
    trigger_type: str
    workshop_id: str
    snapshot_time: datetime
    params_version: int
    degraded_flags: list[str]


class DynamicEvaluateRequest(V6Model):
    """一轮评估中会变化的机台、缓存区和 AGV 实时数据集合。"""
    machine_realtime: list[MachineRealtimeRequest]
    buffer_realtime: list[BufferRealtimeRequest]
    agv_relations: list[V6AgvRelation]


class V6EvaluateRequest(V6Model):
    """引用静态目录版本并提交动态快照的正式评估请求。"""
    catalog_version: str = Field(..., min_length=1)
    snapshot_meta: SnapshotMetaV6
    dynamic: DynamicEvaluateRequest


class CatalogResponse(V6Model):
    """目录发布成功后的版本、内容哈希、发布时间和可用历史版本。"""
    catalog_version: str
    catalog_hash: str
    published_at: datetime
    retained_versions: list[str]


class CatalogErrorDetail(V6Model):
    """目录相关 HTTP 错误的结构化内容，支持调用方按错误码恢复。"""
    code: str
    message: str
    catalog_version: str | None = None
    retryable: bool = False
    missing_references: list[dict[str, Any]] | None = None


class V6EvaluateResponse(CutlineAlgorithmResponse):
    """复用算法结果并附带本轮使用的目录版本与状态仓库信息。"""
    catalog_version: str
    state_generation: str
    state_reset: bool
