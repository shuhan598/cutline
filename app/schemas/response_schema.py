"""Public response models returned by the cutline algorithm service."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.schemas.pending_cutline_schema import PendingCutlinePlan


class ResponseModel(BaseModel):
    """Strict base model for the public backend response contract."""

    model_config = ConfigDict(extra="forbid")


class StockoutWarningResponse(ResponseModel):
    warning_id: str = Field(..., min_length=1)
    warning_type: Literal["stockout"] = "stockout"
    warning_time: datetime
    buffer_code: str
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


class OverflowWarningResponse(ResponseModel):
    warning_id: str = Field(..., min_length=1)
    warning_type: Literal["overflow"] = "overflow"
    warning_time: datetime
    buffer_code: str
    workshop_code: str
    total_inventory: float = Field(..., ge=0)
    max_capacity: float = Field(..., gt=0)
    remaining_capacity: float
    buffer_growth_rate: float
    overflow_minutes: float = Field(..., ge=0)
    overflow_warning_lead_minutes: float = Field(..., gt=0)


class SelectedMachineResponse(ResponseModel):
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


class StockoutSelectedMachineResponse(SelectedMachineResponse):
    contribution_capacity: float = Field(..., ge=0)


class OverflowSelectedMachineResponse(SelectedMachineResponse):
    reduced_capacity: float = Field(..., ge=0)


class StockoutCutlinePlanResponse(ResponseModel):
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
    selected_machines: list[StockoutSelectedMachineResponse] = Field(
        default_factory=list
    )


class OverflowCutlinePlanResponse(ResponseModel):
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
    selected_machines: list[OverflowSelectedMachineResponse] = Field(
        default_factory=list
    )


CutlinePlanResponse = Annotated[
    StockoutCutlinePlanResponse | OverflowCutlinePlanResponse,
    Field(discriminator="warning_type"),
]


class AutomaticCutlineDecisionResponse(ResponseModel):
    warning_id: str = Field(..., min_length=1)
    plan: CutlinePlanResponse


class ManualInterventionResponse(ResponseModel):
    reason: str = Field(..., min_length=1)


class ManualCutlineDecisionResponse(ResponseModel):
    warning_id: str = Field(..., min_length=1)
    manual_intervention: ManualInterventionResponse


CutlineDecisionResponse = (
    AutomaticCutlineDecisionResponse | ManualCutlineDecisionResponse
)


class ReturnRecommendationResponse(ResponseModel):
    event_id: str = Field(..., min_length=1)
    machine_code: str
    source_order_code: str
    target_order_code: str
    return_recommended_time: datetime


class SilkScreenClearanceResponse(ResponseModel):
    workshop_code: str
    current_order_code: str
    machine_codes: list[str]
    calculation_time: datetime
    silk_screen_clear_minutes: float = Field(..., gt=0)
    remaining_production_hours: float | None = Field(default=None, ge=0)
    prepare_clearance: bool
    reason: Literal[
        "not_yet_time_to_prepare",
        "clearance_preparation_required",
        "current_order_completed",
        "current_order_capacity_unavailable",
    ]
    message: str


class ActiveCutlineEventResponse(ResponseModel):
    event_id: str = Field(..., min_length=1)
    machine_code: str
    source_order_code: str
    target_order_code: str
    workshop_code: str
    target_buffer_code: str
    upstream_process_code: str
    downstream_process_code: str
    target_wafer_size: str
    target_wafer_spec: str
    cutline_start_time: datetime
    negative_start_time: datetime | None


class ActiveCutlineEventUpdateResponse(ResponseModel):
    event_id: str = Field(..., min_length=1)
    negative_start_time: datetime | None


class MixingCompositionResponse(ResponseModel):
    order_code: str
    product_code: str
    sequence: int = Field(..., ge=1)
    estimated_pieces: int = Field(..., ge=0)


class MixingTraceRecordResponse(ResponseModel):
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
    compositions: list[MixingCompositionResponse]
    notification_status: Literal["scheduled", "due"]


class PipelineErrorResponse(ResponseModel):
    stage: str
    warning_type: str | None = None
    warning_key: str | None = None
    reason: str
    message: str


class MixingTraceErrorResponse(ResponseModel):
    stage: Literal["mixing_trace"] = "mixing_trace"
    machine_code: str
    reason: str
    message: str


class CutlineAlgorithmResponse(ResponseModel):
    """Customer results, backend tracking state, and isolated errors."""

    calculation_time: datetime
    stockout_warnings: list[StockoutWarningResponse] = Field(
        default_factory=list
    )
    overflow_warnings: list[OverflowWarningResponse] = Field(
        default_factory=list
    )
    cutline_decisions: list[CutlineDecisionResponse] = Field(
        default_factory=list
    )
    return_recommendations: list[ReturnRecommendationResponse] = Field(
        default_factory=list
    )
    silk_screen_results: list[SilkScreenClearanceResponse] = Field(
        default_factory=list
    )
    mixing_trace_records: list[MixingTraceRecordResponse] = Field(
        default_factory=list
    )
    new_active_cutline_events: list[ActiveCutlineEventResponse] = Field(
        default_factory=list
    )
    updated_active_cutline_events: list[
        ActiveCutlineEventUpdateResponse
    ] = Field(default_factory=list)
    closed_active_cutline_event_ids: list[str] = Field(default_factory=list)
    errors: list[PipelineErrorResponse | MixingTraceErrorResponse] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def validate_closed_events_match_recommendations(self):
        recommendation_ids = [
            item.event_id for item in self.return_recommendations
        ]
        closed_ids = self.closed_active_cutline_event_ids
        if (
            len(recommendation_ids) != len(set(recommendation_ids))
            or len(closed_ids) != len(set(closed_ids))
            or set(recommendation_ids) != set(closed_ids)
        ):
            raise ValueError(
                "return recommendations and closed active cutline event ids "
                "must match one-to-one"
            )
        return self


class ActiveCutlineEventPersistenceResponse(ResponseModel):
    event_id: str = Field(..., min_length=1)
    plan_id: str | None = Field(default=None, min_length=1)
    warning_id: str | None = Field(default=None, min_length=1)
    machine_code: str
    source_order_code: str
    target_order_code: str
    workshop_code: str
    source_buffer_code: str | None = None
    target_buffer_code: str
    upstream_process_code: str
    downstream_process_code: str
    source_wafer_size: str | None = None
    source_wafer_spec: str | None = None
    target_wafer_size: str
    target_wafer_spec: str
    cutline_start_time: datetime
    negative_start_time: datetime | None = None
    status: Literal[
        "active",
        "return_recommended",
        "returned",
        "cancelled",
    ] = "active"
    contribution_capacity: float | None = Field(default=None, ge=0)
    warning_type: Literal["stockout", "overflow"] | None = None
    process_code: str | None = None
    warning_buffer_code: str | None = None
    warning_upstream_process_code: str | None = None
    warning_downstream_process_code: str | None = None
    is_recommended_candidate: bool | None = None

    @field_validator("plan_id", "warning_id")
    @classmethod
    def validate_optional_identifier(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("optional identifier must not be blank")
        return value


class PersistenceStateResponse(ResponseModel):
    pending_cutline_plans: list[PendingCutlinePlan] = Field(
        default_factory=list
    )
    active_cutline_events: list[ActiveCutlineEventPersistenceResponse] = Field(
        default_factory=list
    )
    expired_pending_plan_ids: list[str] = Field(default_factory=list)
    completed_pending_plan_ids: list[str] = Field(default_factory=list)
    return_suggested_event_ids: list[str] = Field(default_factory=list)
    mixed_cutline_event_ids: list[str] = Field(default_factory=list)
    new_mixing_trace_records: list[MixingTraceRecordResponse] = Field(
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


class CutlineEvaluateResponse(CutlineAlgorithmResponse):
    persistence_state: PersistenceStateResponse = Field(
        default_factory=PersistenceStateResponse
    )
