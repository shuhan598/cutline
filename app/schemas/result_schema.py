# 算法管道四步各自的中间产物对象（内部模型，字段沿用原 dict 契约）

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.schemas.common_schema import AlgorithmActiveCutlineEvent
from app.core.buffer_aggregation.models import GroupKey
from app.schemas.pending_cutline_schema import (
    PendingCutlinePlan,
    PendingCutlinePlanStatus,
)

class AlgorithmIntervalNetRateResult(BaseModel):
    """新版算法按 Buffer、订单、规格和具体工序区间计算的净消耗速率。"""

    main_id: str
    buffer_code: str
    buffer_codes: list[str] = Field(..., min_length=1)
    order_code: str
    wafer_size: str
    wafer_spec: str
    workshop_code: str
    upstream_process_code: str
    downstream_process_code: str
    current_quantity: float
    upstream_output_rate: float
    downstream_input_rate: float
    net_consumption_rate: float
    inventory_change_rate: float | None = Field(default=None, exclude=True)
    group_key: GroupKey | None = Field(default=None, exclude=True)


class ConfirmedCutlineTransition(BaseModel):
    """A physical AGV binding change confirmed from a pending plan."""

    plan_id: str
    warning_id: str
    warning_type: Literal["stockout", "overflow"]
    machine_code: str
    source_order_code: str
    target_order_code: str
    workshop_code: str
    process_code: str
    source_buffer_code: str | None = None
    target_buffer_code: str
    target_upstream_process_code: str
    target_downstream_process_code: str
    source_wafer_size: str
    source_wafer_spec: str
    target_wafer_size: str
    target_wafer_spec: str
    cutline_start_time: datetime
    is_recommended_candidate: bool


class PendingCutlinePlanEvaluation(BaseModel):
    """Current confirmation progress for one persisted pending plan."""

    plan_id: str
    warning_id: str
    status: PendingCutlinePlanStatus
    before_machine_count: int = Field(..., ge=0)
    before_machine_codes: list[str] = Field(default_factory=list)
    current_machine_count: int = Field(..., ge=0)
    current_machine_codes: list[str] = Field(default_factory=list)
    expected_machine_count: int = Field(..., ge=0)
    expected_delta_direction: Literal["increase", "decrease"]
    confirmed_machine_codes: list[str] = Field(default_factory=list)
    new_confirmed_machine_codes: list[str] = Field(default_factory=list)


class PendingCutlineDetectionBatchResult(BaseModel):
    """Confirmed transitions and per-plan state from one snapshot."""

    transitions: list[ConfirmedCutlineTransition] = Field(
        default_factory=list
    )
    plan_evaluations: list[PendingCutlinePlanEvaluation] = Field(
        default_factory=list
    )


class AlgorithmReturnResult(BaseModel):
    """新版活动切线事件在当前快照时刻的切回判断结果。"""

    event_id: str
    machine_code: str
    source_order_code: str
    target_order_code: str
    workshop_code: str
    source_buffer_code: str | None
    target_buffer_code: str
    upstream_process_code: str
    downstream_process_code: str
    target_wafer_size: str
    target_wafer_spec: str
    current_time: datetime
    cutline_start_time: datetime
    previous_negative_start_time: datetime | None
    updated_negative_start_time: datetime | None
    cutline_duration_minutes: float
    negative_duration_minutes: float
    net_consumption_rate: float
    current_quantity: float
    stability_window_minutes: float
    stockout_warning_lead_minutes: float
    safe_inventory_quantity: float
    condition_net_rate_met: bool
    condition_stability_met: bool
    condition_inventory_met: bool
    return_recommended: bool
    previous_status: Literal[
        "active",
        "return_recommended",
        "returned",
        "cancelled",
    ]
    updated_status: Literal["active", "return_recommended"]
    reason: Literal[
        "net_rate_not_negative",
        "stability_window_not_met",
        "inventory_not_above_safe_level",
        "all_return_conditions_met",
    ]


class AlgorithmSilkScreenTransitionResult(BaseModel):
    """新版丝网当前订单的完工与清台准备预测结果。"""

    workshop_code: str
    process_code: str
    process_name: str
    current_order_code: str
    current_product_code: str
    machine_codes: list[str]
    total_quantity: float = Field(..., ge=0)
    produced_quantity: float = Field(..., ge=0)
    remaining_quantity: float = Field(..., ge=0)
    current_order_output_rate: float = Field(..., ge=0)
    remaining_production_hours: float | None = Field(default=None, ge=0)
    current_time: datetime
    estimated_finish_time: datetime | None = None
    silk_screen_clear_minutes: float = Field(..., gt=0)
    clearance_prepare_time: datetime | None = None
    prepare_clearance: bool
    reason: Literal[
        "not_yet_time_to_prepare",
        "clearance_preparation_required",
        "current_order_completed",
        "current_order_capacity_unavailable",
    ]
    message: str
    next_order_code: str | None = None


class AlgorithmDepletionTimeResult(BaseModel):
    """新版算法按订单区间计算的断料时间。"""

    main_id: str
    buffer_code: str
    buffer_codes: list[str] = Field(..., min_length=1)
    order_code: str
    wafer_size: str
    wafer_spec: str
    workshop_code: str
    upstream_process_code: str
    downstream_process_code: str
    current_quantity: float = Field(..., ge=0)
    upstream_output_rate: float = Field(..., ge=0)
    downstream_input_rate: float = Field(..., ge=0)
    net_consumption_rate: float
    depletion_minutes: float | None = Field(..., ge=0)
    group_key: GroupKey | None = Field(default=None, exclude=True)


class AlgorithmOrderGrowthDetail(BaseModel):
    """单个订单对物理 Buffer 库存增长速率的贡献明细。"""

    order_code: str
    wafer_size: str
    wafer_spec: str
    current_quantity: float = Field(..., ge=0)
    upstream_output_rate: float = Field(..., ge=0)
    downstream_input_rate: float = Field(..., ge=0)
    net_consumption_rate: float
    growth_rate: float


class AlgorithmBufferOverflowTimeResult(BaseModel):
    """新版算法按物理 Buffer 汇总计算的溢满时间。"""

    main_id: str
    buffer_code: str
    buffer_codes: list[str] = Field(..., min_length=1)
    workshop_code: str
    upstream_process_code: str
    downstream_process_code: str
    max_capacity: float = Field(..., gt=0)
    total_inventory: float = Field(..., ge=0)
    remaining_capacity: float
    buffer_growth_rate: float
    overflow_minutes: float | None = Field(..., ge=0)
    order_growth_details: list[AlgorithmOrderGrowthDetail] = Field(
        default_factory=list
    )
    group_key: GroupKey | None = Field(default=None, exclude=True)


class AlgorithmStockoutWarningResult(BaseModel):
    """新版算法按订单工序区间生成的断料预警。"""

    warning_type: Literal["stockout"] = "stockout"
    warning_time: datetime
    main_id: str
    buffer_code: str
    buffer_codes: list[str] = Field(..., min_length=1)
    order_code: str
    wafer_size: str
    wafer_spec: str
    workshop_code: str
    upstream_process_code: str
    downstream_process_code: str
    current_quantity: float = Field(..., ge=0)
    upstream_output_rate: float = Field(..., ge=0)
    downstream_input_rate: float = Field(..., ge=0)
    net_consumption_rate: float
    depletion_minutes: float = Field(..., ge=0)
    stockout_warning_lead_minutes: float = Field(..., gt=0)
    group_key: GroupKey | None = Field(default=None, exclude=True)


class AlgorithmOverflowWarningResult(BaseModel):
    """新版算法按物理 Buffer 生成的溢满预警。"""

    warning_type: Literal["overflow"] = "overflow"
    warning_time: datetime
    main_id: str
    buffer_code: str
    buffer_codes: list[str] = Field(..., min_length=1)
    workshop_code: str
    upstream_process_code: str
    downstream_process_code: str
    max_capacity: float = Field(..., gt=0)
    total_inventory: float = Field(..., ge=0)
    remaining_capacity: float
    buffer_growth_rate: float
    overflow_minutes: float = Field(..., ge=0)
    overflow_warning_lead_minutes: float = Field(..., gt=0)
    order_growth_details: list[AlgorithmOrderGrowthDetail] = Field(
        default_factory=list
    )
    group_key: GroupKey | None = Field(default=None, exclude=True)


class AlgorithmStockoutCandidateMachine(BaseModel):
    """新版断料预警的单台候选机台。"""

    machine_code: str
    machine_name: str
    status: str
    workshop_code: str
    process_code: str
    process_name: str
    current_order_code: str
    current_order_name: str
    current_product_code: str
    current_wafer_size: str
    current_wafer_spec: str
    current_source_grade: str
    target_order_code: str
    target_product_code: str
    target_wafer_size: str
    target_wafer_spec: str
    target_source_grade: str
    input_quantity_30m: float = Field(..., ge=0)
    output_quantity_30m: float = Field(..., ge=0)
    current_output_rate_per_hour: float = Field(..., ge=0)
    contribution_capacity: float = Field(..., ge=0)
    utilization_rate: float
    idle_rate: float
    receiver_group_key: GroupKey | None = Field(default=None, exclude=True)
    donor_group_key: GroupKey | None = Field(default=None, exclude=True)
    donor_main_id: str | None = Field(default=None, exclude=True)


class AlgorithmStockoutCandidateResult(BaseModel):
    """新版断料预警的候选机台筛选结果。"""

    warning_type: Literal["stockout"] = "stockout"
    workshop_code: str
    buffer_code: str
    warning_order_code: str
    target_product_code: str
    target_wafer_size: str
    target_wafer_spec: str
    target_source_grade: str
    upstream_process_code: str
    downstream_process_code: str
    capacity_gap: float
    candidates: list[AlgorithmStockoutCandidateMachine] = Field(
        default_factory=list
    )
    receiver_group_key: GroupKey | None = Field(default=None, exclude=True)


class AlgorithmOverflowTargetOption(BaseModel):
    """新版溢满来源机台可切入的单个目标订单。"""

    target_order_code: str
    target_product_code: str
    target_wafer_size: str
    target_wafer_spec: str
    target_source_grade: str
    target_buffer_code: str | None = None
    target_workshop_code: str | None = None
    target_upstream_process_code: str | None = None
    target_downstream_process_code: str | None = None
    capacity_gap: float
    estimated_contribution_capacity: float = Field(..., ge=0)
    target_group_key: GroupKey | None = Field(default=None, exclude=True)


class AlgorithmOverflowCandidateMachine(BaseModel):
    """新版溢满预警的单台来源候选机台。"""

    machine_code: str
    machine_name: str
    status: str
    workshop_code: str
    process_code: str
    process_name: str
    current_order_code: str
    current_order_name: str
    current_product_code: str
    current_wafer_size: str
    current_wafer_spec: str
    current_source_grade: str
    input_quantity_30m: float = Field(..., ge=0)
    output_quantity_30m: float = Field(..., ge=0)
    current_output_rate_per_hour: float = Field(..., ge=0)
    reduced_capacity: float = Field(..., ge=0)
    utilization_rate: float
    idle_rate: float
    target_options: list[AlgorithmOverflowTargetOption] = Field(
        default_factory=list
    )
    source_group_key: GroupKey | None = Field(default=None, exclude=True)


class AlgorithmOverflowCandidateResult(BaseModel):
    """新版物理 Buffer 溢满预警的候选机台筛选结果。"""

    warning_type: Literal["overflow"] = "overflow"
    workshop_code: str
    buffer_code: str
    upstream_process_code: str
    downstream_process_code: str
    source_order_code: str
    source_product_code: str
    source_wafer_size: str
    source_wafer_spec: str
    source_source_grade: str
    source_growth_rate: float
    source_net_consumption_rate: float
    candidates: list[AlgorithmOverflowCandidateMachine] = Field(
        default_factory=list
    )
    source_group_key: GroupKey | None = Field(default=None, exclude=True)


class AlgorithmRejectedMachineEvaluation(BaseModel):
    """新版逐台模拟中未通过影响校验的机台诊断结果。"""

    machine_code: str
    reason: str
    source_order_code: str
    target_order_code: str | None = None
    source_buffer_code: str | None = None
    target_buffer_code: str | None = None
    source_net_rate_before: float | None = None
    source_net_rate_after: float | None = None
    source_depletion_minutes_after: float | None = Field(default=None, ge=0)
    target_net_rate_before: float | None = None
    target_net_rate_after: float | None = None
    target_overflow_minutes_after: float | None = Field(default=None, ge=0)
    message: str | None = None


class AlgorithmSelectedMachineEvaluation(BaseModel):
    """新版逐台模拟中通过全部影响校验的单台机台结果。"""

    machine_code: str
    source_order_code: str
    target_order_code: str
    source_buffer_code: str
    target_buffer_code: str
    process_code: str
    workshop_code: str
    wafer_size: str
    source_wafer_spec: str
    target_wafer_spec: str
    contribution_capacity: float | None = Field(default=None, ge=0)
    reduced_capacity: float | None = Field(default=None, ge=0)
    utilization_rate: float
    idle_rate: float
    source_net_rate_before: float
    source_net_rate_after: float
    source_depletion_minutes_after: float | None = Field(default=None, ge=0)
    target_net_rate_before: float
    target_net_rate_after: float
    target_overflow_minutes_after: float | None = Field(default=None, ge=0)
    receiver_group_key: GroupKey | None = Field(default=None, exclude=True)
    donor_group_key: GroupKey | None = Field(default=None, exclude=True)
    donor_main_id: str | None = Field(default=None, exclude=True)
    source_group_key: GroupKey | None = Field(default=None, exclude=True)
    target_group_key: GroupKey | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def validate_capacity_kind(self):
        has_contribution = self.contribution_capacity is not None
        has_reduction = self.reduced_capacity is not None
        if has_contribution == has_reduction:
            raise ValueError(
                "selected machine must provide exactly one capacity kind"
            )
        return self


class AlgorithmStockoutSelectionResult(BaseModel):
    """新版断料候选逐台影响模拟和累计选机结果。"""

    warning_type: Literal["stockout"] = "stockout"
    workshop_code: str
    buffer_code: str
    order_code: str
    wafer_size: str
    wafer_spec: str
    upstream_process_code: str
    downstream_process_code: str
    initial_capacity_gap: float
    total_contribution_capacity: float = Field(..., ge=0)
    remaining_capacity_gap: float = Field(..., ge=0)
    selected_machines: list[AlgorithmSelectedMachineEvaluation] = Field(
        default_factory=list
    )
    rejected_machines: list[AlgorithmRejectedMachineEvaluation] = Field(
        default_factory=list
    )
    risk_resolved: bool
    failure_reason: str | None = None

    @model_validator(mode="after")
    def validate_selection_state(self):
        if any(
            item.contribution_capacity is None
            for item in self.selected_machines
        ):
            raise ValueError(
                "stockout selected machines require contribution capacity"
            )
        if not self.risk_resolved and self.remaining_capacity_gap <= 0:
            raise ValueError(
                "unresolved stockout selection requires a remaining capacity gap"
            )
        self._validate_failure_reason()
        return self

    def _validate_failure_reason(self) -> None:
        if self.risk_resolved and self.failure_reason is not None:
            raise ValueError("resolved selection cannot have a failure reason")
        if not self.risk_resolved and not self.failure_reason:
            raise ValueError("unresolved selection requires a failure reason")


class AlgorithmOverflowSelectionResult(BaseModel):
    """新版溢满候选逐台影响模拟和累计选机结果。"""

    warning_type: Literal["overflow"] = "overflow"
    workshop_code: str
    buffer_code: str
    upstream_process_code: str
    downstream_process_code: str
    source_order_code: str
    source_wafer_size: str
    source_wafer_spec: str
    initial_growth_rate: float
    total_reduced_capacity: float = Field(..., ge=0)
    remaining_growth_rate: float
    updated_overflow_minutes: float | None = Field(default=None, ge=0)
    selected_machines: list[AlgorithmSelectedMachineEvaluation] = Field(
        default_factory=list
    )
    rejected_machines: list[AlgorithmRejectedMachineEvaluation] = Field(
        default_factory=list
    )
    risk_resolved: bool
    failure_reason: str | None = None

    @model_validator(mode="after")
    def validate_selection_state(self):
        if any(
            item.reduced_capacity is None
            for item in self.selected_machines
        ):
            raise ValueError(
                "overflow selected machines require reduced capacity"
            )
        if self.risk_resolved and self.failure_reason is not None:
            raise ValueError("resolved selection cannot have a failure reason")
        if not self.risk_resolved and not self.failure_reason:
            raise ValueError("unresolved selection requires a failure reason")
        return self


class AlgorithmStockoutCutlinePlan(BaseModel):
    """风险完全解除后生成的新版断料正式切线方案。"""

    plan_id: str
    warning_type: Literal["stockout"] = "stockout"
    calculation_time: datetime
    workshop_code: str
    buffer_code: str
    order_code: str
    wafer_size: str
    wafer_spec: str
    upstream_process_code: str
    downstream_process_code: str
    initial_capacity_gap: float
    total_contribution_capacity: float = Field(..., ge=0)
    remaining_capacity_gap: float = Field(..., ge=0)
    selected_machines: list[AlgorithmSelectedMachineEvaluation] = Field(
        default_factory=list
    )
    risk_resolved: Literal[True] = True
    manual_intervention_required: Literal[False] = False


class AlgorithmOverflowCutlinePlan(BaseModel):
    """风险完全解除后生成的新版溢满正式切线方案。"""

    plan_id: str
    warning_type: Literal["overflow"] = "overflow"
    calculation_time: datetime
    workshop_code: str
    buffer_code: str
    source_order_code: str
    source_wafer_size: str
    source_wafer_spec: str
    upstream_process_code: str
    downstream_process_code: str
    initial_growth_rate: float
    total_reduced_capacity: float = Field(..., ge=0)
    remaining_growth_rate: float
    updated_overflow_minutes: float | None = Field(default=None, ge=0)
    selected_machines: list[AlgorithmSelectedMachineEvaluation] = Field(
        default_factory=list
    )
    risk_resolved: Literal[True] = True
    manual_intervention_required: Literal[False] = False


class AlgorithmManualInterventionResult(BaseModel):
    """新版风险未完全解除时输出的人工介入诊断结果。"""

    warning_type: Literal["stockout", "overflow"]
    warning_time: datetime
    workshop_code: str
    buffer_code: str
    order_code: str | None = None
    source_order_code: str | None = None
    wafer_size: str
    wafer_spec: str
    upstream_process_code: str
    downstream_process_code: str
    manual_intervention_required: Literal[True] = True
    risk_resolved: Literal[False] = False
    reason: str
    initial_risk_value: float
    remaining_risk_value: float
    evaluated_candidate_count: int = Field(..., ge=0)
    passed_candidate_count: int = Field(..., ge=0)
    rejected_candidate_count: int = Field(..., ge=0)
    passed_machines: list[AlgorithmSelectedMachineEvaluation] = Field(
        default_factory=list
    )
    rejected_machines: list[AlgorithmRejectedMachineEvaluation] = Field(
        default_factory=list
    )


class AlgorithmCutlineDecisionResult(BaseModel):
    """新版正式方案与人工介入二选一的统一决策结果。"""

    plan: AlgorithmStockoutCutlinePlan | AlgorithmOverflowCutlinePlan | None
    manual_intervention: AlgorithmManualInterventionResult | None

    @model_validator(mode="after")
    def validate_exactly_one_result(self):
        if (self.plan is None) == (self.manual_intervention is None):
            raise ValueError(
                "exactly one of plan or manual_intervention must be present"
            )
        return self


AlgorithmCutlinePlan = AlgorithmStockoutCutlinePlan | AlgorithmOverflowCutlinePlan


class AlgorithmMixingComposition(BaseModel):
    """单个切线前后产品在预计混料中的片数组成。"""

    order_code: str
    product_code: str
    sequence: int = Field(..., ge=1)
    estimated_pieces: int = Field(..., ge=0)


class AlgorithmMixingTraceRecord(BaseModel):
    """正式切线方案中单台机台的精简混料追溯记录。"""

    mix_trace_id: str
    plan_id: str
    cutline_event_id: str
    machine_code: str
    workshop_code: str
    process_code: str
    process_name: str
    source_order_code: str
    target_order_code: str
    source_product_code: str
    target_product_code: str
    mix_start_time: datetime
    mixed_basket_start_index: int = Field(..., ge=1)
    mixed_basket_end_index: int = Field(..., ge=1)
    mixed_basket_count: int = Field(..., ge=1)
    estimated_total_mixed_pieces: int = Field(..., ge=1)
    compositions: list[AlgorithmMixingComposition]
    notification_status: Literal["scheduled", "due"]


class AlgorithmMixingTraceFailure(BaseModel):
    """正式方案中单台机台无法生成混料追溯记录的原因。"""

    plan_id: str
    cutline_event_id: str
    machine_code: str
    source_order_code: str
    target_order_code: str
    reason: str
    message: str


class AlgorithmMixingTraceBatchResult(BaseModel):
    """一份正式切线方案中所有机台的混料追溯计算结果。"""

    records: list[AlgorithmMixingTraceRecord] = Field(default_factory=list)
    failures: list[AlgorithmMixingTraceFailure] = Field(default_factory=list)


class AlgorithmPipelineError(BaseModel):
    """新版算法单个阶段或单条预警的可隔离执行错误。"""

    stage: str
    warning_type: str | None = None
    warning_key: str | None = None
    reason: str
    message: str


class AlgorithmPersistenceState(BaseModel):
    """The complete backend state to persist after an evaluation cycle."""

    model_config = ConfigDict(extra="forbid")

    pending_cutline_plans: list[PendingCutlinePlan] = Field(
        default_factory=list
    )
    active_cutline_events: list[AlgorithmActiveCutlineEvent] = Field(
        default_factory=list
    )
    expired_pending_plan_ids: list[str] = Field(default_factory=list)
    completed_pending_plan_ids: list[str] = Field(default_factory=list)
    return_suggested_event_ids: list[str] = Field(default_factory=list)
    mixed_cutline_event_ids: list[str] = Field(default_factory=list)
    new_mixing_trace_records: list[AlgorithmMixingTraceRecord] = Field(
        default_factory=list
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


class AlgorithmEvaluateResult(BaseModel):
    """承接所有新版算法模块产物的统一总结果。"""

    calculation_time: datetime
    net_rate_results: list[AlgorithmIntervalNetRateResult] = Field(
        default_factory=list
    )
    depletion_results: list[AlgorithmDepletionTimeResult] = Field(
        default_factory=list
    )
    overflow_time_results: list[AlgorithmBufferOverflowTimeResult] = Field(
        default_factory=list
    )
    stockout_warnings: list[AlgorithmStockoutWarningResult] = Field(
        default_factory=list
    )
    overflow_warnings: list[AlgorithmOverflowWarningResult] = Field(
        default_factory=list
    )
    cutline_decisions: list[AlgorithmCutlineDecisionResult] = Field(
        default_factory=list
    )
    return_results: list[AlgorithmReturnResult] = Field(default_factory=list)
    new_active_cutline_events: list[AlgorithmActiveCutlineEvent] = Field(
        default_factory=list
    )
    updated_active_cutline_events: list[AlgorithmActiveCutlineEvent] = Field(
        default_factory=list
    )
    silk_screen_results: list[AlgorithmSilkScreenTransitionResult] = Field(
        default_factory=list
    )
    mixing_trace_records: list[AlgorithmMixingTraceRecord] = Field(
        default_factory=list
    )
    mixing_trace_failures: list[AlgorithmMixingTraceFailure] = Field(
        default_factory=list
    )
    errors: list[AlgorithmPipelineError] = Field(default_factory=list)
    persistence_state: AlgorithmPersistenceState = Field(
        default_factory=AlgorithmPersistenceState
    )
