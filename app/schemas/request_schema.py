# 后端传给算法服务的请求数据格式

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
from app.schemas.pending_cutline_schema import PendingCutlinePlan
from app.utils.time_utils import normalize_local_time


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
    machine_code: str = Field(
        ...,
        description="机台实时状态使用的 P166 集团编码，对应静态机台 p166_jt_group",
    )
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
    out_time: datetime | None = Field(..., description="运行态出料时间，无出料时间时为 null")


class MachineMasterRequest(RequestModel):
    machine_code: str = Field(
        ...,
        description="静态机台标准编码，对应 AGV equipmentid，并作为算法内部机台编码",
    )
    p166_jt_group: str = Field(
        ...,
        description="P166 集团机台编码，对应机台实时状态中的 machine_code",
    )
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
    workshop_code: str = Field(
        ...,
        description=(
            "产线自身所属车间编码；兼容保留，不作为机台所属车间的算法依据"
        ),
    )
    workshop_name: str = Field(..., description="产线所属车间名称")


class MachineLineRequest(RequestModel):
    """兼容保留的机台产线关系，不作为机台所属车间的算法依据。"""

    machine_code: str = Field(..., description="机台与产线关联关系中的机台编码")
    machine_name: str = Field(..., description="机台与产线关联关系中的机台名称")
    line_code: str = Field(..., description="机台与产线关联关系中的产线编码")
    line_name: str = Field(..., description="机台与产线关联关系中的产线名称")
    wafer_spec: str = Field(..., description="机台关联产线绑定的硅片规格")


class OrderRequest(RequestModel):
    order_code: str = Field(..., description="订单编码")
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
    workshop_code: str = Field(
        ...,
        description=(
            "工艺路线所属车间编码，也是机台按所属工序解析车间的权威来源"
        ),
    )
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
    bound_source_name: str = Field(
        ...,
        description="Buffer 当前绑定的产品型号名称，用于匹配当前订单 product_name",
    )
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
    machine_code: str = Field(
        ...,
        description="AGV equipmentid 投影的标准机台编码",
    )
    machine_name: str = Field(..., description="AGV 绑定的机台名称")
    product_name: str = Field(..., description="AGV linename 投影的当前产品型号名称")
    previous_product_name: str | None = Field(
        ...,
        description="AGV lastlinename 投影的上一产品型号名称，允许为 null 或空值",
    )
    wafer_spec: str = Field(..., description="AGV 绑定的当前订单硅片规格")
    binding_time: datetime = Field(..., description="AGV 定线绑定记录时间")


class ActiveCutlineEventRequest(RequestModel):
    """后端保存并在下一轮回传的最小活动切线跟踪事件。"""

    event_id: str = Field(..., min_length=1, description="活动切线事件唯一标识")
    plan_id: str | None = Field(
        default=None,
        min_length=1,
        description="确认该事件的待确认切线方案标识",
    )
    warning_id: str | None = Field(default=None, min_length=1)
    machine_code: str = Field(..., description="当前被借用的机台编码")
    source_order_code: str = Field(..., description="切线前生产的原订单编码")
    target_order_code: str = Field(..., description="切线后支援的目标订单编码")
    workshop_code: str = Field(..., description="活动切线事件所属车间编码")
    source_buffer_code: str | None = Field(
        default=None,
        description="原订单产能借出 Buffer 编码",
    )
    target_buffer_code: str = Field(..., description="切回判断监测的目标Buffer编码")
    upstream_process_code: str = Field(..., description="目标区间上游工序编码")
    downstream_process_code: str = Field(..., description="目标区间下游工序编码")
    source_wafer_size: str | None = Field(
        default=None,
        description="原订单硅片尺寸",
    )
    source_wafer_spec: str | None = Field(
        default=None,
        description="原订单硅片规格",
    )
    target_wafer_size: str = Field(..., description="目标订单硅片尺寸")
    target_wafer_spec: str = Field(..., description="目标订单硅片规格")
    cutline_start_time: datetime = Field(
        ...,
        description=(
            "AGV记录首次观察到绑定变化时间，不等于精确物理切线时间"
        ),
    )
    negative_start_time: datetime | None = Field(
        ...,
        description="目标区间净消耗速率连续小于0的开始时间",
    )
    status: Literal[
        "active",
        "return_recommended",
        "returned",
        "cancelled",
    ] = Field(default="active")
    contribution_capacity: float | None = Field(
        default=None,
        ge=0,
        description="确认切线机台贡献或减少的小时产能",
    )
    warning_type: Literal["stockout", "overflow"] | None = Field(
        default=None,
        description="触发来源的预警类型",
    )
    process_code: str | None = Field(
        default=None,
        description="确认切线机台所属的输出侧工序编码",
    )
    warning_buffer_code: str | None = Field(
        default=None,
        description="触发切线方案的预警 Buffer 编码",
    )
    warning_upstream_process_code: str | None = Field(
        default=None,
        description="预警 Buffer 对应区间的上游工序编码",
    )
    warning_downstream_process_code: str | None = Field(
        default=None,
        description="预警 Buffer 对应区间的下游工序编码",
    )
    is_recommended_candidate: bool | None = Field(
        default=None,
        description="确认机台是否来自原方案推荐候选列表",
    )

    @field_validator("plan_id", "warning_id")
    @classmethod
    def validate_optional_identifier(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("optional identifier must not be blank")
        return value


def validate_confirmed_pending_active_coverage(
    pending_plans: list[PendingCutlinePlan],
    active_events: Sequence[
        ActiveCutlineEventRequest | AlgorithmActiveCutlineEvent
    ],
) -> None:
    """Require every persisted Pending confirmation to retain its real event."""
    for plan in pending_plans:
        baseline_by_code = {
            item.machine_code: item
            for item in plan.baseline_machine_bindings
        }
        for machine_code in plan.confirmed_machine_codes:
            baseline = baseline_by_code[machine_code]
            if any(
                _active_event_matches_confirmation(
                    plan=plan,
                    machine_code=machine_code,
                    baseline_order_code=baseline.order_code,
                    baseline_process_code=baseline.process_code,
                    event=event,
                )
                for event in active_events
            ):
                continue
            raise ValueError(
                "pending_cutline_plans "
                f"plan_id={plan.plan_id}, warning_id={plan.warning_id}, "
                f"confirmed_machine_code={machine_code} requires a matching "
                "active_cutline_events record"
            )


def _active_event_matches_confirmation(
    *,
    plan: PendingCutlinePlan,
    machine_code: str,
    baseline_order_code: str,
    baseline_process_code: str,
    event: ActiveCutlineEventRequest | AlgorithmActiveCutlineEvent,
) -> bool:
    if event.machine_code != machine_code:
        return False
    has_full_identity = (
        event.plan_id == plan.plan_id
        and event.warning_id == plan.warning_id
    )
    has_legacy_identity = (
        event.plan_id is None
        and event.warning_id is None
        and event.event_id == f"CUT-{plan.plan_id}-{machine_code}"
    )
    if not has_full_identity and not has_legacy_identity:
        return False
    if (
        event.source_order_code != baseline_order_code
        or event.workshop_code != plan.workshop_code
    ):
        return False
    if plan.warning_type == "stockout":
        direction_is_valid = (
            baseline_order_code != plan.monitored_order_code
            and event.target_order_code == plan.monitored_order_code
        )
    else:
        direction_is_valid = (
            baseline_order_code == plan.monitored_order_code
            and event.target_order_code != plan.monitored_order_code
        )
    if not direction_is_valid:
        return False
    observed_at = normalize_local_time(event.cutline_start_time)
    if not (
        normalize_local_time(plan.created_at)
        < observed_at
        <= normalize_local_time(plan.expire_at)
    ):
        return False
    if (
        event.process_code is not None
        and event.process_code != baseline_process_code
    ):
        return False
    return not (
        event.warning_type is not None
        and event.warning_type != plan.warning_type
    )


class CutlineAlgorithmRequest(RequestModel):
    snapshot_meta: SnapshotMetaRequest = Field(..., description="算法运行上下文、版本和降级标记")
    machine_realtime: list[MachineRealtimeRequest] = Field(..., description="机台实时状态及当前统计周期数量")
    machine_master: list[MachineMasterRequest] = Field(
        ...,
        description="机台标准编码、P166 实时编码及所属工序的基础信息",
    )
    machine_process_times: list[MachineProcessTimeRequest] = Field(..., description="机台与产品型号的工艺时间和实际产能关系")
    workshops: list[WorkshopRequest] = Field(..., description="车间基础信息")
    lines: list[LineRequest] = Field(
        default_factory=list,
        description="可选的产线兼容数据，当前核心算法不依赖",
    )
    machine_lines: list[MachineLineRequest] = Field(
        default_factory=list,
        description="可选的机台—产线兼容关系，当前核心算法不依赖",
    )
    orders: list[OrderRequest] = Field(..., description="订单数量、产品和所属车间信息")
    products: list[ProductRequest] = Field(..., description="产品型号、片源等级和物料信息")
    process_routes: list[ProcessRouteRequest] = Field(..., description="工艺路线顺序、缓存、循环及上下游关系")
    buffer_realtime: list[BufferRealtimeRequest] = Field(..., description="Buffer 当前实时库存及占用率")
    buffer_master: list[BufferMasterRequest] = Field(..., description="Buffer 容量、安全库存、服务工序及所属循环信息")
    agv_relations: list[AgvRelationRequest] = Field(
        ...,
        description="AGV 提供的机台当前产品型号、上一产品型号及记录时间",
    )
    pending_cutline_plans: list[PendingCutlinePlan] = Field(
        default_factory=list,
        description="后端持久化并在本轮回传的待确认切线方案列表",
    )
    active_cutline_events: list[ActiveCutlineEventRequest] = Field(
        default_factory=list,
        description="后端保存并在本轮重新传入的活动切线事件列表",
    )
    return_suggested_event_ids: list[str] = Field(
        default_factory=list,
        description="Backend-persisted event ids that already produced a return suggestion",
    )
    mixed_cutline_event_ids: list[str] = Field(
        default_factory=list,
        description="Backend-persisted event ids that already produced a real mixing record",
    )

    @field_validator(
        "return_suggested_event_ids", "mixed_cutline_event_ids"
    )
    @classmethod
    def validate_persisted_event_ids(cls, value: list[str]) -> list[str]:
        if any(not event_id.strip() for event_id in value):
            raise ValueError("persisted event ids must not be blank")
        if len(value) != len(set(value)):
            raise ValueError("persisted event ids must not contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_confirmed_pending_events(self) -> CutlineAlgorithmRequest:
        validate_confirmed_pending_active_coverage(
            self.pending_cutline_plans,
            self.active_cutline_events,
        )
        return self


class AlgorithmSnapshot(BaseModel):
    """新版切线算法内部使用的统一数据快照。"""

    current_time: datetime = Field(...,description="本次算法计算所使用的数据快照时间",)

    workshops: list[AlgorithmWorkshop] = Field(...,description="算法使用的车间基础数据列表",)
    lines: list[AlgorithmLine] = Field(
        default_factory=list,
        description=(
            "可选兼容产线基础数据列表；兼容保留产线所属车间和硅片规格，"
            "但二者均不作为机台所属车间或当前生产规格的算法依据"
        ),
    )
    machine_lines: list[AlgorithmMachineLineRelation] = Field(
        default_factory=list,
        description=(
            "可选兼容机台与产线绑定关系列表，不作为核心算法的数据依据"
        ),
    )

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

    pending_cutline_plans: list[PendingCutlinePlan] = Field(
        default_factory=list,
        description="后端持久化并回传的待确认切线方案列表",
    )
    agv_binding_history: list[AlgorithmAgvRelation] = Field(
        default_factory=list,
        description="待确认切线窗口内的AGV绑定历史列表",
    )

    active_cutline_events: list[AlgorithmActiveCutlineEvent] = Field(
        default_factory=list,
        description="当前仍需跟踪的切线事件列表",
    )
    return_suggested_event_ids: list[str] = Field(
        default_factory=list,
        description="Backend-persisted event ids that already produced a return suggestion",
    )
    mixed_cutline_event_ids: list[str] = Field(
        default_factory=list,
        description="Backend-persisted event ids that already produced a real mixing record",
    )

    @field_validator(
        "return_suggested_event_ids", "mixed_cutline_event_ids"
    )
    @classmethod
    def validate_persisted_event_ids(cls, value: list[str]) -> list[str]:
        if any(not event_id.strip() for event_id in value):
            raise ValueError("persisted event ids must not be blank")
        if len(value) != len(set(value)):
            raise ValueError("persisted event ids must not contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_confirmed_pending_events(self) -> AlgorithmSnapshot:
        validate_confirmed_pending_active_coverage(
            self.pending_cutline_plans,
            self.active_cutline_events,
        )
        return self

    config: AlgorithmConfig = Field(
        default_factory=AlgorithmConfig,
        description="切线算法运行参数配置",
    )
