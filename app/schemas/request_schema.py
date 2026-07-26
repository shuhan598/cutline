# 后端传给算法服务的请求数据格式

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common_schema import (
    AlgorithmActiveCutlineEvent,
    AlgorithmAgvRelation,
    AlgorithmBufferMaster,
    AlgorithmBufferOrderInventory,
    AlgorithmBufferProcessRelation,
    AlgorithmConfig,
    AlgorithmLine,
    AlgorithmMachineLineRelation,
    AlgorithmMachineMaster,
    AlgorithmMachineProductCapacity,
    AlgorithmMachineRuntime,
    AlgorithmOrder,
    AlgorithmProcessRoute,
    AlgorithmProduct,
    AlgorithmWorkshop,
)


class RequestModel(BaseModel):
    """后端原始算法请求的严格基础模型。"""

    model_config = ConfigDict(extra="forbid")


class SnapshotMetaRequest(RequestModel):
    run_id: str = Field(..., description="本次算法运行编号")
    trigger_type: str = Field(..., description="本次算法运行的触发方式")
    workshop_id: str = Field(..., description="当前车间编号")
    snapshot_time: datetime = Field(..., description="本次请求快照的生成时间")
    params_version: int = Field(..., description="本次请求使用的算法参数版本")
    catalog_version: str = Field(..., description="本次请求使用的静态目录版本")
    catalog_loaded_at: datetime = Field(..., description="静态目录数据的加载时间")
    degraded_flags: list[str] = Field(..., description="数据缺失或降级处理的诊断标记列表")


class MachineRealtimeRequest(RequestModel):
    machine_code: str = Field(..., description="机台编码")
    status: str = Field(..., description="机台当前生产状态")
    tangent_time: datetime | None = Field(..., description="机台切线时间，无切线时间时为 null")
    input_quantity: float = Field(
        ...,
        ge=0,
        strict=True,
        allow_inf_nan=False,
        description="当前统计周期内（30分钟）的上料数量",
    )
    output_quantity: float = Field(
        ...,
        ge=0,
        strict=True,
        allow_inf_nan=False,
        description="当前统计周期内（30分钟）的出料数量",
    )
    completed_quantity: float = Field(..., ge=0, description="当前统计周期内（30分钟）的已完成数量")
    period_quantity: float = Field(..., ge=0, description="当前统计周期内（30分钟）的产量，主要看丝网")
    out_time: datetime | None = Field(..., description="运行态出料时间，无出料时间时为 null")


class MachineMasterRequest(RequestModel):
    machine_code: str = Field(..., description="机台编码")
    machine_name: str = Field(..., description="机台名称")
    process_code: str = Field(..., description="机台所属工序编码")
    process_name: str = Field(..., description="机台所属工序名称")


class MachineProcessTimeRequest(RequestModel):
    machine_code: str = Field(..., description="机台与产品型号关系中的机台编码")
    machine_name: str = Field(..., description="机台与产品型号关系中的机台名称")
    product_code: str = Field(..., description="机台与产品型号关系中的产品型号编码")
    product_name: str = Field(..., description="机台与产品型号关系中的产品型号名称")
    proc_seconds: float = Field(
        ...,
        ge=0,
        strict=True,
        allow_inf_nan=False,
        description="机台与产品型号组合对应的工艺时间，单位为秒",
    )
    actual_capacity: float = Field(..., gt=0, description="机台与产品型号组合对应的实际产能")


class WorkshopRequest(RequestModel):
    workshop_code: str = Field(..., description="车间编码")
    workshop_name: str | None = Field(..., description="车间名称，数据缺失时为 null")


class LineRequest(RequestModel):
    line_code: str = Field(..., description="产线编码")
    line_name: str = Field(..., description="产线名称")
    wafer_spec: str = Field(..., description="产线绑定的硅片规格")
    workshop_code: str = Field(..., description="产线所属车间编码")
    workshop_name: str = Field(..., description="产线所属车间名称")


class MachineLineRequest(RequestModel):
    machine_code: str = Field(..., description="机台与产线关联关系中的机台编码")
    machine_name: str = Field(..., description="机台与产线关联关系中的机台名称")
    line_code: str = Field(..., description="机台与产线关联关系中的产线编码")
    line_name: str = Field(..., description="机台与产线关联关系中的产线名称")
    wafer_spec: str = Field(..., description="机台关联产线绑定的硅片规格")


class OrderRequest(RequestModel):
    order_code: str = Field(..., description="订单编码")
    order_name: str = Field(..., description="订单名称，例如：至上；不能为空")
    order_status: str = Field(..., description="订单状态")
    total_quantity: float = Field(..., ge=0, description="订单计划生产的总数量")
    piece_source: str = Field(..., description="订单片源")
    estimated_yield: str = Field(..., description="订单预计良率，保持后端传入的字符串格式")
    product_code: str = Field(..., description="订单对应的产品型号编码")
    product_name: str = Field(..., description="订单对应的产品型号名称")
    workshop_code: str = Field(..., description="订单所属车间编码")
    workshop_name: str = Field(..., description="订单所属车间名称")
    produced_quantity: float = Field(..., ge=0, description="订单已经生产完成的数量")
    remaining_quantity: float = Field(..., ge=0, description="订单尚未生产的剩余数量")


class ProductRequest(RequestModel):
    product_code: str = Field(..., description="产品型号编码")
    product_name: str = Field(..., description="产品型号名称")
    wafer_size: str = Field(..., description="产品对应的硅片尺寸")
    source_grade: str = Field(..., description="产品对应的硅片片源等级")
    material_code: str = Field(..., description="产品对应的物料编码")
    material_name: str = Field(..., description="产品对应的物料名称")


class ProcessRouteRequest(RequestModel):
    process_code: str = Field(..., description="工艺路线节点的工序编码")
    process_name: str = Field(..., description="工艺路线节点的工序名称")
    sequence: int = Field(..., description="工序在工艺路线中的顺序号")
    cache_type: str = Field(..., description="该工序的下料可缓存类型")
    workshop_code: str = Field(..., description="工艺路线所属车间编码")
    workshop_name: str = Field(..., description="工艺路线所属车间名称")
    loop_code: str = Field(..., description="工艺路线所属循环编码")
    loop_name: str = Field(..., description="工艺路线所属循环名称")
    upstream_process_code: str | None = Field(..., description="上游工序编码，首工序时为 null")
    upstream_process_name: str | None = Field(..., description="上游工序名称，首工序时为 null")
    downstream_process_code: str | None = Field(..., description="下游工序编码，末工序时为 null")
    downstream_process_name: str | None = Field(..., description="下游工序名称，末工序时为 null")


class BufferRealtimeRequest(RequestModel):
    main_id: str | None = Field(..., description="Buffer 实时数据主记录编号，缺失时为 null")
    buffer_code: str = Field(..., description="Buffer 编码")
    bound_source_name: str = Field(..., description="Buffer 绑定来源订单的名称，用于匹配订单数据中的 order_name")
    current_quantity: float = Field(..., ge=0, description="Buffer 当前实时库存数量")
    current_utilization_rate: float = Field(..., ge=0, description="Buffer 当前实时占用率")


class BufferMasterRequest(RequestModel):
    buffer_code: str = Field(..., description="Buffer 编码")
    buffer_name: str = Field(..., description="Buffer 名称")
    buffer_type: str = Field(..., description="Buffer 类型")
    buffer_type_title: str = Field(..., description="Buffer 类型的标题名称")
    max_capacity: float = Field(..., gt=0, description="Buffer 最大容量")
    safety_low: float = Field(..., ge=0, description="Buffer 安全库存下限")
    served_process_codes: list[str] = Field(..., description="Buffer 服务的工序编码列表，允许为空列表")
    served_process_names: list[str] = Field(..., description="Buffer 服务的工序名称列表，允许为空列表")
    loop_code: str = Field(..., description="Buffer 所属循环编码")
    loop_name: str = Field(..., description="Buffer 所属循环名称")


class AgvRelationRequest(RequestModel):
    machine_code: str = Field(..., description="AGV 绑定的机台编码")
    machine_name: str = Field(..., description="AGV 绑定的机台名称")
    order_code: str = Field(..., description="AGV 绑定的当前订单编码")
    order_name: str = Field(..., description="AGV 绑定的当前订单名称")
    wafer_spec: str = Field(..., description="AGV 绑定的当前订单硅片规格")
    binding_time: datetime = Field(..., description="AGV 定线绑定记录时间")


class ActiveCutlineEventRequest(RequestModel):
    """后端保存并在下一轮回传的最小活动切线跟踪事件。"""

    event_id: str = Field(..., min_length=1, description="活动切线事件唯一标识")
    machine_code: str = Field(..., description="当前被借用的机台编码")
    source_order_code: str = Field(..., description="切线前生产的原订单编码")
    target_order_code: str = Field(..., description="切线后支援的目标订单编码")
    workshop_code: str = Field(..., description="活动切线事件所属车间编码")
    target_buffer_code: str = Field(..., description="切回判断监测的目标Buffer编码")
    upstream_process_code: str = Field(..., description="目标区间上游工序编码")
    downstream_process_code: str = Field(..., description="目标区间下游工序编码")
    target_wafer_size: str = Field(..., description="目标订单硅片尺寸")
    target_wafer_spec: str = Field(..., description="目标订单硅片规格")
    cutline_start_time: datetime = Field(..., description="机台实际开始执行切线的时间")
    negative_start_time: datetime | None = Field(
        ...,
        description="目标区间净消耗速率连续小于0的开始时间",
    )


class CutlineAlgorithmRequest(RequestModel):
    snapshot_meta: SnapshotMetaRequest = Field(..., description="算法运行上下文、版本和降级标记")
    machine_realtime: list[MachineRealtimeRequest] = Field(..., description="机台实时状态及当前统计周期数量")
    machine_master: list[MachineMasterRequest] = Field(..., description="机台及其所属工序的基础信息")
    machine_process_times: list[MachineProcessTimeRequest] = Field(..., description="机台与产品型号的工艺时间和实际产能关系")
    workshops: list[WorkshopRequest] = Field(..., description="车间基础信息")
    lines: list[LineRequest] = Field(..., description="产线、硅片规格及所属车间信息")
    machine_lines: list[MachineLineRequest] = Field(..., description="机台与产线的关联关系")
    orders: list[OrderRequest] = Field(..., description="订单数量、产品和所属车间信息")
    products: list[ProductRequest] = Field(..., description="产品型号、片源等级和物料信息")
    process_routes: list[ProcessRouteRequest] = Field(..., description="工艺路线顺序、缓存、循环及上下游关系")
    buffer_realtime: list[BufferRealtimeRequest] = Field(..., description="Buffer 当前实时库存及占用率")
    buffer_master: list[BufferMasterRequest] = Field(..., description="Buffer 容量、安全库存、服务工序及所属循环信息")
    agv_relations: list[AgvRelationRequest] = Field(..., description="AGV 提供的机台当前订单绑定及记录时间")
    active_cutline_events: list[ActiveCutlineEventRequest] = Field(
        default_factory=list,
        description="后端保存并在本轮重新传入的活动切线事件列表",
    )


class AlgorithmSnapshot(BaseModel):
    """新版切线算法内部使用的统一数据快照。"""

    current_time: datetime = Field(...,description="本次算法计算所使用的数据快照时间",)

    workshops: list[AlgorithmWorkshop] = Field(...,description="算法使用的车间基础数据列表",)
    lines: list[AlgorithmLine] = Field(
        ...,
        description=(
            "算法使用的产线基础数据列表，保留产线绑定硅片规格兼容字段，"
            "用于支持机台—产线—车间归属关系，不作为机台当前实际生产规格的数据来源"
        ),
    )
    machine_lines: list[AlgorithmMachineLineRelation] = Field(...,description="机台与产线之间的绑定关系列表",)

    machine_runtimes: list[AlgorithmMachineRuntime] = Field(...,description="快照时刻的机台实时运行状态列表",)
    machine_masters: list[AlgorithmMachineMaster] = Field(...,description="机台基础信息列表，包括机台所属工序",)
    machine_product_capacities: list[AlgorithmMachineProductCapacity] = Field(...,description="机台与产品型号之间的工艺时间和实际产能关系列表",)

    orders: list[AlgorithmOrder] = Field(...,description="算法使用的生产订单列表，订单未生产量由计划总量减去累计已生产量计算",)
    products: list[AlgorithmProduct] = Field(...,description="算法使用的产品型号基础数据列表",)
    process_routes: list[AlgorithmProcessRoute] = Field(
        ...,
        description="车间各循环中的工艺路线步骤列表，包括工序顺序和上下游工序关系",
    )

    buffer_masters: list[AlgorithmBufferMaster] = Field(
        ...,
        description="物理小Buffer基础数据列表，包括容量、安全库存、服务工序和所属循环",
    )
    buffer_process_relations: list[AlgorithmBufferProcessRelation] = Field(
        ...,
        description="物理Buffer与所属车间、上下游工序区间之间的关系列表",
    )
    buffer_order_inventories: list[AlgorithmBufferOrderInventory] = Field(
        ...,
        description="当前快照时刻，各订单在各物理Buffer中的实时库存明细列表",
    )

    agv_relations: list[AlgorithmAgvRelation] = Field(
        ...,
        description="算法使用的AGV调度关系列表",
    )

    active_cutline_events: list[AlgorithmActiveCutlineEvent] = Field(
        default_factory=list,
        description="当前仍需跟踪的切线事件列表",
    )
    config: AlgorithmConfig = Field(
        default_factory=AlgorithmConfig,
        description="切线算法运行参数配置",
    )
