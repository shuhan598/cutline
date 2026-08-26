"""把完整内部算法结果映射为精简且稳定的正式响应契约。"""

from app.schemas.common_schema import AlgorithmActiveCutlineEvent
from app.schemas.response_schema import (
    ActiveCutlineEventPersistenceResponse,
    ActiveCutlineEventResponse,
    ActiveCutlineEventUpdateResponse,
    AutomaticCutlineDecisionResponse,
    CutlineAlgorithmResponse,
    CutlineEvaluateResponse,
    ManualCutlineDecisionResponse,
    ManualInterventionResponse,
    MixingCompositionResponse,
    MixingTraceErrorResponse,
    MixingTraceRecordResponse,
    OverflowCutlinePlanResponse,
    OverflowSelectedMachineResponse,
    OverflowWarningResponse,
    PipelineErrorResponse,
    PersistenceStateResponse,
    ReturnRecommendationResponse,
    SilkScreenClearanceResponse,
    StockoutCutlinePlanResponse,
    StockoutSelectedMachineResponse,
    StockoutWarningResponse,
)
from app.schemas.result_schema import (
    AlgorithmCutlineDecisionResult,
    AlgorithmEvaluateResult,
    AlgorithmMixingTraceRecord,
    AlgorithmOverflowCutlinePlan,
    AlgorithmOverflowWarningResult,
    AlgorithmPipelineError,
    AlgorithmReturnResult,
    AlgorithmSilkScreenTransitionResult,
    AlgorithmStockoutCutlinePlan,
    AlgorithmStockoutWarningResult,
)
from app.utils.input_error_codes import (
    error_code_message,
    mixing_trace_error_code,
    pipeline_error_code,
)


_PUBLIC_MANUAL_REASON_BY_INTERNAL = {
    "insufficient_contribution_capacity": "insufficient_capacity",
    "insufficient_reduced_capacity": "insufficient_capacity",
}


class AlgorithmResponseMapper:
    """类 【AlgorithmResponseMapper】 封装该领域的数据或服务能力，对外提供稳定的业务契约。"""
    def to_response(
        self,
        result: AlgorithmEvaluateResult,
    ) -> CutlineAlgorithmResponse:
        """执行【to_response】业务操作；参数、返回值和异常语义以类型标注及调用方契约为准。"""
        recommendations, updates, closed_ids = self._map_return_results(
            result.return_results,
            new_event_ids={
                event.event_id
                for event in result.new_active_cutline_events
            },
        )
        errors: list[
            PipelineErrorResponse | MixingTraceErrorResponse
        ] = [
            self._map_pipeline_error(item)
            for item in result.errors
        ]
        errors.extend(
            self._map_mixing_trace_failure(item)
            for item in result.mixing_trace_failures
        )
        return CutlineAlgorithmResponse(
            calculation_time=result.calculation_time,
            stockout_warnings=[
                self._map_stockout_warning(item)
                for item in result.stockout_warnings
            ],
            overflow_warnings=[
                self._map_overflow_warning(item)
                for item in result.overflow_warnings
            ],
            cutline_decisions=[
                self._map_cutline_decision(item)
                for item in result.cutline_decisions
            ],
            return_recommendations=recommendations,
            silk_screen_results=[
                self._map_silk_screen_result(
                    item,
                    calculation_time=result.calculation_time,
                )
                for item in result.silk_screen_results
            ],
            mixing_trace_records=[
                self._map_mixing_trace_record(item)
                for item in result.mixing_trace_records
            ],
            new_active_cutline_events=[
                self._map_active_event(item)
                for item in result.new_active_cutline_events
            ],
            updated_active_cutline_events=updates,
            closed_active_cutline_event_ids=closed_ids,
            errors=errors,
        )

    def to_evaluate_response(
        self,
        result: AlgorithmEvaluateResult,
    ) -> CutlineEvaluateResponse:
        """执行【to_evaluate_response】业务操作；参数、返回值和异常语义以类型标注及调用方契约为准。"""
        business_response = self.to_response(result)
        state = result.persistence_state
        return CutlineEvaluateResponse(
            **business_response.model_dump(),
            persistence_state=PersistenceStateResponse(
                pending_cutline_plans=[
                    plan.model_copy(deep=True)
                    for plan in state.pending_cutline_plans
                ],
                active_cutline_events=[
                    ActiveCutlineEventPersistenceResponse(
                        **event.model_dump()
                    )
                    for event in state.active_cutline_events
                ],
                expired_pending_plan_ids=list(
                    state.expired_pending_plan_ids
                ),
                completed_pending_plan_ids=list(
                    state.completed_pending_plan_ids
                ),
                return_suggested_event_ids=list(
                    state.return_suggested_event_ids
                ),
                mixed_cutline_event_ids=list(state.mixed_cutline_event_ids),
                new_mixing_trace_records=[
                    self._map_mixing_trace_record(item)
                    for item in state.new_mixing_trace_records
                ],
            ),
        )

    def _map_stockout_warning(
        self,
        item: AlgorithmStockoutWarningResult,
    ) -> StockoutWarningResponse:
        """在後端输入与算法内部模型之间执行【_map_stockout_warning】转换，并保留必要的校验信息。"""
        return StockoutWarningResponse(
            warning_id=self._stockout_warning_id(
                item.warning_time,
                item.buffer_code,
                item.order_code,
            ),
            warning_type=item.warning_type,
            warning_time=item.warning_time,
            buffer_code=item.buffer_code,
            order_code=item.order_code,
            wafer_size=item.wafer_size,
            wafer_spec=item.wafer_spec,
            workshop_code=item.workshop_code,
            upstream_process_code=item.upstream_process_code,
            downstream_process_code=item.downstream_process_code,
            current_quantity=item.current_quantity,
            upstream_output_rate=item.upstream_output_rate,
            downstream_input_rate=item.downstream_input_rate,
            net_consumption_rate=item.net_consumption_rate,
            depletion_minutes=item.depletion_minutes,
            stockout_warning_lead_minutes=(
                item.stockout_warning_lead_minutes
            ),
        )

    def _map_overflow_warning(
        self,
        item: AlgorithmOverflowWarningResult,
    ) -> OverflowWarningResponse:
        """在後端输入与算法内部模型之间执行【_map_overflow_warning】转换，并保留必要的校验信息。"""
        return OverflowWarningResponse(
            warning_id=self._overflow_warning_id(
                item.warning_time,
                item.buffer_code,
            ),
            warning_type=item.warning_type,
            warning_time=item.warning_time,
            buffer_code=item.buffer_code,
            workshop_code=item.workshop_code,
            total_inventory=item.total_inventory,
            max_capacity=item.max_capacity,
            remaining_capacity=item.remaining_capacity,
            buffer_growth_rate=item.buffer_growth_rate,
            overflow_minutes=item.overflow_minutes,
            overflow_warning_lead_minutes=(
                item.overflow_warning_lead_minutes
            ),
        )

    def _map_cutline_decision(self, item: AlgorithmCutlineDecisionResult):
        """在後端输入与算法内部模型之间执行【_map_cutline_decision】转换，并保留必要的校验信息。"""
        if item.plan is not None:
            return AutomaticCutlineDecisionResponse(
                warning_id=self._plan_warning_id(item.plan),
                plan=self._map_plan(item.plan),
            )
        manual = item.manual_intervention
        if manual is None:
            raise ValueError("cutline decision has no result branch")
        if manual.warning_type == "stockout":
            if manual.order_code is None:
                raise ValueError("stockout manual decision has no order code")
            warning_id = self._stockout_warning_id(
                manual.warning_time,
                manual.buffer_code,
                manual.order_code,
            )
        else:
            warning_id = self._overflow_warning_id(
                manual.warning_time,
                manual.buffer_code,
            )
        return ManualCutlineDecisionResponse(
            warning_id=warning_id,
            manual_intervention=ManualInterventionResponse(
                reason=_PUBLIC_MANUAL_REASON_BY_INTERNAL.get(
                    manual.reason,
                    manual.reason,
                )
            ),
        )

    def _map_plan(
        self,
        plan: AlgorithmStockoutCutlinePlan | AlgorithmOverflowCutlinePlan,
    ) -> StockoutCutlinePlanResponse | OverflowCutlinePlanResponse:
        """在後端输入与算法内部模型之间执行【_map_plan】转换，并保留必要的校验信息。"""
        if isinstance(plan, AlgorithmStockoutCutlinePlan):
            return StockoutCutlinePlanResponse(
                plan_id=plan.plan_id,
                warning_type=plan.warning_type,
                calculation_time=plan.calculation_time,
                workshop_code=plan.workshop_code,
                buffer_code=plan.buffer_code,
                order_code=plan.order_code,
                wafer_size=plan.wafer_size,
                wafer_spec=plan.wafer_spec,
                upstream_process_code=plan.upstream_process_code,
                downstream_process_code=plan.downstream_process_code,
                initial_capacity_gap=plan.initial_capacity_gap,
                total_contribution_capacity=(
                    plan.total_contribution_capacity
                ),
                remaining_capacity_gap=plan.remaining_capacity_gap,
                selected_machines=[
                    StockoutSelectedMachineResponse(
                        machine_code=machine.machine_code,
                        source_order_code=machine.source_order_code,
                        target_order_code=machine.target_order_code,
                        source_buffer_code=machine.source_buffer_code,
                        target_buffer_code=machine.target_buffer_code,
                        process_code=machine.process_code,
                        workshop_code=machine.workshop_code,
                        wafer_size=machine.wafer_size,
                        source_wafer_spec=machine.source_wafer_spec,
                        target_wafer_spec=machine.target_wafer_spec,
                        contribution_capacity=self._required_capacity(
                            machine.contribution_capacity,
                            "stockout contribution",
                        ),
                    )
                    for machine in plan.selected_machines
                ],
            )
        return OverflowCutlinePlanResponse(
            plan_id=plan.plan_id,
            warning_type=plan.warning_type,
            calculation_time=plan.calculation_time,
            workshop_code=plan.workshop_code,
            buffer_code=plan.buffer_code,
            source_order_code=plan.source_order_code,
            source_wafer_size=plan.source_wafer_size,
            source_wafer_spec=plan.source_wafer_spec,
            upstream_process_code=plan.upstream_process_code,
            downstream_process_code=plan.downstream_process_code,
            initial_growth_rate=plan.initial_growth_rate,
            total_reduced_capacity=plan.total_reduced_capacity,
            remaining_growth_rate=plan.remaining_growth_rate,
            updated_overflow_minutes=plan.updated_overflow_minutes,
            selected_machines=[
                OverflowSelectedMachineResponse(
                    machine_code=machine.machine_code,
                    source_order_code=machine.source_order_code,
                    target_order_code=machine.target_order_code,
                    source_buffer_code=machine.source_buffer_code,
                    target_buffer_code=machine.target_buffer_code,
                    process_code=machine.process_code,
                    workshop_code=machine.workshop_code,
                    wafer_size=machine.wafer_size,
                    source_wafer_spec=machine.source_wafer_spec,
                    target_wafer_spec=machine.target_wafer_spec,
                    reduced_capacity=self._required_capacity(
                        machine.reduced_capacity,
                        "overflow reduction",
                    ),
                )
                for machine in plan.selected_machines
            ],
        )

    def _map_return_results(
        self,
        items: list[AlgorithmReturnResult],
        *,
        new_event_ids: set[str],
    ) -> tuple[
        list[ReturnRecommendationResponse],
        list[ActiveCutlineEventUpdateResponse],
        list[str],
    ]:
        """在後端输入与算法内部模型之间执行【_map_return_results】转换，并保留必要的校验信息。"""
        recommendations: list[ReturnRecommendationResponse] = []
        updates: list[ActiveCutlineEventUpdateResponse] = []
        closed_ids: list[str] = []
        for item in items:
            if item.return_recommended:
                recommendations.append(
                    ReturnRecommendationResponse(
                        event_id=item.event_id,
                        machine_code=item.machine_code,
                        source_order_code=item.source_order_code,
                        target_order_code=item.target_order_code,
                        return_recommended_time=item.current_time,
                    )
                )
                closed_ids.append(item.event_id)
                continue
            if (
                item.event_id not in new_event_ids
                and item.previous_negative_start_time
                != item.updated_negative_start_time
            ):
                updates.append(
                    ActiveCutlineEventUpdateResponse(
                        event_id=item.event_id,
                        negative_start_time=(
                            item.updated_negative_start_time
                        ),
                    )
                )
        return recommendations, updates, closed_ids

    def _map_active_event(
        self,
        item: AlgorithmActiveCutlineEvent,
    ) -> ActiveCutlineEventResponse:
        """在後端输入与算法内部模型之间执行【_map_active_event】转换，并保留必要的校验信息。"""
        return ActiveCutlineEventResponse(
            event_id=item.event_id,
            machine_code=item.machine_code,
            source_order_code=item.source_order_code,
            target_order_code=item.target_order_code,
            workshop_code=item.workshop_code,
            target_buffer_code=item.target_buffer_code,
            upstream_process_code=item.upstream_process_code,
            downstream_process_code=item.downstream_process_code,
            target_wafer_size=item.target_wafer_size,
            target_wafer_spec=item.target_wafer_spec,
            cutline_start_time=item.cutline_start_time,
            negative_start_time=item.negative_start_time,
        )

    def _map_silk_screen_result(
        self,
        item: AlgorithmSilkScreenTransitionResult,
        *,
        calculation_time,
    ) -> SilkScreenClearanceResponse:
        """在後端输入与算法内部模型之间执行【_map_silk_screen_result】转换，并保留必要的校验信息。"""
        return SilkScreenClearanceResponse(
            workshop_code=item.workshop_code,
            current_order_code=item.current_order_code,
            machine_codes=list(item.machine_codes),
            calculation_time=calculation_time,
            silk_screen_clear_minutes=item.silk_screen_clear_minutes,
            remaining_production_hours=item.remaining_production_hours,
            prepare_clearance=item.prepare_clearance,
            reason=item.reason,
            message=item.message,
        )

    def _map_mixing_trace_record(
        self,
        item: AlgorithmMixingTraceRecord,
    ) -> MixingTraceRecordResponse:
        """在後端输入与算法内部模型之间执行【_map_mixing_trace_record】转换，并保留必要的校验信息。"""
        return MixingTraceRecordResponse(
            mix_trace_id=item.mix_trace_id,
            plan_id=item.plan_id,
            cutline_event_id=item.cutline_event_id,
            machine_code=item.machine_code,
            workshop_code=item.workshop_code,
            process_code=item.process_code,
            process_name=item.process_name,
            source_order_code=item.source_order_code,
            target_order_code=item.target_order_code,
            source_product_code=item.source_product_code,
            target_product_code=item.target_product_code,
            mix_start_time=item.mix_start_time,
            mixed_basket_start_index=item.mixed_basket_start_index,
            mixed_basket_end_index=item.mixed_basket_end_index,
            mixed_basket_count=item.mixed_basket_count,
            estimated_total_mixed_pieces=(
                item.estimated_total_mixed_pieces
            ),
            compositions=[
                MixingCompositionResponse(
                    order_code=composition.order_code,
                    product_code=composition.product_code,
                    sequence=composition.sequence,
                    estimated_pieces=composition.estimated_pieces,
                )
                for composition in item.compositions
            ],
            notification_status=item.notification_status,
        )

    def _map_pipeline_error(
        self,
        item: AlgorithmPipelineError,
    ) -> PipelineErrorResponse:
        """在後端输入与算法内部模型之间执行【_map_pipeline_error】转换，并保留必要的校验信息。"""
        error_code = item.error_code or pipeline_error_code(
            item.stage, item.reason
        )
        return PipelineErrorResponse(
            stage=item.stage,
            warning_type=item.warning_type,
            warning_key=item.warning_key,
            reason=item.reason,
            error_code=error_code,
            message=error_code_message(error_code, item.message),
        )

    @staticmethod
    def _map_mixing_trace_failure(item) -> MixingTraceErrorResponse:
        """将混料追溯失败转换为带中文描述的公开错误。"""
        error_code = mixing_trace_error_code(item.reason)
        return MixingTraceErrorResponse(
            machine_code=item.machine_code,
            reason=item.reason,
            error_code=error_code,
            message=error_code_message(error_code, item.message),
        )

    def _plan_warning_id(
        self,
        plan: AlgorithmStockoutCutlinePlan | AlgorithmOverflowCutlinePlan,
    ) -> str:
        """内部辅助步骤【_plan_warning_id】，为上层业务流程提供数据处理或共用判断。"""
        if isinstance(plan, AlgorithmStockoutCutlinePlan):
            return self._stockout_warning_id(
                plan.calculation_time,
                plan.buffer_code,
                plan.order_code,
            )
        return self._overflow_warning_id(
            plan.calculation_time,
            plan.buffer_code,
        )

    @staticmethod
    def _stockout_warning_id(warning_time, buffer_code, order_code) -> str:
        """内部辅助步骤【_stockout_warning_id】，为上层业务流程提供数据处理或共用判断。"""
        return (
            f"stockout:{warning_time.isoformat()}:"
            f"{buffer_code}:{order_code}"
        )

    @staticmethod
    def _overflow_warning_id(warning_time, buffer_code) -> str:
        """内部辅助步骤【_overflow_warning_id】，为上层业务流程提供数据处理或共用判断。"""
        return f"overflow:{warning_time.isoformat()}:{buffer_code}"

    @staticmethod
    def _required_capacity(value: float | None, label: str) -> float:
        """内部辅助步骤【_required_capacity】，为上层业务流程提供数据处理或共用判断。"""
        if value is None:
            raise ValueError(f"{label} capacity is required")
        return value
