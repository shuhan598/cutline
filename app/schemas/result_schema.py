# 算法管道四步各自的中间产物对象（内部模型，字段沿用原 dict 契约）

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class NetRateResult(BaseModel):
    """净速率计算结果。"""

    buffer_code: str
    product_code: str
    process_from: str
    process_to: Optional[str] = None
    upstream_output_per_hour: float
    downstream_input_per_hour: float
    net_rate_per_hour: float
    upstream_equipment_codes: List[str] = Field(default_factory=list)
    downstream_equipment_codes: List[str] = Field(default_factory=list)


class DepletionResult(BaseModel):
    """耗尽时间计算结果。"""

    buffer_code: str
    product_code: str
    process_from: str
    process_to: Optional[str] = None
    inventory_quantity: float
    net_rate_per_hour: float
    depletion_minutes: Optional[float] = None
    depletion_status: str


class StockoutWarningResult(BaseModel):
    """断料预警评估结果。"""

    buffer_code: str
    product_code: str
    process_from: str
    process_to: Optional[str] = None
    warning_type: str
    warning_triggered: bool
    reason: str
    inventory_quantity: float
    net_rate_per_hour: float
    depletion_minutes: Optional[float] = None
    depletion_status: str
    cutline_lead_minutes: float


class CandidateMachine(BaseModel):
    """候选机台明细。"""

    equipment_code: str
    equipment_name: Optional[str] = None
    process_code: str
    current_product_code: Optional[str] = None
    target_product_code: str
    wafer_size: Optional[str] = None
    shape_code: Optional[str] = None
    current_output_rate_per_hour: float
    contribution_capacity_per_hour: Optional[float] = None
    utilization_rate: Optional[float] = None
    idle_rate: Optional[float] = None
    reason: str


class CandidateResult(BaseModel):
    """单个预警的候选机台查找结果。"""

    buffer_code: str
    product_code: str
    process_from: str
    process_to: Optional[str] = None
    candidate_found: bool
    candidate_status: str
    reason: Optional[str] = None
    candidates: List[CandidateMachine] = Field(default_factory=list)


class OverflowWarningResult(BaseModel):
    """段级溢满预警评估结果。"""

    buffer_code: str
    product_code: str
    process_from: str
    process_to: Optional[str] = None
    warning_type: str = "overflow"
    warning_triggered: bool
    reason: str
    segment_inventory: float
    segment_capacity: float
    net_rate_per_hour: float
    overflow_minutes: Optional[float] = None
    cutline_lead_minutes: float


class PlanResult(BaseModel):
    """切线方案（断料/溢满共用）。"""

    buffer_code: str
    product_code: str
    process_from: str
    process_to: Optional[str] = None
    warning_type: str
    selected_machines: List[CandidateMachine] = Field(default_factory=list)
    total_contribution_capacity: float = 0.0
    remaining_capacity_gap: Optional[float] = None
    requires_silk_screen_clear: bool = False
    silk_screen_clear_minutes: Optional[float] = None


class ManualInterventionResult(BaseModel):
    """未补足/无候选的人工介入结果。"""

    buffer_code: str
    product_code: str
    process_from: str
    process_to: Optional[str] = None
    warning_type: str
    required_capacity: float
    reason: str
    candidates: List[CandidateMachine] = Field(default_factory=list)


class ReturnResult(BaseModel):
    """单个被跟踪切线事件的切回判断结果。"""

    equipment_code: str
    product_code: str
    original_product_code: Optional[str] = None
    buffer_code: Optional[str] = None
    process_from: Optional[str] = None
    process_to: Optional[str] = None
    net_rate_per_hour: Optional[float] = None
    inventory_quantity: Optional[float] = None
    negative_start_time: Optional[datetime] = None
    negative_duration_minutes: Optional[float] = None
    safety_inventory_quantity: Optional[float] = None
    triggered: bool = False
