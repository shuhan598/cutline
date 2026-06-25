# 算法服务返回给后端的结果数据格式

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.schemas.common_schema import CutlineEvent


class WarningResult(BaseModel):
    """断料或溢满预警结果。"""

    warning_id: Optional[str] = Field(default=None, description="预警 ID")
    warning_time: datetime = Field(..., description="预警触发时间")
    warning_type: str = Field(..., description="预警类型，例如：stockout、overflow")
    buffer_code: str = Field(..., description="预警 Buffer 段编码")
    cycle_code: Optional[str] = Field(default=None, description="预警所属循环编码")
    cycle_name: Optional[str] = Field(default=None, description="预警所属循环名称")
    workshop_code: Optional[str] = Field(default=None, description="预警所属车间编码")
    workshop_name: Optional[str] = Field(default=None, description="预警所属车间名称")
    upstream_process_code: str = Field(..., description="预警区间上游工序编码")
    downstream_process_code: str = Field(..., description="预警区间下游工序编码")
    product_code: str = Field(..., description="预警产品型号")
    inventory_quantity: Optional[float] = Field(default=None, ge=0, description="当前区间库存数量，单位：片")
    net_rate: Optional[float] = Field(default=None, description="区间净消耗速率，单位：片/小时")
    prediction_minutes: Optional[float] = Field(default=None, ge=0, description="预测耗尽或溢满时间，单位：分钟")
    cutline_lead_minutes: Optional[float] = Field(default=None, ge=0, description="切线提前预警时间，单位：分钟")
    capacity_gap: Optional[float] = Field(default=None, description="产能缺口或过剩量，单位：片/小时")
    message: Optional[str] = Field(default=None, description="预警说明")


class SelectedMachine(BaseModel):
    """切线方案中选中的机台。"""

    equipment_code: str = Field(..., description="机台编码")
    workshop_code: Optional[str] = Field(default=None, description="机台所属车间编码")
    workshop_name: Optional[str] = Field(default=None, description="机台所属车间名称")
    current_product_code: Optional[str] = Field(default=None, description="当前生产产品型号")
    target_product_code: Optional[str] = Field(default=None, description="建议切入目标产品型号")
    wafer_size: Optional[str] = Field(default=None, description="硅片尺寸")
    shape_code: Optional[str] = Field(default=None, description="形状代码")
    process_code: Optional[str] = Field(default=None, description="所属工序编码")
    utilization_rate: Optional[float] = Field(default=None, ge=0, description="产能利用率，取值范围建议为 0~1")
    idle_rate: Optional[float] = Field(default=None, ge=0, description="机台空闲度，取值范围建议为 0~1")
    actual_capacity: Optional[float] = Field(default=None, ge=0, description="当前型号实际产能，单位：片/小时")
    contribution_capacity: Optional[float] = Field(default=None, ge=0, description="切换后可贡献产能，单位：片/小时")


class CutlinePlan(BaseModel):
    """切线推荐方案。"""

    plan_id: Optional[str] = Field(default=None, description="切线方案 ID")
    workshop_code: Optional[str] = Field(default=None, description="切线方案所属车间编码")
    workshop_name: Optional[str] = Field(default=None, description="切线方案所属车间名称")
    warning: WarningResult = Field(..., description="触发该方案的预警")
    selected_machines: List[SelectedMachine] = Field(default_factory=list, description="建议切线机台列表")
    total_contribution_capacity: float = Field(default=0, ge=0, description="补充产能合计，单位：片/小时")
    remaining_capacity_gap: Optional[float] = Field(default=None, description="剩余产能缺口，单位：片/小时")
    cutline_start_time: Optional[datetime] = Field(default=None, description="建议切线开始时间")
    expected_return_time: Optional[datetime] = Field(default=None, description="预计切回时间，后续可动态更新")
    requires_silk_screen_clear: bool = Field(default=False, description="是否需要丝网清台")
    silk_screen_clear_minutes: Optional[float] = Field(default=None, ge=0, description="丝网清台停机时间，单位：分钟")
    message: Optional[str] = Field(default=None, description="方案说明")


class ManualIntervention(BaseModel):
    """人工介入提示。"""

    intervention_id: Optional[str] = Field(default=None, description="人工介入提示 ID")
    workshop_code: Optional[str] = Field(default=None, description="人工介入所属车间编码")
    workshop_name: Optional[str] = Field(default=None, description="人工介入所属车间名称")
    warning: WarningResult = Field(..., description="触发人工介入的预警")
    reason: str = Field(..., description="需要人工介入的原因")
    required_capacity: Optional[float] = Field(default=None, description="仍需补充产能，单位：片/小时")
    candidate_machines: List[SelectedMachine] = Field(default_factory=list, description="可展示给操作员的候选机台列表")
    message: Optional[str] = Field(default=None, description="人工介入说明")


class ReturnSuggestion(BaseModel):
    """切回建议。"""

    suggestion_id: Optional[str] = Field(default=None, description="切回建议 ID")
    suggestion_time: datetime = Field(..., description="切回建议触发时间")
    equipment_code: str = Field(..., description="建议切回的机台编码")
    workshop_code: Optional[str] = Field(default=None, description="建议切回机台所属车间编码")
    workshop_name: Optional[str] = Field(default=None, description="建议切回机台所属车间名称")
    product_code: str = Field(..., description="当前被补充的产品型号")
    original_product_code: Optional[str] = Field(default=None, description="建议切回的原产品型号")
    buffer_code: Optional[str] = Field(default=None, description="关联 Buffer 段编码")
    upstream_process_code: Optional[str] = Field(default=None, description="关联区间上游工序编码")
    downstream_process_code: Optional[str] = Field(default=None, description="关联区间下游工序编码")
    negative_start_time: Optional[datetime] = Field(default=None, description="净消耗速率首次转负时间")
    negative_duration_minutes: Optional[float] = Field(default=None, ge=0, description="净消耗速率连续为负的时长，单位：分钟")
    inventory_quantity: Optional[float] = Field(default=None, ge=0, description="当前区间库存数量，单位：片")
    safety_inventory_quantity: Optional[float] = Field(default=None, ge=0, description="安全库存水位，单位：片")
    net_rate: Optional[float] = Field(default=None, description="当前区间净消耗速率，单位：片/小时")
    message: Optional[str] = Field(default=None, description="切回建议说明")


class CutlineEvaluateResponse(BaseModel):
    """切线评估统一响应。"""

    success: bool = Field(default=True, description="请求是否处理成功")
    message: str = Field(default="", description="响应说明")
    warnings: List[WarningResult] = Field(default_factory=list, description="预警结果列表")
    plans: List[CutlinePlan] = Field(default_factory=list, description="切线方案列表")
    manual_interventions: List[ManualIntervention] = Field(default_factory=list, description="人工介入提示列表")
    return_suggestions: List[ReturnSuggestion] = Field(default_factory=list, description="切回建议列表")
    tracked_events: List["CutlineEvent"] = Field(
        default_factory=list,
        description="回吐给后端续存的被跟踪切线事件（含最新 negative_start_time）",
    )


class MixTraceNotification(BaseModel):
    """混料通知。"""

    notification_id: Optional[str] = Field(default=None, description="混料通知 ID")
    source_equipment_code: str = Field(..., description="来源机台编码")
    workshop_code: Optional[str] = Field(default=None, description="混料通知所属车间编码")
    workshop_name: Optional[str] = Field(default=None, description="混料通知所属车间名称")
    cut_time: datetime = Field(..., description="切线发生时间")
    previous_product_code: str = Field(..., description="切线前产品型号")
    next_product_code: str = Field(..., description="切线后产品型号")
    mix_start_time: datetime = Field(..., description="混料起始时刻")
    mix_basket_count: int = Field(..., ge=1, description="混料花篮数，单位：篮")
    estimated_total_quantity: float = Field(..., ge=0, description="混料批次估算总片数，单位：片")
    product_compositions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="混料型号组成列表，建议包含 product_code、sequence_no、estimated_quantity",
    )
    status: str = Field(default="pending", description="通知状态，例如：pending、arrived")
    message: Optional[str] = Field(default=None, description="混料通知说明")


class MixTraceResponse(BaseModel):
    """混料追溯统一响应。"""

    success: bool = Field(default=True, description="请求是否处理成功")
    message: str = Field(default="", description="响应说明")
    notifications: List[MixTraceNotification] = Field(default_factory=list, description="混料通知列表")
