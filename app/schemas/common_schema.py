# 通用基础对象

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class AlgorithmConfig(BaseModel):
    """算法参数配置。"""

    stockout_warning_lead_minutes: float = Field(
        default=30.0,
        gt=0,
        strict=True,
        allow_inf_nan=False,
        description="断料预警提前量，单位：分钟",
    )
    overflow_warning_lead_minutes: float = Field(
        default=30.0,
        gt=0,
        strict=True,
        allow_inf_nan=False,
        description="溢满预警提前量，单位：分钟",
    )
    stability_window_minutes: float = Field(
        default=20.0,
        gt=0,
        strict=True,
        allow_inf_nan=False,
        description="切回判断稳定窗口，单位：分钟",
    )
    silk_screen_clear_minutes: float = Field(
        default=30.0,
        gt=0,
        strict=True,
        allow_inf_nan=False,
        description="丝网清台停机时间，单位：分钟",
    )
    schedule_interval_minutes: float = Field(default=5, gt=0, description="调度算法执行周期，单位：分钟")
    cutline_execution_delay_minutes: float = Field(
        default=0.0,
        ge=0,
        strict=True,
        allow_inf_nan=False,
        description="当前默认方案生成后立即切线，单位：分钟",
    )
    agv_delivery_minutes: float = Field(
        default=5.0,
        ge=0,
        strict=True,
        allow_inf_nan=False,
        description="AGV 送料到达预估时长，单位：分钟",
    )
    mixed_basket_count: int = Field(
        default=10,
        gt=0,
        strict=True,
        description="预计标记为混料的花篮数量，单位：篮",
    )
    basket_capacity_pieces: int = Field(
        default=120,
        gt=0,
        strict=True,
        description="单个花篮标准片数，单位：片/篮",
    )
    mixing_input_max_baskets: int = Field(
        default=10,
        gt=0,
        strict=True,
        description="切线时上料区最坏残留花篮数量，单位：篮",
    )
class AlgorithmModel(BaseModel):
    """新版算法内部公共数据模型基类。"""

    model_config = ConfigDict(extra="forbid")


class AlgorithmActiveCutlineEvent(AlgorithmModel):
    """新版算法跨轮传入的单台机台活动切线跟踪事件。"""

    event_id: str = Field(..., min_length=1, description="活动切线事件唯一标识")
    plan_id: str | None = Field(
        default=None,
        min_length=1,
        description="仅内部新事件保留的来源正式切线方案标识",
    )
    machine_code: str = Field(..., description="当前被借用的机台编码")
    source_order_code: str = Field(..., description="切线前生产的原订单编码")
    target_order_code: str = Field(..., description="切线后支援的目标订单编码")
    workshop_code: str = Field(..., description="活动切线事件所属车间编码")
    source_buffer_code: str | None = Field(
        default=None,
        description="仅内部新事件保留的原订单产能借出Buffer编码",
    )
    target_buffer_code: str = Field(..., description="切回判断监测的目标Buffer编码")
    upstream_process_code: str = Field(..., description="目标区间上游工序编码")
    downstream_process_code: str = Field(..., description="目标区间下游工序编码")
    source_wafer_size: str | None = Field(
        default=None,
        description="仅内部新事件保留的原订单硅片尺寸",
    )
    source_wafer_spec: str | None = Field(
        default=None,
        description="仅内部新事件保留的原订单硅片规格",
    )
    target_wafer_size: str = Field(..., description="目标订单硅片尺寸")
    target_wafer_spec: str = Field(..., description="目标订单硅片规格")
    cutline_start_time: datetime = Field(..., description="机台实际开始执行切线的时间")
    negative_start_time: datetime | None = Field(
        default=None,
        description="目标区间净消耗速率连续小于0的开始时间",
    )
    status: Literal[
        "active",
        "return_recommended",
        "returned",
        "cancelled",
    ] = Field(default="active", description="活动切线事件当前状态")
    contribution_capacity: float | None = Field(
        default=None,
        ge=0,
        description="该机台切线贡献或减少的小时产能",
    )
    warning_type: Literal["stockout", "overflow"] | None = Field(
        default=None,
        description="触发来源的预警类型",
    )


class AlgorithmWorkshop(AlgorithmModel):
    """新版算法内部使用的车间基础数据。"""

    workshop_code: str = Field(..., description="车间编码")
    workshop_name: str | None = Field(...,description="车间名称，数据缺失时允许为空", )


class AlgorithmLine(AlgorithmModel):
    """新版算法内部使用的产线基础数据。"""

    line_code: str = Field(..., description="产线编码")
    line_name: str = Field(..., description="产线名称")
    wafer_spec: str = Field(...,description="产线绑定的硅片规格，用于判断该产线机台对应的 N、R、P 规格",)
    workshop_code: str = Field(..., description="产线所属车间编码")
    workshop_name: str | None = Field(...,description="产线所属车间名称，数据缺失时允许为空",)


class AlgorithmMachineLineRelation(AlgorithmModel):
    """新版算法内部使用的机台与产线编码关联关系。"""

    machine_code: str = Field(..., description="机台编码")
    line_code: str = Field(..., description="产线编码")


class AlgorithmMachineRuntime(AlgorithmModel):
    """新版算法内部使用的机台实时状态。"""

    machine_code: str = Field(..., description="机台编码")
    status: str = Field(..., description="机台当前生产状态")
    current_order_code: str | None = Field(...,description="机台当前生产的订单编码，无订单时允许为空",)
    tangent_time: datetime | None = Field(...,description="最近一次切线时间", )
    input_quantity_30m: float = Field(
        ...,
        ge=0,
        strict=True,
        allow_inf_nan=False,
        description="当前30分钟统计周期内的上料数量",
    )
    output_quantity_30m: float = Field(
        ...,
        ge=0,
        strict=True,
        allow_inf_nan=False,
        description="当前30分钟统计周期内的出料数量",
    )
    period_quantity_30m: float = Field(...,ge=0,description="当前30分钟统计周期内机台的累计产量",)
    out_time: datetime | None = Field(..., description="机台时间，无出料时允许为空",)


class AlgorithmMachineMaster(AlgorithmModel):
    """新版算法内部使用的机台基础数据。"""

    machine_code: str = Field(..., description="机台编码")
    machine_name: str = Field(..., description="机台名称")
    process_code: str = Field(..., description="机台所属工序编码")
    process_name: str = Field(..., description="机台所属工序名称")


class AlgorithmMachineProductCapacity(AlgorithmModel):
    """新版算法内部使用的机台与产品型号产能关系。"""

    machine_code: str = Field(..., description="机台编码")
    product_code: str = Field(..., description="产品型号编码")
    proc_seconds: float = Field(
        ...,
        ge=0,
        strict=True,
        allow_inf_nan=False,
        description="该机台生产指定产品时的工艺时间，单位为秒",
    )
    actual_capacity: float = Field(...,gt=0, description="该机台生产指定产品时的实际小时产能",)


class AlgorithmOrder(AlgorithmModel):
    """新版算法内部使用的订单数据。"""

    order_code: str = Field(..., description="订单编码")
    order_name: str = Field(..., description="订单名称")
    order_status: str = Field(..., description="订单状态")
    product_code: str = Field(..., description="订单对应的产品型号编码")
    product_name: str = Field(..., description="订单对应的产品型号名称")
    workshop_code: str = Field(..., description="订单所属车间编码")
    workshop_name: str | None = Field(...,description="订单所属车间名称，数据缺失时允许为空", )
    total_quantity: float = Field(..., ge=0, description="订单计划总数量")
    produced_quantity: float = Field(..., ge=0, description="订单累计已生产数量")
    piece_source: str = Field(..., description="订单片源")
    estimated_yield: str = Field(..., description="订单预计良率，保持字符串格式")

    @computed_field(
        description="订单未生产数量，由订单计划总量减去订单累计已生产量计算得到")
    @property
    def remaining_quantity(self) -> float:
        return self.total_quantity - self.produced_quantity

    @model_validator(mode="after")
    def validate_produced_quantity(self) -> AlgorithmOrder:
        if self.produced_quantity > self.total_quantity:
            raise ValueError("订单累计已生产数量不能大于订单计划总数量")
        return self


class AlgorithmProduct(AlgorithmModel):
    """新版算法内部使用的产品型号基础数据。"""

    product_code: str = Field(..., description="产品型号编码")
    product_name: str = Field(..., description="产品型号名称")
    wafer_size: str = Field(..., description="产品对应的硅片尺寸")
    source_grade: str = Field(..., description="产品对应的硅片片源等级")
    material_code: str = Field(..., description="产品对应的物料编码")
    material_name: str = Field(..., description="产品对应的物料名称")


class AlgorithmProcessRoute(AlgorithmModel):
    """新版算法内部使用的工艺路线节点。"""

    process_code: str = Field(..., description="工序编码")
    process_name: str = Field(..., description="工序名称")
    sequence: int = Field(..., ge=1, description="工序顺序号")
    cache_type: str = Field(..., description="下料可缓存类型")
    workshop_code: str = Field(..., description="工艺路线所属车间编码")
    workshop_name: str | None = Field(...,description="工艺路线所属车间名称，数据缺失时允许为空",)
    loop_code: str = Field(..., description="工艺路线所属循环编码")
    loop_name: str = Field(..., description="工艺路线所属循环名称")
    upstream_process_code: str | None = Field(...,description="上游工序编码，首工序允许为空",)
    upstream_process_name: str | None = Field(...,description="上游工序名称，首工序允许为空",)
    downstream_process_code: str | None = Field(..., description="下游工序编码，末工序允许为空",)
    downstream_process_name: str | None = Field(...,description="下游工序名称，末工序允许为空")


class AlgorithmBufferMaster(AlgorithmModel):
    """新版算法内部使用的单个物理小 Buffer 基础数据。"""

    buffer_code: str = Field(..., description="物理 Buffer 编码")
    buffer_name: str = Field(..., description="物理 Buffer 名称")
    buffer_type: str = Field(..., description="Buffer类型")
    buffer_type_title: str = Field(..., description="Buffer类型_类型")
    max_capacity: float = Field(...,gt=0,description="单个物理小 Buffer 的最大容量",)
    safety_low: float = Field(..., ge=0, description="安全库存下限")
    served_process_codes: list[str] = Field(...,description="物理 Buffer 服务的工序编码列表",)
    served_process_names: list[str] = Field(...,description="物理 Buffer 服务的工序名称列表",
    )
    loop_code: str = Field(..., description="物理 Buffer 所属循环编码")
    loop_name: str = Field(..., description="物理 Buffer 所属循环名称")



class AlgorithmBufferProcessRelation(AlgorithmModel):
    """新版算法内部使用的物理 Buffer 与工序区间关系。"""

    buffer_code: str = Field(..., description="物理 Buffer 编码")
    workshop_code: str = Field(..., description="Buffer 所属车间")
    upstream_process_code: str = Field(...,description="Buffer 对应区间的上游工序",)
    downstream_process_code: str = Field(..., description="Buffer 对应区间的下游工序",)


class AlgorithmBufferOrderInventory(AlgorithmModel):
    """新版算法内部使用的订单与物理 Buffer 库存明细（buffer实时数据）。"""

    main_id: str = Field(..., description="多个物理 Buffer 共同参与计算的分组编码")
    buffer_code: str = Field(..., description="物理 Buffer 编码")
    order_code: str = Field(..., description="订单编码")
    current_quantity: float = Field(...,ge=0,description="指定订单在当前物理 Buffer 中的库存数量",)


class AlgorithmAgvRelation(AlgorithmModel):
    """新版算法内部使用的 AGV 机台当前订单绑定。"""

    machine_code: str = Field(..., description="机台编码")
    machine_name: str = Field(..., description="机台名称")
    order_code: str = Field(..., description="当前订单编码")
    order_name: str = Field(..., description="当前订单名称")
    binding_time: datetime = Field(..., description="AGV 定线绑定记录时间")
