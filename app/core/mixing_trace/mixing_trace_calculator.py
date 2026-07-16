from __future__ import annotations

from datetime import datetime, timedelta
from math import isfinite

from app.core.mixing_trace.errors import MixingTraceCalculationError
from app.schemas.request_schema import AlgorithmSnapshot
from app.schemas.result_schema import (
    AlgorithmCutlineDecisionResult,
    AlgorithmCutlinePlan,
    AlgorithmMixingComposition,
    AlgorithmMixingTraceBatchResult,
    AlgorithmMixingTraceFailure,
    AlgorithmMixingTraceRecord,
)


class MixingTraceCalculator:
    """从正式切线方案批量计算精简混料追溯记录。"""

    def calculate_for_plan(
        self,
        *,
        snapshot: AlgorithmSnapshot,
        plan: AlgorithmCutlinePlan,
    ) -> AlgorithmMixingTraceBatchResult:
        if not self._is_executable_plan(plan):
            return AlgorithmMixingTraceBatchResult()

        records: list[AlgorithmMixingTraceRecord] = []
        failures: list[AlgorithmMixingTraceFailure] = []
        for selected_machine in plan.selected_machines:
            try:
                records.append(
                    self._calculate_machine(
                        snapshot=snapshot,
                        plan=plan,
                        selected_machine=selected_machine,
                    )
                )
            except MixingTraceCalculationError as error:
                failures.append(
                    self._failure(
                        plan=plan,
                        selected_machine=selected_machine,
                        error=error,
                    )
                )

        records.sort(
            key=lambda item: (
                item.mix_start_time,
                item.machine_code,
                item.cutline_event_id,
            )
        )
        failures.sort(
            key=lambda item: (item.machine_code, item.cutline_event_id)
        )
        return AlgorithmMixingTraceBatchResult(
            records=records,
            failures=failures,
        )

    def calculate_for_decision(
        self,
        *,
        snapshot: AlgorithmSnapshot,
        decision: AlgorithmCutlineDecisionResult,
    ) -> AlgorithmMixingTraceBatchResult:
        if decision.plan is None:
            return AlgorithmMixingTraceBatchResult()
        return self.calculate_for_plan(snapshot=snapshot, plan=decision.plan)

    def _is_executable_plan(self, plan: AlgorithmCutlinePlan) -> bool:
        if plan is None:
            return False
        if getattr(plan, "risk_resolved", True) is not True:
            return False
        if getattr(plan, "manual_intervention_required", False) is not False:
            return False
        return bool(getattr(plan, "selected_machines", []))

    def _calculate_machine(
        self,
        *,
        snapshot: AlgorithmSnapshot,
        plan: AlgorithmCutlinePlan,
        selected_machine,
    ) -> AlgorithmMixingTraceRecord:
        plan_id = self._required_context(plan, "plan_id")
        machine_code = self._required_context(
            selected_machine,
            "machine_code",
        )
        source_order_code = self._required_context(
            selected_machine,
            "source_order_code",
        )
        target_order_code = self._required_context(
            selected_machine,
            "target_order_code",
        )
        workshop_code = self._required_context(
            selected_machine,
            "workshop_code",
        )
        process_code = self._required_context(
            selected_machine,
            "process_code",
        )

        if source_order_code == target_order_code:
            self._raise(
                "same_order_transition_invalid",
                f"source and target order are both {source_order_code}",
            )

        source_order = self._unique_order(
            snapshot,
            source_order_code,
            missing_reason="source_order_not_found",
        )
        target_order = self._unique_order(
            snapshot,
            target_order_code,
            missing_reason="target_order_not_found",
        )
        source_product_code = self._resolved_product_code(
            selected_machine=selected_machine,
            field_name="source_product_code",
            order_product_code=source_order.product_code,
        )
        target_product_code = self._resolved_product_code(
            selected_machine=selected_machine,
            field_name="target_product_code",
            order_product_code=target_order.product_code,
        )
        if source_product_code == target_product_code:
            self._raise(
                "same_product_transition_no_mixing",
                f"source and target product are both {source_product_code}",
            )

        process_name = self._process_name(
            snapshot=snapshot,
            machine_code=machine_code,
            process_code=process_code,
        )
        runtime = self._runtime(snapshot, machine_code)
        actual_capacity_per_hour = self._actual_capacity(runtime)
        proc_seconds = self._process_duration(
            snapshot=snapshot,
            machine_code=machine_code,
            source_product_code=source_product_code,
        )
        plan_generated_time = self._plan_generated_time(plan)

        config = snapshot.config
        try:
            estimated_cutline_time = plan_generated_time + timedelta(
                minutes=config.cutline_execution_delay_minutes
            )
            residual_pieces = (
                config.mixing_input_max_baskets
                * config.basket_capacity_pieces
            )
            residual_consumption_minutes = (
                residual_pieces / actual_capacity_per_hour * 60
            )
            process_time_minutes = proc_seconds / 60
            mix_start_time = estimated_cutline_time + timedelta(
                minutes=(
                    residual_consumption_minutes
                    + config.agv_delivery_minutes
                    + process_time_minutes
                )
            )
            notification_status = (
                "scheduled"
                if snapshot.current_time < mix_start_time
                else "due"
            )
        except (OverflowError, TypeError) as error:
            self._raise(
                "mix_start_time_unrepresentable",
                f"mix start time cannot be represented: {error}",
            )

        estimated_total_mixed_pieces = (
            config.mixed_basket_count * config.basket_capacity_pieces
        )
        source_estimated_pieces = estimated_total_mixed_pieces // 2
        target_estimated_pieces = (
            estimated_total_mixed_pieces - source_estimated_pieces
        )
        cutline_event_id = f"CUT-{plan_id}-{machine_code}"
        return AlgorithmMixingTraceRecord(
            mix_trace_id=f"MIX-{plan_id}-{machine_code}",
            plan_id=plan_id,
            cutline_event_id=cutline_event_id,
            machine_code=machine_code,
            workshop_code=workshop_code,
            process_code=process_code,
            process_name=process_name,
            source_order_code=source_order_code,
            target_order_code=target_order_code,
            source_product_code=source_product_code,
            target_product_code=target_product_code,
            mix_start_time=mix_start_time,
            mixed_basket_start_index=1,
            mixed_basket_end_index=config.mixed_basket_count,
            mixed_basket_count=config.mixed_basket_count,
            estimated_total_mixed_pieces=estimated_total_mixed_pieces,
            compositions=[
                AlgorithmMixingComposition(
                    order_code=source_order_code,
                    product_code=source_product_code,
                    sequence=1,
                    estimated_pieces=source_estimated_pieces,
                ),
                AlgorithmMixingComposition(
                    order_code=target_order_code,
                    product_code=target_product_code,
                    sequence=2,
                    estimated_pieces=target_estimated_pieces,
                ),
            ],
            notification_status=notification_status,
        )

    def _required_context(self, value, field_name: str) -> str:
        field_value = getattr(value, field_name, None)
        if not isinstance(field_value, str) or not field_value.strip():
            self._raise(
                "selected_machine_context_incomplete",
                f"missing or invalid {field_name}",
            )
        return field_value

    def _unique_order(
        self,
        snapshot: AlgorithmSnapshot,
        order_code: str,
        *,
        missing_reason: str,
    ):
        matches = [
            order for order in snapshot.orders if order.order_code == order_code
        ]
        if not matches:
            self._raise(missing_reason, f"order {order_code} was not found")
        if len(matches) > 1:
            self._raise(
                "selected_machine_context_incomplete",
                f"order {order_code} is ambiguous",
            )
        return matches[0]

    def _resolved_product_code(
        self,
        *,
        selected_machine,
        field_name: str,
        order_product_code: str,
    ) -> str:
        if not isinstance(order_product_code, str) or not order_product_code:
            self._raise(
                "selected_machine_context_incomplete",
                f"order has no valid product for {field_name}",
            )
        plan_product_code = getattr(selected_machine, field_name, None)
        if plan_product_code is None:
            return order_product_code
        if plan_product_code != order_product_code:
            self._raise(
                "cutline_plan_product_mismatch",
                f"{field_name} does not match order product",
            )
        return plan_product_code

    def _process_name(
        self,
        *,
        snapshot: AlgorithmSnapshot,
        machine_code: str,
        process_code: str,
    ) -> str:
        matches = [
            machine
            for machine in snapshot.machine_masters
            if machine.machine_code == machine_code
        ]
        if len(matches) != 1:
            self._raise(
                "selected_machine_context_incomplete",
                f"machine master for {machine_code} is not unique",
            )
        machine = matches[0]
        if machine.process_code != process_code or not machine.process_name:
            self._raise(
                "selected_machine_context_incomplete",
                f"process context for {machine_code} is inconsistent",
            )
        return machine.process_name

    def _runtime(self, snapshot: AlgorithmSnapshot, machine_code: str):
        matches = [
            runtime
            for runtime in snapshot.machine_runtimes
            if runtime.machine_code == machine_code
        ]
        if not matches:
            self._raise(
                "machine_runtime_not_found",
                f"runtime for {machine_code} was not found",
            )
        if len(matches) > 1:
            self._raise(
                "machine_runtime_ambiguous",
                f"runtime for {machine_code} is ambiguous",
            )
        return matches[0]

    def _actual_capacity(self, runtime) -> float:
        quantities = (
            runtime.input_quantity_30m,
            runtime.output_quantity_30m,
        )
        if any(not self._is_finite_non_negative(value) for value in quantities):
            self._raise(
                "runtime_quantity_invalid",
                "runtime input/output quantity must be finite and non-negative",
            )
        actual_capacity_per_hour = min(quantities) * 2
        if actual_capacity_per_hour <= 0:
            self._raise(
                "runtime_actual_capacity_unavailable",
                "runtime actual capacity is not positive",
            )
        return actual_capacity_per_hour

    def _process_duration(
        self,
        *,
        snapshot: AlgorithmSnapshot,
        machine_code: str,
        source_product_code: str,
    ) -> float:
        matches = [
            capacity
            for capacity in snapshot.machine_product_capacities
            if capacity.machine_code == machine_code
            and capacity.product_code == source_product_code
        ]
        if not matches:
            self._raise(
                "process_duration_not_found",
                f"process duration for {machine_code}/{source_product_code} was not found",
            )
        if len(matches) > 1:
            self._raise(
                "process_duration_ambiguous",
                f"process duration for {machine_code}/{source_product_code} is ambiguous",
            )
        proc_seconds = matches[0].proc_seconds
        if not self._is_finite_non_negative(proc_seconds):
            self._raise(
                "process_duration_invalid",
                "proc_seconds must be finite and non-negative",
            )
        return proc_seconds

    def _plan_generated_time(self, plan: AlgorithmCutlinePlan) -> datetime:
        generated_time = getattr(plan, "calculation_time", None)
        if generated_time is None:
            generated_time = getattr(plan, "plan_generated_time", None)
        if not isinstance(generated_time, datetime):
            self._raise(
                "selected_machine_context_incomplete",
                "formal plan has no valid generation time",
            )
        return generated_time

    def _failure(
        self,
        *,
        plan: AlgorithmCutlinePlan,
        selected_machine,
        error: MixingTraceCalculationError,
    ) -> AlgorithmMixingTraceFailure:
        plan_id = self._string_or_empty(getattr(plan, "plan_id", None))
        machine_code = self._string_or_empty(
            getattr(selected_machine, "machine_code", None)
        )
        return AlgorithmMixingTraceFailure(
            plan_id=plan_id,
            cutline_event_id=f"CUT-{plan_id}-{machine_code}",
            machine_code=machine_code,
            source_order_code=self._string_or_empty(
                getattr(selected_machine, "source_order_code", None)
            ),
            target_order_code=self._string_or_empty(
                getattr(selected_machine, "target_order_code", None)
            ),
            reason=error.reason,
            message=error.message,
        )

    def _is_finite_non_negative(self, value) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and isfinite(value)
            and value >= 0
        )

    def _string_or_empty(self, value) -> str:
        return value if isinstance(value, str) else ""

    def _raise(self, reason: str, message: str):
        raise MixingTraceCalculationError(reason, message)
