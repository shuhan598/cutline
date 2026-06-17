# 通用基础对象

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class MachineRuntimeStatus(BaseModel):
    """机台实时状态。"""

    equipment_code: str = Field(..., description="机台编码")
    status: str = Field(..., description="当前机台状态，例如：运行、待机、停机")
    order_code: Optional[str] = Field(default=None, description="当前生产订单编号")
    product_code: Optional[str] = Field(default=None, description="当前生产产品型号")
    input_rate: Optional[float] = Field(
        default=None,
        ge=0,
        description="实时吞入速率，单位：片/小时,如果来源是半小时数量，需要先换算为片/小时",
    )
    output_rate: Optional[float] = Field(
        default=None,
        ge=0,
        description="实时产出速率，单位：片/小时,来源是半小时数量，需要先换算为片/小时",
    )
    completed_quantity: Optional[float] = Field(
        default=None,
        ge=0,
        description="订单已完成数量，单位：片",
    )


class MachineMaster(BaseModel):
    """机台主数据。"""

    equipment_code: str = Field(..., description="机台编码")
    equipment_name: Optional[str] = Field(default=None, description="机台名称")
    process_code: str = Field(..., description="机台所属工序编码")
    process_name: Optional[str] = Field(default=None, description="机台所属工序名称")
    line_code: Optional[str] = Field(
        default=None,
        description="机台所属产线编码",
    )
    line_name: Optional[str] = Field(
        default=None,
        description="机台所属产线名称",
    )
    


class ProductModel(BaseModel):
    """产品型号基础信息。"""

    product_code: str = Field(..., description="产品型号编码")
    product_name: Optional[str] = Field(default=None, description="产品型号名称")
    wafer_size: str = Field(..., description="硅片尺寸，例如:182、210")
    shape_code: str = Field(..., description="形状代码，例如:R、N、P")

class ProcessRouteStep(BaseModel):
    """工艺路线中的单个工序节点。"""

    process_code: str = Field(..., description="工序编码")
    process_name: Optional[str] = Field(default=None, description="工序名称")
    sequence_no: int = Field(..., ge=0, description="工序顺序号")
    upstream_process_code: Optional[str] = Field(default=None, description="上游工序编码")
    upstream_process_name: Optional[str] = Field(default=None, description="上游工序名称")
    downstream_process_code: Optional[str] = Field(default=None, description="下游工序编码")
    downstream_process_name: Optional[str] = Field(default=None, description="下游工序名称")
    unload_cache_type: Optional[str] = Field(default=None, description="下料可缓存类型")


class BufferSegment(BaseModel):
    """Buffer配置。"""

    buffer_code: str = Field(..., description="Buffer 编码")
    buffer_name: Optional[str] = Field(default=None, description="Buffer 名称")
    service_process_codes: List[str] = Field(
        default_factory=list,
        description="Buffer 服务的工序编码列表。确定buffer服务的上下游关系"
    )
    cycle_code: Optional[str] = Field(default=None, description="所属循环编码")
    cycle_name: Optional[str] = Field(default=None, description="所属循环名称")
    max_capacity: float = Field(..., ge=0, description="Buffer 最大容量，单位：片")
    buffer_type: Optional[str] = Field(default=None, description="Buffer 类型")
    safety_stock_lower_limit: Optional[float] = Field(
        default=None,
        ge=0,
        description="静态安全库存下限，单位：片",
    )

class BufferServiceProcess(BaseModel):
    """Buffer 服务工序明细。"""

    process_code: str = Field(..., description="服务工序列表.工序编码")
    process_name: Optional[str] = Field(default=None, description="服务工序列表.工序名称")


class BufferInventoryItem(BaseModel):
    """Buffer 区间库存明细。"""

    buffer_code: str = Field(..., description="Buffer 编码")
    source_process_code: str = Field(..., description="库存来源（上游）工序编码")
    source_process_name: Optional[str] = Field(default=None, description="库存来源(上游)工序名称")
    target_process_code: Optional[str] = Field(default=None, description="库存目标下游工序编码")
    target_process_name: Optional[str] = Field(default=None, description="库存目标下游工序名称")
    product_code: str = Field(..., description="库存对应产品型号")
    order_code: Optional[str] = Field(default=None, description="库存绑定订单编号")
    material_code: Optional[str] = Field(default=None, description="库存绑定物料编码")
    currentStockQuantity: Optional[int] = Field(
        default=None,
        ge=0,
        description="当前buffer库存量,单位:片"
    )


class MachineCapacityRecord(BaseModel):
    """机台在指定产品型号下的静态产能和工艺时长。"""

    equipment_code: str = Field(..., description="机台编码")
    product_code: str = Field(..., description="产品型号编码")
    actual_capacity: float = Field(..., ge=0, description="实际产能，单位：片/小时")
    rated_capacity: Optional[float] = Field(default=None, ge=0, description="额定产能，单位：片/小时")
    process_time_minutes: float = Field(..., ge=0, description="工艺时长，单位：分钟")


class OrderInfo(BaseModel):
    """订单信息。"""

    order_code: str = Field(..., description="订单编号")
    product_code: str = Field(..., description="订单产品型号")
    total_quantity: float = Field(..., ge=0, description="订单总数量，单位：片")
    completed_quantity: float = Field(default=0, ge=0, description="订单已完成数量，单位：片")


class AlgorithmConfig(BaseModel):
    """算法参数配置。"""

    cutline_lead_minutes: float = Field(default=30, ge=0, description="切线提前预警时间，单位：分钟")
    stability_window_minutes: float = Field(default=20, ge=0, description="切回判断稳定窗口，单位：分钟")
    silk_screen_clear_minutes: float = Field(default=30, ge=0, description="丝网清台停机时间，单位：分钟")
    schedule_interval_minutes: float = Field(default=5, gt=0, description="调度算法执行周期，单位：分钟")
    agv_delivery_minutes: float = Field(default=5, ge=0, description="AGV 送料到达预估时长，单位：分钟")
    mix_basket_count: int = Field(default=2, ge=1, description="混料批次标记花篮数，单位：篮")
    basket_capacity: int = Field(default=120, ge=1, description="单个花篮容量，单位：片/篮")
    max_feed_basket_count: int = Field(default=10, ge=1, description="上料区最大残留花篮数，单位：篮")


class CutlineEvent(BaseModel):
    """已确认发生的切线事件。"""

    equipment_code: str = Field(..., description="发生切线的机台编码")
    cut_time: datetime = Field(..., description="切线发生时间")
    previous_product_code: str = Field(..., description="切线前产品型号")
    next_product_code: str = Field(..., description="切线后产品型号")
    event_id: Optional[str] = Field(default=None, description="切线事件 ID")
    source_plan_id: Optional[str] = Field(default=None, description="来源切线方案 ID")
