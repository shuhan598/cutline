from __future__ import annotations

from dataclasses import dataclass
from math import isclose

from app.core.cutline_plan.errors import MachineSelectionEvaluationError
from app.schemas.request_schema import AlgorithmSnapshot
from app.schemas.result_schema import (
    AlgorithmBufferOverflowTimeResult,
    AlgorithmIntervalNetRateResult,
    AlgorithmOverflowCandidateMachine,
    AlgorithmOverflowCandidateResult,
    AlgorithmOverflowSelectionResult,
    AlgorithmOverflowTargetOption,
    AlgorithmOverflowWarningResult,
    AlgorithmRejectedMachineEvaluation,
    AlgorithmSelectedMachineEvaluation,
    AlgorithmStockoutCandidateMachine,
    AlgorithmStockoutCandidateResult,
    AlgorithmStockoutSelectionResult,
    AlgorithmStockoutWarningResult,
)


IntervalKey = tuple[str, str, str, str, str, str, str]


@dataclass
class VirtualCutlineState:
    """单次选择调用内累计使用的净速率、Buffer增长率和已选机台。"""

    interval_net_rates: dict[IntervalKey, float]
    buffer_growth_rates: dict[str, float]
    selected_machine_codes: set[str]


class MachineSelectionEvaluator:
    """保持候选顺序，逐台模拟双侧影响并累计选择安全机台。"""

    def select_stockout_machines(
        self,
        *,
        snapshot: AlgorithmSnapshot,
        warning: AlgorithmStockoutWarningResult,
        candidate_result: AlgorithmStockoutCandidateResult,
        interval_results: list[AlgorithmIntervalNetRateResult],
        overflow_results: list[AlgorithmBufferOverflowTimeResult],
    ) -> AlgorithmStockoutSelectionResult:
        stockout_warning_lead_minutes = (
            snapshot.config.stockout_warning_lead_minutes
        )
        overflow_warning_lead_minutes = (
            snapshot.config.overflow_warning_lead_minutes
        )
        if warning.net_consumption_rate <= 0:
            raise MachineSelectionEvaluationError(
                "stockout warning net consumption rate must be positive"
            )

        interval_by_key = self._interval_index(interval_results)
        buffer_by_code = self._buffer_index(overflow_results)
        buffer_code_by_main_id = self._buffer_code_by_main_id(
            overflow_results
        )
        target_key = self._warning_interval_key(warning)
        target_interval = interval_by_key.get(target_key)
        if target_interval is None:
            raise MachineSelectionEvaluationError(
                "stockout target interval does not exist"
            )
        if warning.buffer_code not in buffer_by_code:
            raise MachineSelectionEvaluationError(
                f"{warning.buffer_code} target buffer state does not exist"
            )

        state = VirtualCutlineState(
            interval_net_rates={
                key: interval.net_consumption_rate
                for key, interval in interval_by_key.items()
            },
            buffer_growth_rates={
                code: result.buffer_growth_rate
                for code, result in buffer_by_code.items()
            },
            selected_machine_codes=set(),
        )
        initial_gap = warning.net_consumption_rate
        remaining_gap = initial_gap
        total_contribution = 0.0
        selected: list[AlgorithmSelectedMachineEvaluation] = []
        rejected: list[AlgorithmRejectedMachineEvaluation] = []

        for candidate in candidate_result.candidates:
            if remaining_gap <= 0:
                break
            if candidate.machine_code in state.selected_machine_codes:
                rejected.append(
                    self._rejected(
                        candidate,
                        reason="duplicate_machine_selection",
                        message="machine has already been selected",
                    )
                )
                continue

            contribution = self._validated_capacity(
                candidate.contribution_capacity,
                candidate.output_quantity_30m,
                candidate.machine_code,
            )
            if contribution <= 0:
                rejected.append(
                    self._rejected(
                        candidate,
                        reason="no_effective_contribution",
                        message="candidate contribution capacity is not positive",
                    )
                )
                continue

            source_match = self._source_interval(
                candidate,
                interval_by_key,
            )
            if source_match is None:
                rejected.append(
                    self._rejected(
                        candidate,
                        reason="source_interval_not_found",
                        message="source interval cannot be located",
                    )
                )
                continue
            if source_match is False:
                rejected.append(
                    self._rejected(
                        candidate,
                        reason="source_interval_ambiguous",
                        message="multiple source intervals match the candidate",
                    )
                )
                continue
            source_key, source_interval = source_match
            source_before = state.interval_net_rates[source_key]
            source_after = source_before + contribution
            source_depletion = self._depletion_minutes(
                source_interval.current_quantity,
                source_after,
            )
            if (
                source_depletion is not None
                and source_depletion <= stockout_warning_lead_minutes
            ):
                rejected.append(
                    self._rejected(
                        candidate,
                        reason="source_order_stockout_risk",
                        source_interval=source_interval,
                        source_before=source_before,
                        source_after=source_after,
                        source_depletion=source_depletion,
                        message="borrowing the machine creates source stockout risk",
                    )
                )
                continue

            source_buffer_code = buffer_code_by_main_id.get(
                source_interval.main_id
            )
            target_buffer_code = buffer_code_by_main_id.get(
                target_interval.main_id
            )
            if source_buffer_code is None:
                rejected.append(
                    self._rejected(
                        candidate,
                        reason="source_buffer_state_not_found",
                        source_interval=source_interval,
                        source_before=source_before,
                        source_after=source_after,
                        source_depletion=source_depletion,
                        message="source buffer virtual state does not exist",
                    )
                )
                continue
            if target_buffer_code is None:
                raise MachineSelectionEvaluationError(
                    f"{target_interval.main_id} target buffer state "
                    "does not exist"
                )

            target_before = state.interval_net_rates[target_key]
            target_after = target_before - contribution
            source_growth_after, target_growth_after = self._buffer_growth_after(
                source_buffer_code=source_buffer_code,
                target_buffer_code=target_buffer_code,
                contribution=contribution,
                state=state,
            )
            target_overflow = self._overflow_minutes(
                buffer_by_code[target_buffer_code],
                target_growth_after,
            )
            if (
                target_overflow is not None
                and target_overflow <= overflow_warning_lead_minutes
            ):
                rejected.append(
                    self._rejected(
                        candidate,
                        reason="target_buffer_overflow_risk",
                        source_interval=source_interval,
                        target_interval=target_interval,
                        source_before=source_before,
                        source_after=source_after,
                        source_depletion=source_depletion,
                        target_before=target_before,
                        target_after=target_after,
                        target_overflow=target_overflow,
                        message="switching in creates target buffer overflow risk",
                    )
                )
                continue

            state.interval_net_rates[source_key] = source_after
            state.interval_net_rates[target_key] = target_after
            state.buffer_growth_rates[source_buffer_code] = source_growth_after
            state.buffer_growth_rates[target_buffer_code] = target_growth_after
            state.selected_machine_codes.add(candidate.machine_code)
            selected.append(
                AlgorithmSelectedMachineEvaluation(
                    machine_code=candidate.machine_code,
                    source_order_code=candidate.current_order_code,
                    target_order_code=warning.order_code,
                    source_buffer_code=source_buffer_code,
                    target_buffer_code=target_buffer_code,
                    process_code=candidate.process_code,
                    workshop_code=candidate.workshop_code,
                    wafer_size=warning.wafer_size,
                    source_wafer_spec=candidate.current_wafer_spec,
                    target_wafer_spec=warning.wafer_spec,
                    contribution_capacity=contribution,
                    reduced_capacity=None,
                    utilization_rate=candidate.utilization_rate,
                    idle_rate=candidate.idle_rate,
                    source_net_rate_before=source_before,
                    source_net_rate_after=source_after,
                    source_depletion_minutes_after=source_depletion,
                    target_net_rate_before=target_before,
                    target_net_rate_after=target_after,
                    target_overflow_minutes_after=target_overflow,
                )
            )
            total_contribution += contribution
            remaining_gap = max(0.0, remaining_gap - contribution)

        risk_resolved = remaining_gap <= 0
        return AlgorithmStockoutSelectionResult(
            workshop_code=warning.workshop_code,
            buffer_code=warning.buffer_code,
            order_code=warning.order_code,
            wafer_size=warning.wafer_size,
            wafer_spec=warning.wafer_spec,
            upstream_process_code=warning.upstream_process_code,
            downstream_process_code=warning.downstream_process_code,
            initial_capacity_gap=initial_gap,
            total_contribution_capacity=total_contribution,
            remaining_capacity_gap=remaining_gap,
            selected_machines=selected,
            rejected_machines=rejected,
            risk_resolved=risk_resolved,
            failure_reason=self._stockout_failure_reason(
                candidate_count=len(candidate_result.candidates),
                selected_count=len(selected),
                risk_resolved=risk_resolved,
            ),
        )

    def select_overflow_machines(
        self,
        *,
        snapshot: AlgorithmSnapshot,
        warning: AlgorithmOverflowWarningResult,
        candidate_result: AlgorithmOverflowCandidateResult,
        interval_results: list[AlgorithmIntervalNetRateResult],
        overflow_results: list[AlgorithmBufferOverflowTimeResult],
    ) -> AlgorithmOverflowSelectionResult:
        stockout_warning_lead_minutes = (
            snapshot.config.stockout_warning_lead_minutes
        )
        overflow_warning_lead_minutes = (
            snapshot.config.overflow_warning_lead_minutes
        )
        source_detail = self._maximum_growth_detail(warning)
        if candidate_result.source_order_code != source_detail.order_code:
            raise MachineSelectionEvaluationError(
                "candidate source order does not match warning maximum growth order"
            )

        interval_by_key = self._interval_index(interval_results)
        buffer_by_code = self._buffer_index(overflow_results)
        buffer_code_by_main_id = self._buffer_code_by_main_id(
            overflow_results
        )
        current_buffer = buffer_by_code.get(warning.buffer_code)
        if current_buffer is None:
            raise MachineSelectionEvaluationError(
                f"{warning.buffer_code} current overflow buffer state does not exist"
            )
        source_key: IntervalKey = (
            warning.workshop_code,
            warning.buffer_code,
            source_detail.order_code,
            source_detail.wafer_size,
            source_detail.wafer_spec,
            warning.upstream_process_code,
            warning.downstream_process_code,
        )
        source_interval = interval_by_key.get(source_key)
        if source_interval is None:
            source_matches = [
                (key, interval)
                for key, interval in interval_by_key.items()
                if interval.main_id == warning.main_id
                and interval.order_code == source_detail.order_code
                and interval.wafer_size == source_detail.wafer_size
                and interval.wafer_spec == source_detail.wafer_spec
                and interval.workshop_code == warning.workshop_code
                and interval.upstream_process_code
                == warning.upstream_process_code
                and interval.downstream_process_code
                == warning.downstream_process_code
            ]
            if len(source_matches) == 1:
                source_key, source_interval = source_matches[0]

        state = VirtualCutlineState(
            interval_net_rates={
                key: interval.net_consumption_rate
                for key, interval in interval_by_key.items()
            },
            buffer_growth_rates={
                code: result.buffer_growth_rate
                for code, result in buffer_by_code.items()
            },
            selected_machine_codes=set(),
        )
        state.buffer_growth_rates[warning.buffer_code] = (
            warning.buffer_growth_rate
        )
        selected: list[AlgorithmSelectedMachineEvaluation] = []
        rejected: list[AlgorithmRejectedMachineEvaluation] = []
        total_reduced_capacity = 0.0

        for candidate in candidate_result.candidates:
            _, risk_resolved = self._current_overflow_risk(
                warning,
                state.buffer_growth_rates[warning.buffer_code],
                overflow_warning_lead_minutes,
            )
            if risk_resolved:
                break
            if candidate.machine_code in state.selected_machine_codes:
                rejected.append(
                    self._overflow_rejected(
                        candidate,
                        None,
                        reason="duplicate_machine_selection",
                        message="machine has already been selected",
                    )
                )
                continue

            reduction = self._validated_capacity(
                candidate.reduced_capacity,
                candidate.output_quantity_30m,
                candidate.machine_code,
            )
            if reduction <= 0:
                rejected.append(
                    self._overflow_rejected(
                        candidate,
                        None,
                        reason="no_effective_reduction",
                        message="candidate reduced capacity is not positive",
                    )
                )
                continue
            if source_interval is None:
                rejected.append(
                    self._overflow_rejected(
                        candidate,
                        None,
                        reason="source_interval_not_found",
                        message="source interval cannot be located",
                    )
                )
                continue

            source_before = state.interval_net_rates[source_key]
            source_after = source_before + reduction
            source_depletion = self._depletion_minutes(
                source_interval.current_quantity,
                source_after,
            )
            if (
                source_depletion is not None
                and source_depletion <= stockout_warning_lead_minutes
            ):
                rejected.append(
                    self._overflow_rejected(
                        candidate,
                        None,
                        reason="source_order_stockout_risk",
                        source_interval=source_interval,
                        source_before=source_before,
                        source_after=source_after,
                        source_depletion=source_depletion,
                        message="borrowing the machine creates source stockout risk",
                    )
                )
                continue

            if not candidate.target_options:
                rejected.append(
                    self._overflow_rejected(
                        candidate,
                        None,
                        reason="no_valid_target_order",
                        source_interval=source_interval,
                        source_before=source_before,
                        source_after=source_after,
                        source_depletion=source_depletion,
                        message="candidate has no target options",
                    )
                )
                continue

            selected_option = False
            option_rejections: list[
                AlgorithmRejectedMachineEvaluation
            ] = []
            for target_option in candidate.target_options:
                if target_option.target_buffer_code == warning.buffer_code:
                    option_rejections.append(
                        self._overflow_rejected(
                            candidate,
                            target_option,
                            reason="target_in_same_overflow_buffer",
                            source_interval=source_interval,
                            source_before=source_before,
                            source_after=source_after,
                            source_depletion=source_depletion,
                            message="target option remains in current overflow buffer",
                        )
                    )
                    continue

                target_match = self._overflow_target_interval(
                    candidate,
                    target_option,
                    interval_by_key,
                )
                if target_match is None:
                    option_rejections.append(
                        self._overflow_rejected(
                            candidate,
                            target_option,
                            reason="target_interval_not_found",
                            source_interval=source_interval,
                            source_before=source_before,
                            source_after=source_after,
                            source_depletion=source_depletion,
                            message="target interval cannot be located",
                        )
                    )
                    continue
                if target_match is False:
                    option_rejections.append(
                        self._overflow_rejected(
                            candidate,
                            target_option,
                            reason="target_interval_ambiguous",
                            source_interval=source_interval,
                            source_before=source_before,
                            source_after=source_after,
                            source_depletion=source_depletion,
                            message="multiple target intervals match target option",
                        )
                    )
                    continue
                target_key, target_interval = target_match
                target_buffer_code = buffer_code_by_main_id.get(
                    target_interval.main_id
                )
                if target_buffer_code is None:
                    option_rejections.append(
                        self._overflow_rejected(
                            candidate,
                            target_option,
                            reason="target_buffer_state_not_found",
                            source_interval=source_interval,
                            target_interval=target_interval,
                            source_before=source_before,
                            source_after=source_after,
                            source_depletion=source_depletion,
                            message="target buffer virtual state does not exist",
                        )
                    )
                    continue
                if target_buffer_code == warning.buffer_code:
                    option_rejections.append(
                        self._overflow_rejected(
                            candidate,
                            target_option,
                            reason="target_in_same_overflow_buffer",
                            source_interval=source_interval,
                            target_interval=target_interval,
                            source_before=source_before,
                            source_after=source_after,
                            source_depletion=source_depletion,
                            message="target interval is in current overflow buffer",
                        )
                    )
                    continue
                target_buffer = buffer_by_code.get(target_buffer_code)
                if target_buffer is None:
                    option_rejections.append(
                        self._overflow_rejected(
                            candidate,
                            target_option,
                            reason="target_buffer_state_not_found",
                            source_interval=source_interval,
                            target_interval=target_interval,
                            source_before=source_before,
                            source_after=source_after,
                            source_depletion=source_depletion,
                            message="target buffer virtual state does not exist",
                        )
                    )
                    continue

                target_before = state.interval_net_rates[target_key]
                target_after = target_before - reduction
                source_growth_after = (
                    state.buffer_growth_rates[warning.buffer_code] - reduction
                )
                target_growth_after = (
                    state.buffer_growth_rates[target_buffer_code] + reduction
                )
                target_overflow = self._overflow_minutes(
                    target_buffer,
                    target_growth_after,
                )
                if (
                    target_overflow is not None
                    and target_overflow <= overflow_warning_lead_minutes
                ):
                    option_rejections.append(
                        self._overflow_rejected(
                            candidate,
                            target_option,
                            reason="target_buffer_overflow_risk",
                            source_interval=source_interval,
                            target_interval=target_interval,
                            source_before=source_before,
                            source_after=source_after,
                            source_depletion=source_depletion,
                            target_before=target_before,
                            target_after=target_after,
                            target_overflow=target_overflow,
                            message="switching in creates target buffer overflow risk",
                        )
                    )
                    continue

                state.interval_net_rates[source_key] = source_after
                state.interval_net_rates[target_key] = target_after
                state.buffer_growth_rates[warning.buffer_code] = (
                    source_growth_after
                )
                state.buffer_growth_rates[target_buffer_code] = (
                    target_growth_after
                )
                state.selected_machine_codes.add(candidate.machine_code)
                selected.append(
                    AlgorithmSelectedMachineEvaluation(
                        machine_code=candidate.machine_code,
                        source_order_code=source_detail.order_code,
                        target_order_code=target_option.target_order_code,
                        source_buffer_code=warning.buffer_code,
                        target_buffer_code=target_buffer_code,
                        process_code=candidate.process_code,
                        workshop_code=candidate.workshop_code,
                        wafer_size=candidate.current_wafer_size,
                        source_wafer_spec=source_detail.wafer_spec,
                        target_wafer_spec=target_option.target_wafer_spec,
                        contribution_capacity=None,
                        reduced_capacity=reduction,
                        utilization_rate=candidate.utilization_rate,
                        idle_rate=candidate.idle_rate,
                        source_net_rate_before=source_before,
                        source_net_rate_after=source_after,
                        source_depletion_minutes_after=source_depletion,
                        target_net_rate_before=target_before,
                        target_net_rate_after=target_after,
                        target_overflow_minutes_after=target_overflow,
                    )
                )
                total_reduced_capacity += reduction
                selected_option = True
                break

            if selected_option:
                continue
            rejected.extend(option_rejections)

        remaining_growth_rate = state.buffer_growth_rates[
            warning.buffer_code
        ]
        updated_overflow_minutes, risk_resolved = (
            self._current_overflow_risk(
                warning,
                remaining_growth_rate,
                overflow_warning_lead_minutes,
            )
        )
        return AlgorithmOverflowSelectionResult(
            workshop_code=warning.workshop_code,
            buffer_code=warning.buffer_code,
            upstream_process_code=warning.upstream_process_code,
            downstream_process_code=warning.downstream_process_code,
            source_order_code=source_detail.order_code,
            source_wafer_size=source_detail.wafer_size,
            source_wafer_spec=source_detail.wafer_spec,
            initial_growth_rate=warning.buffer_growth_rate,
            total_reduced_capacity=total_reduced_capacity,
            remaining_growth_rate=remaining_growth_rate,
            updated_overflow_minutes=updated_overflow_minutes,
            selected_machines=selected,
            rejected_machines=rejected,
            risk_resolved=risk_resolved,
            failure_reason=self._overflow_failure_reason(
                candidate_count=len(candidate_result.candidates),
                warning=warning,
                selected_count=len(selected),
                rejected=rejected,
                risk_resolved=risk_resolved,
            ),
        )

    def _maximum_growth_detail(
        self,
        warning: AlgorithmOverflowWarningResult,
    ):
        positive = [
            detail
            for detail in warning.order_growth_details
            if detail.growth_rate > 0
        ]
        if not positive:
            raise MachineSelectionEvaluationError(
                "overflow warning has no positive growth source order"
            )
        return min(
            positive,
            key=lambda detail: (-detail.growth_rate, detail.order_code),
        )

    def _overflow_target_interval(
        self,
        candidate: AlgorithmOverflowCandidateMachine,
        option: AlgorithmOverflowTargetOption,
        interval_by_key: dict[IntervalKey, AlgorithmIntervalNetRateResult],
    ):
        has_complete_context = all(
            value is not None
            for value in (
                option.target_buffer_code,
                option.target_workshop_code,
                option.target_upstream_process_code,
                option.target_downstream_process_code,
            )
        )
        if has_complete_context:
            key: IntervalKey = (
                option.target_workshop_code,
                option.target_buffer_code,
                option.target_order_code,
                option.target_wafer_size,
                option.target_wafer_spec,
                option.target_upstream_process_code,
                option.target_downstream_process_code,
            )
            interval = interval_by_key.get(key)
            if interval is None:
                return None
            return key, interval

        matches = [
            (key, interval)
            for key, interval in interval_by_key.items()
            if interval.order_code == option.target_order_code
            and interval.wafer_size == option.target_wafer_size
            and interval.wafer_spec == option.target_wafer_spec
            and interval.workshop_code == candidate.workshop_code
            and interval.upstream_process_code == candidate.process_code
        ]
        if not matches:
            return None
        if len(matches) > 1:
            return False
        return matches[0]

    def _current_overflow_risk(
        self,
        warning: AlgorithmOverflowWarningResult,
        growth_rate: float,
        overflow_warning_lead_minutes: float,
    ) -> tuple[float | None, bool]:
        if warning.total_inventory >= warning.max_capacity:
            return 0.0, False
        if growth_rate <= 0:
            return None, True
        updated_minutes = warning.remaining_capacity / growth_rate * 60
        return (
            updated_minutes,
            updated_minutes > overflow_warning_lead_minutes,
        )

    def _overflow_rejected(
        self,
        candidate: AlgorithmOverflowCandidateMachine,
        option: AlgorithmOverflowTargetOption | None,
        *,
        reason: str,
        source_interval: AlgorithmIntervalNetRateResult | None = None,
        target_interval: AlgorithmIntervalNetRateResult | None = None,
        source_before: float | None = None,
        source_after: float | None = None,
        source_depletion: float | None = None,
        target_before: float | None = None,
        target_after: float | None = None,
        target_overflow: float | None = None,
        message: str,
    ) -> AlgorithmRejectedMachineEvaluation:
        return AlgorithmRejectedMachineEvaluation(
            machine_code=candidate.machine_code,
            reason=reason,
            source_order_code=candidate.current_order_code,
            target_order_code=(
                option.target_order_code if option is not None else None
            ),
            source_buffer_code=(
                source_interval.buffer_code
                if source_interval is not None
                else None
            ),
            target_buffer_code=(
                target_interval.buffer_code
                if target_interval is not None
                else (
                    option.target_buffer_code
                    if option is not None
                    else None
                )
            ),
            source_net_rate_before=source_before,
            source_net_rate_after=source_after,
            source_depletion_minutes_after=source_depletion,
            target_net_rate_before=target_before,
            target_net_rate_after=target_after,
            target_overflow_minutes_after=target_overflow,
            message=message,
        )

    def _overflow_failure_reason(
        self,
        *,
        candidate_count: int,
        warning: AlgorithmOverflowWarningResult,
        selected_count: int,
        rejected: list[AlgorithmRejectedMachineEvaluation],
        risk_resolved: bool,
    ) -> str | None:
        if risk_resolved:
            return None
        if warning.total_inventory >= warning.max_capacity:
            return "current_buffer_already_over_capacity"
        if candidate_count == 0:
            return "no_candidate_machine"
        if selected_count > 0:
            return "insufficient_reduced_capacity"
        target_reasons = {
            "no_valid_target_order",
            "target_in_same_overflow_buffer",
            "target_interval_not_found",
            "target_interval_ambiguous",
            "target_buffer_state_not_found",
            "target_buffer_overflow_risk",
        }
        if rejected and all(item.reason in target_reasons for item in rejected):
            return "no_valid_target_order"
        return "all_candidates_rejected"

    def _interval_index(
        self,
        interval_results: list[AlgorithmIntervalNetRateResult],
    ) -> dict[IntervalKey, AlgorithmIntervalNetRateResult]:
        result: dict[IntervalKey, AlgorithmIntervalNetRateResult] = {}
        for interval in interval_results:
            key = self._interval_key(interval)
            if key in result:
                raise MachineSelectionEvaluationError(
                    f"duplicate interval result: {key}"
                )
            result[key] = interval
        return result

    def _buffer_index(
        self,
        overflow_results: list[AlgorithmBufferOverflowTimeResult],
    ) -> dict[str, AlgorithmBufferOverflowTimeResult]:
        result: dict[str, AlgorithmBufferOverflowTimeResult] = {}
        for overflow in overflow_results:
            if overflow.buffer_code in result:
                raise MachineSelectionEvaluationError(
                    f"duplicate buffer state: {overflow.buffer_code}"
                )
            result[overflow.buffer_code] = overflow
        return result

    def _buffer_code_by_main_id(
        self,
        overflow_results: list[AlgorithmBufferOverflowTimeResult],
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for overflow in overflow_results:
            if overflow.main_id in result:
                raise MachineSelectionEvaluationError(
                    f"duplicate main buffer state: {overflow.main_id}"
                )
            result[overflow.main_id] = overflow.buffer_code
        return result

    def _interval_key(self, interval) -> IntervalKey:
        return (
            interval.workshop_code,
            interval.buffer_code,
            interval.order_code,
            interval.wafer_size,
            interval.wafer_spec,
            interval.upstream_process_code,
            interval.downstream_process_code,
        )

    def _warning_interval_key(
        self,
        warning: AlgorithmStockoutWarningResult,
    ) -> IntervalKey:
        return (
            warning.workshop_code,
            warning.buffer_code,
            warning.order_code,
            warning.wafer_size,
            warning.wafer_spec,
            warning.upstream_process_code,
            warning.downstream_process_code,
        )

    def _source_interval(
        self,
        candidate: AlgorithmStockoutCandidateMachine,
        interval_by_key: dict[IntervalKey, AlgorithmIntervalNetRateResult],
    ):
        matches = [
            (key, interval)
            for key, interval in interval_by_key.items()
            if interval.workshop_code == candidate.workshop_code
            and interval.order_code == candidate.current_order_code
            and interval.wafer_size == candidate.current_wafer_size
            and interval.wafer_spec == candidate.current_wafer_spec
            and interval.upstream_process_code == candidate.process_code
        ]
        if not matches:
            return None
        if len(matches) > 1:
            return False
        return matches[0]

    def _validated_capacity(
        self,
        capacity: float,
        output_quantity_30m: float,
        machine_code: str,
    ) -> float:
        expected = output_quantity_30m * 2
        if not isclose(capacity, expected):
            raise MachineSelectionEvaluationError(
                f"{machine_code} candidate capacity {capacity} does not match "
                f"output_quantity_30m * 2 ({expected})"
            )
        return capacity

    def _depletion_minutes(
        self,
        current_quantity: float,
        net_rate: float,
    ) -> float | None:
        if net_rate <= 0:
            return None
        return current_quantity / net_rate * 60

    def _buffer_growth_after(
        self,
        *,
        source_buffer_code: str,
        target_buffer_code: str,
        contribution: float,
        state: VirtualCutlineState,
    ) -> tuple[float, float]:
        source_before = state.buffer_growth_rates[source_buffer_code]
        target_before = state.buffer_growth_rates[target_buffer_code]
        if source_buffer_code == target_buffer_code:
            return source_before, target_before
        return source_before - contribution, target_before + contribution

    def _overflow_minutes(
        self,
        buffer: AlgorithmBufferOverflowTimeResult,
        growth_rate: float,
    ) -> float | None:
        if buffer.total_inventory >= buffer.max_capacity:
            return 0.0
        if growth_rate <= 0:
            return None
        return (
            (buffer.max_capacity - buffer.total_inventory)
            / growth_rate
            * 60
        )

    def _rejected(
        self,
        candidate: AlgorithmStockoutCandidateMachine,
        *,
        reason: str,
        source_interval: AlgorithmIntervalNetRateResult | None = None,
        target_interval: AlgorithmIntervalNetRateResult | None = None,
        source_before: float | None = None,
        source_after: float | None = None,
        source_depletion: float | None = None,
        target_before: float | None = None,
        target_after: float | None = None,
        target_overflow: float | None = None,
        message: str,
    ) -> AlgorithmRejectedMachineEvaluation:
        return AlgorithmRejectedMachineEvaluation(
            machine_code=candidate.machine_code,
            reason=reason,
            source_order_code=candidate.current_order_code,
            target_order_code=candidate.target_order_code,
            source_buffer_code=(
                source_interval.buffer_code
                if source_interval is not None
                else None
            ),
            target_buffer_code=(
                target_interval.buffer_code
                if target_interval is not None
                else None
            ),
            source_net_rate_before=source_before,
            source_net_rate_after=source_after,
            source_depletion_minutes_after=source_depletion,
            target_net_rate_before=target_before,
            target_net_rate_after=target_after,
            target_overflow_minutes_after=target_overflow,
            message=message,
        )

    def _stockout_failure_reason(
        self,
        *,
        candidate_count: int,
        selected_count: int,
        risk_resolved: bool,
    ) -> str | None:
        if risk_resolved:
            return None
        if candidate_count == 0:
            return "no_candidate_machine"
        if selected_count == 0:
            return "all_candidates_rejected"
        return "insufficient_contribution_capacity"
