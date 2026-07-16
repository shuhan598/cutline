# 算法服务返回给后端的结果数据格式

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field

from app.schemas.common_schema import AlgorithmActiveCutlineEvent
from app.schemas.result_schema import (
    AlgorithmCutlineDecisionResult,
    AlgorithmMixingTraceFailure,
    AlgorithmMixingTraceRecord,
    AlgorithmOverflowWarningResult,
    AlgorithmPipelineError,
    AlgorithmReturnResult,
    AlgorithmSilkScreenTransitionResult,
    AlgorithmStockoutWarningResult,
)


class CutlineAlgorithmResponse(BaseModel):
    """Unified response for the new cutline algorithm pipeline."""

    calculation_time: datetime
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
    silk_screen_results: list[AlgorithmSilkScreenTransitionResult] = Field(
        default_factory=list
    )
    mixing_trace_records: list[AlgorithmMixingTraceRecord] = Field(
        default_factory=list
    )
    mixing_trace_failures: list[AlgorithmMixingTraceFailure] = Field(
        default_factory=list
    )
    new_active_cutline_events: list[AlgorithmActiveCutlineEvent] = Field(
        default_factory=list
    )
    updated_active_cutline_events: list[AlgorithmActiveCutlineEvent] = Field(
        default_factory=list
    )
    errors: list[AlgorithmPipelineError] = Field(default_factory=list)
