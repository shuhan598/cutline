# 后端传给算法服务的请求数据格式

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.common_schema import (
    AlgorithmConfig,
    BufferInventoryItem,
    BufferSegment,
    CutlineEvent,
    MachineCapacityRecord,
    MachineMaster,
    MachineRuntimeStatus,
    OrderInfo,
    ProcessRouteStep,
    ProductModel,
)


class CutlineSnapshot(BaseModel):
    """一次切线评估所需的完整数据快照。"""

    current_time: datetime = Field(..., description="当前快照时间，用于预警、切回和混料追溯")
    machine_statuses: List[MachineRuntimeStatus] = Field(
        default_factory=list,
        description="机台实时状态列表",
    )
    machine_masters: List[MachineMaster] = Field(default_factory=list, description="机台主数据列表")
    product_models: List[ProductModel] = Field(default_factory=list, description="产品型号列表")
    process_route_steps: List[ProcessRouteStep] = Field(default_factory=list, description="工艺路线步骤列表")
    buffer_segments: List[BufferSegment] = Field(default_factory=list, description="Buffer 段配置列表")
    buffer_inventories: List[BufferInventoryItem] = Field(
        default_factory=list,
        description="Buffer 区间库存列表，库存数量单位：片",
    )
    capacity_records: List[MachineCapacityRecord] = Field(
        default_factory=list,
        description="机台型号产能记录列表，产能单位：片/小时",
    )
    orders: List[OrderInfo] = Field(default_factory=list, description="订单信息列表")
    active_cutline_events: List[CutlineEvent] = Field(default_factory=list, description="尚需跟踪的切线事件列表")
    config: AlgorithmConfig = Field(default_factory=AlgorithmConfig, description="算法参数配置")


class CutlineEvaluateRequest(BaseModel):
    """切线评估请求。"""

    request_id: Optional[str] = Field(default=None, description="请求 ID")
    snapshot: CutlineSnapshot = Field(..., description="切线评估数据快照")


class MixTraceRequest(BaseModel):
    """混料追溯请求。"""

    request_id: Optional[str] = Field(default=None, description="请求 ID")
    current_time: datetime = Field(..., description="当前请求时间，用于判断混料通知生命周期")
    cutline_event: CutlineEvent = Field(..., description="已确认发生的切线事件")
    capacity_records: List[MachineCapacityRecord] = Field(
        default_factory=list,
        description="机台型号产能记录列表，产能单位：片/小时，工艺时长单位：分钟",
    )
    config: AlgorithmConfig = Field(default_factory=AlgorithmConfig, description="算法参数配置")
