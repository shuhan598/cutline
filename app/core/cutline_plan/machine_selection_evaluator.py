"""通过虚拟切线评估候选机台，选择满足库存安全约束的组合。"""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose, isfinite

from app.core.cutline_plan.errors import MachineSelectionEvaluationError
from app.core.buffer_aggregation.models import (
    GroupKey,
    MainBufferGroup,
    PhysicalMainBufferState,
)
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


@dataclass
class VirtualGroupState:
    """记录同一轮虚拟评估中单个订单子状态的最新速率与库存。"""

    inventory_change_rate: float
    total_inventory: float
    total_capacity: float | None


class MachineSelectionEvaluator:
    """动态重排来源和目标订单，逐台模拟并累计安全机台组合。"""

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
        if snapshot.main_buffer_batch.groups_by_group_key:
            return self._select_stockout_from_batch(
                snapshot=snapshot,
                warning=warning,
                candidate_result=candidate_result,
                interval_results=interval_results,
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

    def _select_stockout_from_batch(
        self,
        *,
        snapshot: AlgorithmSnapshot,
        warning: AlgorithmStockoutWarningResult,
        candidate_result: AlgorithmStockoutCandidateResult,
        interval_results: list[AlgorithmIntervalNetRateResult],
    ) -> AlgorithmStockoutSelectionResult:
        batch = snapshot.main_buffer_batch
        receiver_key = (
            warning.group_key or candidate_result.receiver_group_key
        )
        if receiver_key is None:
            receiver_key = batch.group_key_by_buffer_code.get(
                warning.buffer_code
            )
        receiver = batch.groups_by_group_key.get(receiver_key)
        if receiver is None:
            raise MachineSelectionEvaluationError(
                "stockout receiver group cannot be located"
            )

        rates_by_key = {
            result.group_key: result
            for result in interval_results
            if result.group_key is not None
        }
        receiver_rate = rates_by_key.get(receiver.group_key)
        if receiver_rate is None:
            raise MachineSelectionEvaluationError(
                "stockout receiver rate cannot be located"
            )
        initial_rate = self._inventory_change_rate(receiver_rate)
        initial_gap = max(0.0, -initial_rate)
        if not receiver.auto_receive_eligible:
            rejected = [
                self._rejected(
                    candidate,
                    reason="target_capacity_unavailable",
                    target_interval=receiver_rate,
                    target_before=-initial_rate,
                    message=(
                        "receiver capacity is unavailable; target overflow "
                        "risk cannot be validated"
                    ),
                )
                for candidate in candidate_result.candidates
            ]
            return self._stockout_batch_result(
                warning=warning,
                initial_gap=initial_gap,
                remaining_gap=initial_gap,
                selected=[],
                rejected=rejected,
                failure_reason="target_capacity_unavailable",
            )

        # 一次 overflow 评估共享同一份 virtual state；每轮都从这里读取
        # 所有订单的最新速率，而不是回到原始 snapshot。
        virtual_groups: dict[GroupKey, VirtualGroupState] = {
            receiver.group_key: VirtualGroupState(
                inventory_change_rate=initial_rate,
                total_inventory=receiver.total_inventory,
                total_capacity=receiver.total_capacity,
            )
        }
        selected_codes: set[str] = set()
        selected: list[AlgorithmSelectedMachineEvaluation] = []
        rejected: list[AlgorithmRejectedMachineEvaluation] = []
        total_contribution = 0.0
        risk_resolved = self._stockout_resolved(
            virtual_groups[receiver.group_key],
            snapshot.config.stockout_warning_lead_minutes,
        )

        for candidate in candidate_result.candidates:
            if risk_resolved:
                break
            if candidate.machine_code in selected_codes:
                rejected.append(
                    self._rejected(
                        candidate,
                        reason="duplicate_machine_selection",
                        message="machine has already been selected",
                    )
                )
                continue
            donor_key = candidate.donor_group_key
            donor = batch.groups_by_group_key.get(donor_key)
            donor_rate = rates_by_key.get(donor_key)
            if (
                donor is None
                or donor_rate is None
                or not donor.auto_donate_eligible
            ):
                rejected.append(
                    self._rejected(
                        candidate,
                        reason="donor_group_not_found",
                        message="candidate donor group cannot be safely located",
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

            donor_state = virtual_groups.setdefault(
                donor.group_key,
                VirtualGroupState(
                    inventory_change_rate=self._inventory_change_rate(
                        donor_rate
                    ),
                    total_inventory=donor.total_inventory,
                    total_capacity=donor.total_capacity,
                ),
            )
            receiver_state = virtual_groups[receiver.group_key]
            donor_before = donor_state.inventory_change_rate
            receiver_before = receiver_state.inventory_change_rate
            donor_after = donor_before - contribution
            receiver_after = receiver_before + contribution
            if max(0.0, -receiver_after) >= max(0.0, -receiver_before):
                rejected.append(
                    self._rejected(
                        candidate,
                        reason="target_risk_not_improved",
                        message="candidate does not strictly improve receiver risk",
                    )
                )
                continue
            donor_depletion = self._group_depletion_minutes(
                donor.total_inventory,
                donor_after,
            )
            if (
                donor_depletion is not None
                and donor_depletion
                <= snapshot.config.stockout_warning_lead_minutes
            ):
                rejected.append(
                    self._rejected(
                        candidate,
                        reason="source_order_stockout_risk",
                        message="borrowing the machine creates donor stockout risk",
                    )
                )
                continue
            receiver_overflow = self._group_overflow_minutes(
                receiver,
                receiver_after,
            )
            if (
                receiver_overflow is not None
                and receiver_overflow
                <= snapshot.config.overflow_warning_lead_minutes
            ):
                rejected.append(
                    self._rejected(
                        candidate,
                        reason="target_buffer_overflow_risk",
                        message="switching in creates receiver overflow risk",
                    )
                )
                continue

            donor_state.inventory_change_rate = donor_after
            receiver_state.inventory_change_rate = receiver_after
            selected_codes.add(candidate.machine_code)
            total_contribution += contribution
            selected.append(
                AlgorithmSelectedMachineEvaluation(
                    machine_code=candidate.machine_code,
                    source_order_code=donor.order_code,
                    target_order_code=receiver.order_code,
                    source_buffer_code=(
                        donor.representative_buffer_code or ""
                    ),
                    target_buffer_code=(
                        receiver.representative_buffer_code or ""
                    ),
                    process_code=candidate.process_code,
                    workshop_code=candidate.workshop_code,
                    wafer_size=warning.wafer_size,
                    source_wafer_spec=candidate.current_wafer_spec,
                    target_wafer_spec=warning.wafer_spec,
                    contribution_capacity=contribution,
                    reduced_capacity=None,
                    utilization_rate=candidate.utilization_rate,
                    idle_rate=candidate.idle_rate,
                    source_net_rate_before=-donor_before,
                    source_net_rate_after=-donor_after,
                    source_depletion_minutes_after=donor_depletion,
                    target_net_rate_before=-receiver_before,
                    target_net_rate_after=-receiver_after,
                    target_overflow_minutes_after=receiver_overflow,
                    receiver_group_key=receiver.group_key,
                    donor_group_key=donor.group_key,
                    donor_main_id=donor.main_id,
                )
            )
            risk_resolved = self._stockout_resolved(
                receiver_state,
                snapshot.config.stockout_warning_lead_minutes,
            )

        remaining_gap = max(
            0.0,
            -virtual_groups[receiver.group_key].inventory_change_rate,
        )
        failure_reason = None
        if not risk_resolved:
            failure_reason = self._stockout_failure_reason(
                candidate_count=len(candidate_result.candidates),
                selected_count=len(selected),
                risk_resolved=False,
            )
        return self._stockout_batch_result(
            warning=warning,
            initial_gap=initial_gap,
            remaining_gap=remaining_gap,
            selected=selected,
            rejected=rejected,
            failure_reason=failure_reason,
            total_contribution=total_contribution,
            risk_resolved=risk_resolved,
        )

    @staticmethod
    def _inventory_change_rate(
        result: AlgorithmIntervalNetRateResult,
    ) -> float:
        if result.inventory_change_rate is not None:
            return result.inventory_change_rate
        return -result.net_consumption_rate

    @staticmethod
    def _group_depletion_minutes(
        total_inventory: float,
        inventory_change_rate: float,
    ) -> float | None:
        if inventory_change_rate >= 0:
            return None
        return total_inventory / abs(inventory_change_rate) * 60

    @staticmethod
    def _group_overflow_minutes(
        group: MainBufferGroup,
        inventory_change_rate: float,
    ) -> float | None:
        if inventory_change_rate <= 0:
            return None
        if group.total_capacity is None:
            return 0.0
        remaining = group.total_capacity - group.total_inventory
        if remaining <= 0:
            return 0.0
        return remaining / inventory_change_rate * 60

    def _stockout_resolved(
        self,
        state: VirtualGroupState,
        lead_minutes: float,
    ) -> bool:
        if state.inventory_change_rate >= 0:
            return True
        depletion = self._group_depletion_minutes(
            state.total_inventory,
            state.inventory_change_rate,
        )
        return depletion is not None and depletion > lead_minutes

    @staticmethod
    def _stockout_batch_result(
        *,
        warning: AlgorithmStockoutWarningResult,
        initial_gap: float,
        remaining_gap: float,
        selected: list[AlgorithmSelectedMachineEvaluation],
        rejected: list[AlgorithmRejectedMachineEvaluation],
        failure_reason: str | None,
        total_contribution: float = 0.0,
        risk_resolved: bool = False,
    ) -> AlgorithmStockoutSelectionResult:
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
            failure_reason=failure_reason,
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
        if snapshot.main_buffer_batch.groups_by_group_key:
            return self._select_overflow_from_batch(
                snapshot=snapshot,
                warning=warning,
                candidate_result=candidate_result,
                interval_results=interval_results,
            )
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

    def _select_overflow_from_batch(
        self,
        *,
        snapshot: AlgorithmSnapshot,
        warning: AlgorithmOverflowWarningResult,
        candidate_result: AlgorithmOverflowCandidateResult,
        interval_results: list[AlgorithmIntervalNetRateResult],
    ) -> AlgorithmOverflowSelectionResult:
        batch = snapshot.main_buffer_batch
        source_key = warning.group_key
        if source_key is None:
            source_key = batch.group_key_by_buffer_code.get(
                warning.buffer_code
            )
        warning_source_group = batch.groups_by_group_key.get(source_key)
        if warning_source_group is None:
            raise MachineSelectionEvaluationError(
                "overflow source group cannot be located"
            )
        if (
            candidate_result.source_group_key is not None
            and candidate_result.source_group_key
            != warning_source_group.group_key
        ):
            raise MachineSelectionEvaluationError(
                "candidate source group does not match warning"
            )
        if candidate_result.source_order_code != warning_source_group.order_code:
            raise MachineSelectionEvaluationError(
                "candidate source order does not match overflow source group"
            )

        rates_by_key = {
            result.group_key: result
            for result in interval_results
            if result.group_key is not None
        }
        warning_source_rate_result = rates_by_key.get(
            warning_source_group.group_key
        )
        if warning_source_rate_result is None:
            raise MachineSelectionEvaluationError(
                "overflow source group rate cannot be located"
            )
        warning_source_rate = self._inventory_change_rate(
            warning_source_rate_result
        )
        if not isfinite(warning_source_rate):
            raise MachineSelectionEvaluationError(
                "overflow source group rate must be finite"
            )
        virtual_groups: dict[GroupKey, VirtualGroupState] = {
            group.group_key: VirtualGroupState(
                inventory_change_rate=self._inventory_change_rate(rates_by_key[group.group_key]),
                total_inventory=group.total_inventory,
                total_capacity=group.total_capacity,
            )
            for group in batch.groups_by_main_id.get(
                warning_source_group.main_id, ()
            )
            if group.order_code and group.group_key in rates_by_key
        }
        old_main_rate = sum(state.inventory_change_rate for state in virtual_groups.values())
        initial_main_rate = old_main_rate
        selected_machine_codes: set[str] = set()
        selected: list[AlgorithmSelectedMachineEvaluation] = []
        rejected: list[AlgorithmRejectedMachineEvaluation] = []
        total_reduced_capacity = 0.0
        risk_resolved = self._physical_main_resolved(
            snapshot, warning_source_group.main_id, virtual_groups, batch,
        )

        remaining_candidates = list(enumerate(candidate_result.candidates))
        deferred_candidates = []
        deferred_rejections = []
        # 每成功选择一台机后重新进入循环，从全部订单中动态选 SourceOrder。
        while not risk_resolved and (
            remaining_candidates or deferred_candidates
        ):
            # 只有当前 virtual rate 为正的订单可以作为 source，并按大到小排序。
            source_keys = [
                key
                for key, state in sorted(
                    virtual_groups.items(),
                    key=lambda item: (
                        -item[1].inventory_change_rate,
                        item[0].order_code,
                    ),
                )
                if state.inventory_change_rate > 0
            ]
            source_rank = {key: index for index, key in enumerate(source_keys)}
            available = [
                (position, candidate)
                for position, candidate in remaining_candidates
                if candidate.source_group_key in source_rank
            ]
            if not available:
                rejected.extend(deferred_rejections)
                break
            def candidate_priority(item):
                # 优先级依次为 source 排名、最新 target rate、稳定订单编码、
                # 物理改善量和原候选位置；machine 自身既有排序仍作为稳定输入。
                position, candidate = item
                options = sorted(
                    candidate.target_options,
                    key=lambda option: (
                        virtual_groups.get(option.target_group_key).inventory_change_rate
                        if option.target_group_key in virtual_groups
                        else float("inf"),
                        option.target_order_code,
                    ),
                )
                if options:
                    option = options[0]
                    target_state = virtual_groups.get(option.target_group_key)
                    target_rate = (
                        target_state.inventory_change_rate
                        if target_state is not None
                        else float("inf")
                    )
                    target_effect = self._target_effect_capacity(
                        snapshot,
                        candidate.machine_code,
                        option.target_product_code,
                        candidate.reduced_capacity,
                    )
                    improvement = candidate.reduced_capacity - target_effect
                    target_order_code = option.target_order_code
                else:
                    target_rate = float("inf")
                    target_order_code = ""
                    improvement = float("-inf")
                return (
                    source_rank[candidate.source_group_key],
                    target_rate,
                    target_order_code,
                    -improvement,
                    position,
                )

            candidate_position, candidate = min(
                available,
                key=candidate_priority,
            )
            remaining_candidates = [
                item for item in remaining_candidates
                if item[0] != candidate_position
            ]
            source_group = batch.groups_by_group_key.get(
                candidate.source_group_key
            )
            if source_group is None:
                rejected.append(
                    self._overflow_rejected(
                        candidate,
                        None,
                        reason="source_group_not_found",
                        message="candidate source group cannot be located",
                    )
                )
                continue
            source_rate_result = rates_by_key.get(source_group.group_key)
            if source_rate_result is None:
                rejected.append(
                    self._overflow_rejected(
                        candidate,
                        None,
                        reason="source_group_not_found",
                        message="candidate source rate cannot be located",
                    )
                )
                continue
            # 同一物理机台在整轮 virtual selection 中最多只能被采用一次。
            if candidate.machine_code in selected_machine_codes:
                rejected.append(
                    self._overflow_rejected(
                        candidate,
                        None,
                        reason="duplicate_machine_selection",
                        message="machine has already been selected",
                    )
                )
                continue
            if not source_group.auto_donate_eligible:
                rejected.append(
                    self._overflow_rejected(
                        candidate,
                        None,
                        reason="source_group_not_found",
                        message="overflow source group cannot safely donate",
                    )
                )
                continue
            if (
                not isfinite(candidate.reduced_capacity)
                or not isfinite(candidate.output_quantity_30m)
            ):
                rejected.append(
                    self._overflow_rejected(
                        candidate,
                        None,
                        reason="invalid_reduction",
                        message="candidate reduction must be finite",
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
            if (
                candidate.source_group_key is not None
                and candidate.source_group_key != source_group.group_key
            ):
                rejected.append(
                    self._overflow_rejected(
                        candidate,
                        None,
                        reason="source_group_not_found",
                        message="candidate source group does not match warning",
                    )
                )
                continue
            if (
                candidate.current_order_code != source_group.order_code
                or candidate.current_product_code != source_group.product_code
                or candidate.current_wafer_size
                != source_rate_result.wafer_size
                or candidate.current_wafer_spec
                != source_rate_result.wafer_spec
                or candidate.workshop_code != source_group.workshop_code
                or candidate.process_code
                != source_rate_result.upstream_process_code
            ):
                rejected.append(
                    self._overflow_rejected(
                        candidate,
                        None,
                        reason="source_group_not_found",
                        message="candidate source identity does not match group",
                    )
                )
                continue

            source_state = virtual_groups[source_group.group_key]
            source_before = source_state.inventory_change_rate
            source_after = source_before - reduction
            if max(0.0, source_after) >= max(0.0, source_before):
                rejected.append(
                    self._overflow_rejected(
                        candidate,
                        None,
                        reason="source_risk_not_improved",
                        source_interval=source_rate_result,
                        source_before=-source_before,
                        source_after=-source_after,
                        message="candidate does not strictly improve source risk",
                    )
                )
                continue
            source_depletion = self._group_depletion_minutes(
                source_group.total_inventory,
                source_after,
            )
            # 切走 source 机台不能制造新的断料风险；边界等于 lead 也属于风险。
            if (
                source_depletion is not None
                and source_depletion
                <= snapshot.config.stockout_warning_lead_minutes
            ):
                # 该拒绝可能随其他虚拟动作而改变，因此暂存到状态更新后重试。
                deferred_candidates.append((candidate_position, candidate))
                deferred_rejections.append(
                    self._overflow_rejected(
                        candidate,
                        None,
                        reason="source_order_stockout_risk",
                        source_interval=source_rate_result,
                        source_before=-source_before,
                        source_after=-source_after,
                        source_depletion=source_depletion,
                        message=(
                            "borrowing the machine creates source stockout risk"
                        ),
                    )
                )
                continue
            if not candidate.target_options:
                rejected.append(
                    self._overflow_rejected(
                        candidate,
                        None,
                        reason="no_valid_target_order",
                        source_interval=source_rate_result,
                        source_before=-source_before,
                        source_after=-source_after,
                        source_depletion=source_depletion,
                        message="candidate has no target options",
                    )
                )
                continue

            option_rejections: list[
                AlgorithmRejectedMachineEvaluation
            ] = []
            selected_option = False
            # TargetOrder 按当前 virtual rate 从小到大重排，订单编码只负责稳定 tie-break。
            options = sorted(
                candidate.target_options,
                key=lambda option: (
                    virtual_groups.get(option.target_group_key).inventory_change_rate
                    if option.target_group_key in virtual_groups
                    else float("inf"),
                    option.target_order_code,
                ),
            )
            for option in options:
                target_group = batch.groups_by_group_key.get(
                    option.target_group_key
                )
                target_rate_result = rates_by_key.get(
                    option.target_group_key
                )
                if (
                    target_group is None
                    or target_rate_result is None
                    or not target_group.auto_receive_eligible
                    or target_group.group_key == source_group.group_key
                    or target_group.main_id != source_group.main_id
                    or target_group.order_code == source_group.order_code
                    or target_group.order_code
                    != option.target_order_code
                    or target_group.product_code
                    != option.target_product_code
                    or target_group.representative_buffer_code
                    != option.target_buffer_code
                    or target_group.workshop_code
                    != option.target_workshop_code
                    or target_rate_result.main_id != target_group.main_id
                    or target_rate_result.buffer_code
                    != target_group.representative_buffer_code
                    or target_rate_result.order_code
                    != option.target_order_code
                    or target_rate_result.wafer_size
                    != option.target_wafer_size
                    or target_rate_result.wafer_spec
                    != option.target_wafer_spec
                    or target_rate_result.workshop_code
                    != option.target_workshop_code
                    or target_rate_result.upstream_process_code
                    != option.target_upstream_process_code
                    or target_rate_result.downstream_process_code
                    != option.target_downstream_process_code
                ):
                    option_rejections.append(
                        self._overflow_rejected(
                            candidate,
                            option,
                            reason="target_group_not_found",
                            source_interval=source_rate_result,
                            source_before=-source_before,
                            source_after=-source_after,
                            source_depletion=source_depletion,
                            message="target group cannot be safely located",
                        )
                    )
                    continue
                target_state = virtual_groups.get(target_group.group_key)
                if target_state is None:
                    target_rate = self._inventory_change_rate(
                        target_rate_result
                    )
                    if not isfinite(target_rate):
                        option_rejections.append(
                            self._overflow_rejected(
                                candidate,
                                option,
                                reason="invalid_target_rate",
                                source_interval=source_rate_result,
                                target_interval=target_rate_result,
                                source_before=-source_before,
                                source_after=-source_after,
                                source_depletion=source_depletion,
                                message="target group rate must be finite",
                            )
                        )
                        continue
                    target_state = VirtualGroupState(
                        inventory_change_rate=target_rate,
                        total_inventory=target_group.total_inventory,
                        total_capacity=target_group.total_capacity,
                    )
                target_before = target_state.inventory_change_rate
                target_effect = self._target_effect_capacity(
                    snapshot,
                    candidate.machine_code,
                    target_group.product_code,
                    reduction,
                )
                target_after = target_before + target_effect
                if target_before < 0 and target_after <= target_before:
                    option_rejections.append(
                        self._overflow_rejected(
                            candidate,
                            option,
                            reason="target_risk_not_improved",
                            source_interval=source_rate_result,
                            target_interval=target_rate_result,
                            source_before=-source_before,
                            source_after=-source_after,
                            source_depletion=source_depletion,
                            target_before=-target_before,
                            target_after=-target_after,
                            message="candidate does not strictly improve target gap",
                        )
                    )
                    continue
                # source 减少量与 target 新增量共同决定物理 main 的真实变化。
                projected_main_rate = old_main_rate - reduction + target_effect
                if projected_main_rate >= old_main_rate:
                    option_rejections.append(
                        self._overflow_rejected(
                            candidate,
                            option,
                            reason="main_rate_not_improved",
                            source_interval=source_rate_result,
                            target_interval=target_rate_result,
                            source_before=-source_before,
                            source_after=-source_after,
                            source_depletion=source_depletion,
                            target_before=-target_before,
                            target_after=-target_after,
                            message="candidate does not strictly reduce physical main growth",
                        )
                    )
                    continue
                projected_states = dict(virtual_groups)
                projected_states[source_group.group_key] = VirtualGroupState(
                    inventory_change_rate=source_after,
                    total_inventory=source_state.total_inventory,
                    total_capacity=source_state.total_capacity,
                )
                projected_states[target_group.group_key] = VirtualGroupState(
                    inventory_change_rate=target_after,
                    total_inventory=target_state.total_inventory,
                    total_capacity=target_state.total_capacity,
                )
                target_overflow = self._physical_overflow_minutes(
                    self._physical_state(batch, source_group.main_id),
                    sum(state.inventory_change_rate for state in projected_states.values()),
                )

                # 只有通过全部安全检查后才提交 virtual state，失败分支不会污染后续轮次。
                source_state.inventory_change_rate = source_after
                target_state.inventory_change_rate = target_after
                virtual_groups[target_group.group_key] = target_state
                selected_machine_codes.add(candidate.machine_code)
                total_reduced_capacity += reduction
                selected.append(
                    AlgorithmSelectedMachineEvaluation(
                        machine_code=candidate.machine_code,
                        source_order_code=source_group.order_code,
                        target_order_code=target_group.order_code,
                        source_buffer_code=(
                            source_group.representative_buffer_code or ""
                        ),
                        target_buffer_code=(
                            target_group.representative_buffer_code or ""
                        ),
                        process_code=candidate.process_code,
                        workshop_code=candidate.workshop_code,
                        wafer_size=candidate.current_wafer_size,
                        source_wafer_spec=source_rate_result.wafer_spec,
                        target_wafer_spec=target_rate_result.wafer_spec,
                        contribution_capacity=None,
                        reduced_capacity=reduction,
                        utilization_rate=candidate.utilization_rate,
                        idle_rate=candidate.idle_rate,
                        source_net_rate_before=-source_before,
                        source_net_rate_after=-source_after,
                        source_depletion_minutes_after=source_depletion,
                        target_net_rate_before=-target_before,
                        target_net_rate_after=-target_after,
                        target_overflow_minutes_after=target_overflow,
                        source_group_key=source_group.group_key,
                        target_group_key=target_group.group_key,
                    )
                )
                # 状态已经变化，重新放回此前因 source stockout 暂缓的候选。
                remaining_candidates.extend(deferred_candidates)
                deferred_candidates.clear()
                deferred_rejections.clear()
                selected_option = True
                old_main_rate = projected_main_rate
                risk_resolved = self._physical_main_resolved(
                    snapshot, source_group.main_id, virtual_groups, batch,
                )
                break

            if not selected_option:
                rejected.extend(option_rejections)

        remaining_rate = sum(state.inventory_change_rate for state in virtual_groups.values())
        updated_overflow_minutes = self._physical_overflow_minutes(
            self._physical_state(batch, warning_source_group.main_id),
            remaining_rate,
        )
        failure_reason = self._overflow_failure_reason(
            candidate_count=len(candidate_result.candidates),
            warning=warning,
            selected_count=len(selected),
            rejected=rejected,
            risk_resolved=risk_resolved,
        )
        return AlgorithmOverflowSelectionResult(
            workshop_code=warning_source_group.workshop_code,
            buffer_code=warning_source_group.representative_buffer_code or "",
            upstream_process_code=warning.upstream_process_code,
            downstream_process_code=warning.downstream_process_code,
            source_order_code=warning_source_group.order_code,
            source_wafer_size=candidate_result.source_wafer_size,
            source_wafer_spec=warning_source_rate_result.wafer_spec,
            initial_growth_rate=initial_main_rate,
            total_reduced_capacity=total_reduced_capacity,
            remaining_growth_rate=remaining_rate,
            updated_overflow_minutes=updated_overflow_minutes,
            selected_machines=selected,
            rejected_machines=rejected,
            risk_resolved=risk_resolved,
            failure_reason=failure_reason,
        )

    def _overflow_group_resolved(
        self,
        group: MainBufferGroup,
        state: VirtualGroupState,
        lead_minutes: float,
    ) -> bool:
        if state.inventory_change_rate <= 0:
            return True
        overflow_minutes = self._group_overflow_minutes(
            group,
            state.inventory_change_rate,
        )
        return (
            overflow_minutes is not None
            and overflow_minutes > lead_minutes
        )

    def _physical_overflow_minutes(self, physical, growth_rate: float):
        if physical is None or physical.total_capacity is None:
            return None
        if physical.total_inventory >= physical.total_capacity:
            return 0.0
        if growth_rate <= 0:
            return None
        return (physical.total_capacity - physical.total_inventory) / growth_rate * 60

    def _physical_main_resolved(self, snapshot, main_id, virtual_groups, batch):
        total_rate = sum(state.inventory_change_rate for state in virtual_groups.values())
        minutes = self._physical_overflow_minutes(
            self._physical_state(batch, main_id), total_rate,
        )
        return total_rate <= 0 or (
            minutes is not None
            and minutes > snapshot.config.overflow_warning_lead_minutes
        )

    @staticmethod
    def _target_effect_capacity(snapshot, machine_code, product_code, fallback):
        matches = [
            item.actual_capacity
            for item in snapshot.machine_product_capacities
            if item.machine_code == machine_code and item.product_code == product_code
        ]
        return matches[0] if matches else fallback

    @staticmethod
    def _physical_state(batch, main_id):
        state = batch.physical_main_buffers_by_main_id.get(main_id)
        if state is not None:
            return state
        groups = batch.groups_by_main_id.get(main_id, ())
        if not groups:
            return None
        first = groups[0]
        inventory = sum(group.total_inventory for group in groups)
        return PhysicalMainBufferState(
            main_id=main_id,
            workshop_code=first.workshop_code,
            ordered_service_process_codes=first.ordered_service_process_codes,
            physical_buffer_key=first.physical_buffer_key,
            buffer_codes=tuple(sorted({code for group in groups for code in group.buffer_codes})),
            total_inventory=inventory,
            total_capacity=first.total_capacity,
            remaining_capacity=(first.total_capacity - inventory if first.total_capacity is not None else None),
            representative_buffer_code=first.representative_buffer_code,
            order_codes=tuple(group.order_code for group in groups if group.order_code),
            stockout_eligible=first.stockout_eligible,
            overflow_eligible=first.overflow_eligible,
            stockout_warning_eligible=first.stockout_warning_eligible,
            overflow_warning_eligible=first.overflow_warning_eligible,
            auto_receive_eligible=first.auto_receive_eligible,
            auto_donate_eligible=first.auto_donate_eligible,
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
