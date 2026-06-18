# 算法管道四步各自的中间产物对象（内部模型，字段沿用原 dict 契约）

from __future__ import annotations

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
