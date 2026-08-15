"""依据当前快照主数据校验并转换后端持久化的 Pending 切线计划。"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from app.adapters.agv_binding_selector import normalize_local_time
from app.core.workshop.machine_workshop_resolver import (
    MachineWorkshopResolutionError,
    MachineWorkshopResolver,
)
from app.core.candidate_machine.product_compatibility import (
    is_source_grade_compatible,
    is_wafer_spec_compatible,
)
from app.schemas.common_schema import (
    AlgorithmBufferMaster,
    AlgorithmBufferProcessRelation,
    AlgorithmConfig,
    AlgorithmMachineMaster,
    AlgorithmOrder,
    AlgorithmProduct,
)
from app.schemas.pending_cutline_schema import (
    BaselineMachineBinding,
    PendingCandidateMachine,
    PendingCutlinePlan,
    PendingCutlinePlanStatus,
)


class PendingCutlinePlanConversionError(ValueError):
    """持久化 Pending 计划与当前静态主数据冲突。"""


class PendingCutlinePlanAdapter:
    """执行关系校验，并深复制类型化的 Pending 计划。"""

    def convert(
        self,
        plans: Iterable[PendingCutlinePlan],
        *,
        snapshot_time: datetime,
        config: AlgorithmConfig,
        machine_by_code: dict[str, AlgorithmMachineMaster],
        order_by_code: dict[str, AlgorithmOrder],
        product_by_code: dict[str, AlgorithmProduct],
        buffer_by_code: dict[str, AlgorithmBufferMaster],
        relation_by_buffer: dict[str, AlgorithmBufferProcessRelation],
        workshop_codes: set[str],
        workshop_resolver: MachineWorkshopResolver,
    ) -> list[PendingCutlinePlan]:
        source = list(plans)
        self._validate_unique_plans(source, snapshot_time=snapshot_time)
        return [
            self._convert_plan(
                plan,
                config=config,
                snapshot_time=snapshot_time,
                machine_by_code=machine_by_code,
                order_by_code=order_by_code,
                product_by_code=product_by_code,
                buffer_by_code=buffer_by_code,
                relation_by_buffer=relation_by_buffer,
                workshop_codes=workshop_codes,
                workshop_resolver=workshop_resolver,
            )
            for plan in source
        ]

    def _validate_unique_plans(
        self,
        plans: list[PendingCutlinePlan],
        *,
        snapshot_time: datetime,
    ) -> None:
        by_id: dict[str, list[PendingCutlinePlan]] = {}
        by_business_key: dict[
            tuple[str, str, str, str, str, str],
            list[PendingCutlinePlan],
        ] = {}
        for plan in plans:
            by_id.setdefault(plan.plan_id, []).append(plan)
            if (
                plan.status
                in {
                    PendingCutlinePlanStatus.PENDING,
                    PendingCutlinePlanStatus.PARTIALLY_CONFIRMED,
                }
                and normalize_local_time(plan.expire_at)
                > normalize_local_time(snapshot_time)
            ):
                key = (
                    plan.warning_type,
                    plan.workshop_code,
                    plan.buffer_code,
                    plan.upstream_process_code,
                    plan.downstream_process_code,
                    plan.monitored_order_code,
                )
                by_business_key.setdefault(key, []).append(plan)
        for plan_id, duplicates in by_id.items():
            if len(duplicates) > 1:
                warning_ids = sorted(plan.warning_id for plan in duplicates)
                raise PendingCutlinePlanConversionError(
                    f"duplicate plan_id={plan_id!r}; conflicting "
                    f"warning_ids={warning_ids!r}"
                )
        for key, duplicates in by_business_key.items():
            if len(duplicates) > 1:
                plan_ids = sorted(plan.plan_id for plan in duplicates)
                raise PendingCutlinePlanConversionError(
                    f"Pending business key={key!r} is duplicated by "
                    f"plans={plan_ids!r}"
                )

    def _convert_plan(
        self,
        plan: PendingCutlinePlan,
        *,
        config: AlgorithmConfig,
        snapshot_time: datetime,
        machine_by_code: dict[str, AlgorithmMachineMaster],
        order_by_code: dict[str, AlgorithmOrder],
        product_by_code: dict[str, AlgorithmProduct],
        buffer_by_code: dict[str, AlgorithmBufferMaster],
        relation_by_buffer: dict[str, AlgorithmBufferProcessRelation],
        workshop_codes: set[str],
        workshop_resolver: MachineWorkshopResolver,
    ) -> PendingCutlinePlan:
        created_at = normalize_local_time(plan.created_at)
        expire_at = normalize_local_time(plan.expire_at)
        warning_time = normalize_local_time(plan.warning_time)
        process_code = plan.process_code or plan.upstream_process_code
        plan = plan.model_copy(update={"process_code": process_code})
        comparable_snapshot_time = normalize_local_time(snapshot_time)
        if created_at > comparable_snapshot_time:
            raise PendingCutlinePlanConversionError(
                f"plan_id={plan.plan_id}: created_at={created_at.isoformat()} "
                "must not be later than snapshot_time="
                f"{comparable_snapshot_time.isoformat()}"
            )
        expected_window = timedelta(
            minutes=config.cutline_confirmation_window_minutes
        )
        actual_window = expire_at - created_at
        if actual_window != expected_window:
            raise PendingCutlinePlanConversionError(
                f"plan_id={plan.plan_id}: confirmation window "
                f"{actual_window.total_seconds() / 60:g} minutes conflicts "
                f"with configured {config.cutline_confirmation_window_minutes:g}"
            )
        if plan.workshop_code not in workshop_codes:
            raise PendingCutlinePlanConversionError(
                f"plan_id={plan.plan_id}: workshop_code "
                f"{plan.workshop_code!r} does not exist"
            )
        warning_relation = self._require_buffer_relation(
            plan_id=plan.plan_id,
            machine_code=None,
            field="buffer_code",
            buffer_code=plan.buffer_code,
            buffer_by_code=buffer_by_code,
            relation_by_buffer=relation_by_buffer,
        )
        self._require_interval(
            plan_id=plan.plan_id,
            machine_code=None,
            field="warning interval",
            relation=warning_relation,
            workshop_code=plan.workshop_code,
            upstream_process_code=plan.upstream_process_code,
            downstream_process_code=plan.downstream_process_code,
        )
        monitored_order, _ = self._require_order_product(
            plan_id=plan.plan_id,
            machine_code=None,
            field="monitored",
            order_code=plan.monitored_order_code,
            product_by_code=product_by_code,
            order_by_code=order_by_code,
        )
        if monitored_order.workshop_code != plan.workshop_code:
            raise PendingCutlinePlanConversionError(
                f"plan_id={plan.plan_id}: monitored order "
                f"{monitored_order.order_code!r} workshop "
                f"{monitored_order.workshop_code!r} conflicts with "
                f"workshop_code={plan.workshop_code!r}"
            )

        expected_direction = (
            "increase" if plan.warning_type == "stockout" else "decrease"
        )
        if plan.expected_delta_direction != expected_direction:
            raise PendingCutlinePlanConversionError(
                f"plan_id={plan.plan_id}: {plan.warning_type} requires "
                f"expected_delta_direction={expected_direction!r}, got "
                f"{plan.expected_delta_direction!r}"
            )

        normalized_baselines: list[BaselineMachineBinding] = []
        baseline_by_machine: dict[str, BaselineMachineBinding] = {}
        for baseline in plan.baseline_machine_bindings:
            normalized = self._validate_baseline(
                plan=plan,
                baseline=baseline,
                created_at=created_at,
                machine_by_code=machine_by_code,
                order_by_code=order_by_code,
                product_by_code=product_by_code,
                workshop_resolver=workshop_resolver,
            )
            normalized_baselines.append(normalized)
            baseline_by_machine[normalized.machine_code] = normalized

        for machine_code in plan.before_machine_codes:
            baseline = baseline_by_machine[machine_code]
            if baseline.order_code != plan.monitored_order_code:
                raise PendingCutlinePlanConversionError(
                    f"plan_id={plan.plan_id}: before_machine_codes contains "
                    f"machine_code={machine_code!r}, whose saved baseline "
                    f"order={baseline.order_code!r} does not equal monitored "
                    f"order={plan.monitored_order_code!r}"
                )

        normalized_candidates = [
            self._validate_candidate(
                plan=plan,
                candidate=candidate,
                baseline_by_machine=baseline_by_machine,
                machine_by_code=machine_by_code,
                order_by_code=order_by_code,
                product_by_code=product_by_code,
                buffer_by_code=buffer_by_code,
                relation_by_buffer=relation_by_buffer,
                workshop_resolver=workshop_resolver,
            )
            for candidate in plan.candidate_machines
        ]
        self._validate_candidate_summaries(plan, normalized_candidates)
        delta = len(normalized_candidates)
        expected_count = (
            plan.before_machine_count + delta
            if plan.warning_type == "stockout"
            else plan.before_machine_count - delta
        )
        if plan.expected_machine_count != expected_count:
            raise PendingCutlinePlanConversionError(
                f"plan_id={plan.plan_id}: expected_machine_count="
                f"{plan.expected_machine_count} conflicts with "
                f"before_machine_count={plan.before_machine_count} and "
                f"candidate_count={delta}; expected={expected_count}"
            )

        return plan.model_copy(
            deep=True,
            update={
                "warning_time": warning_time,
                "created_at": created_at,
                "expire_at": expire_at,
                "process_code": process_code,
                "baseline_machine_bindings": normalized_baselines,
                "candidate_machines": normalized_candidates,
                "before_machine_codes": list(plan.before_machine_codes),
                "confirmed_machine_codes": list(
                    plan.confirmed_machine_codes
                ),
            },
        )

    def _validate_baseline(
        self,
        *,
        plan: PendingCutlinePlan,
        baseline: BaselineMachineBinding,
        created_at: datetime,
        machine_by_code: dict[str, AlgorithmMachineMaster],
        order_by_code: dict[str, AlgorithmOrder],
        product_by_code: dict[str, AlgorithmProduct],
        workshop_resolver: MachineWorkshopResolver,
    ) -> BaselineMachineBinding:
        machine = self._require_machine(
            plan.plan_id, baseline.machine_code, machine_by_code
        )
        workshop_code = self._resolve_machine_workshop(
            plan.plan_id, machine, workshop_resolver
        )
        self._require_equal(
            plan.plan_id,
            machine.machine_code,
            "process_code",
            baseline.process_code,
            machine.process_code,
        )
        self._require_equal(
            plan.plan_id,
            machine.machine_code,
            "process_code output-side scope",
            machine.process_code,
            plan.process_code or plan.upstream_process_code,
        )
        self._require_equal(
            plan.plan_id,
            machine.machine_code,
            "workshop_code",
            baseline.workshop_code,
            workshop_code,
        )
        self._require_equal(
            plan.plan_id,
            machine.machine_code,
            "workshop_code plan scope",
            workshop_code,
            plan.workshop_code,
        )
        order, product = self._require_order_product(
            plan_id=plan.plan_id,
            machine_code=machine.machine_code,
            field="baseline",
            order_code=baseline.order_code,
            product_by_code=product_by_code,
            order_by_code=order_by_code,
        )
        expected = {
            "product_code": product.product_code,
            "product_name": product.product_name,
            "wafer_size": product.wafer_size,
            "source_grade": product.source_grade,
        }
        actual = {
            "product_code": baseline.product_code,
            "product_name": baseline.product_name,
            "wafer_size": baseline.wafer_size,
            "source_grade": baseline.source_grade,
        }
        for field, expected_value in expected.items():
            self._require_equal(
                plan.plan_id,
                machine.machine_code,
                field,
                actual[field],
                expected_value,
            )
        if order.workshop_code != workshop_code:
            raise PendingCutlinePlanConversionError(
                f"plan_id={plan.plan_id}, machine_code={machine.machine_code}: "
                f"baseline order workshop={order.workshop_code!r} conflicts "
                f"with machine workshop={workshop_code!r}"
            )
        observed_at = normalize_local_time(baseline.observed_at)
        if observed_at > created_at:
            raise PendingCutlinePlanConversionError(
                f"plan_id={plan.plan_id}, machine_code={machine.machine_code}: "
                f"observed_at={observed_at.isoformat()} is later than "
                f"created_at={created_at.isoformat()}"
            )
        if (
            baseline.machine_status is not None
            and not baseline.machine_status.strip()
        ):
            raise PendingCutlinePlanConversionError(
                f"plan_id={plan.plan_id}, machine_code={machine.machine_code}: "
                "machine_status must not be blank"
            )
        if not baseline.wafer_spec.strip():
            raise PendingCutlinePlanConversionError(
                f"plan_id={plan.plan_id}, machine_code={machine.machine_code}: "
                "baseline wafer_spec must not be blank"
            )
        return baseline.model_copy(
            deep=True,
            update={"observed_at": observed_at},
        )

    def _validate_candidate(
        self,
        *,
        plan: PendingCutlinePlan,
        candidate: PendingCandidateMachine,
        baseline_by_machine: dict[str, BaselineMachineBinding],
        machine_by_code: dict[str, AlgorithmMachineMaster],
        order_by_code: dict[str, AlgorithmOrder],
        product_by_code: dict[str, AlgorithmProduct],
        buffer_by_code: dict[str, AlgorithmBufferMaster],
        relation_by_buffer: dict[str, AlgorithmBufferProcessRelation],
        workshop_resolver: MachineWorkshopResolver,
    ) -> PendingCandidateMachine:
        baseline = baseline_by_machine.get(candidate.machine_code)
        if baseline is None:
            raise PendingCutlinePlanConversionError(
                f"plan_id={plan.plan_id}: candidate machine_code="
                f"{candidate.machine_code!r} is not in baseline bindings"
            )
        machine = self._require_machine(
            plan.plan_id, candidate.machine_code, machine_by_code
        )
        workshop_code = self._resolve_machine_workshop(
            plan.plan_id, machine, workshop_resolver
        )
        baseline_pairs = (
            (
                "baseline_order_code",
                candidate.baseline_order_code,
                baseline.order_code,
            ),
            (
                "baseline_product_code",
                candidate.baseline_product_code,
                baseline.product_code,
            ),
            (
                "baseline_product_name",
                candidate.baseline_product_name,
                baseline.product_name,
            ),
            (
                "baseline_wafer_size",
                candidate.baseline_wafer_size,
                baseline.wafer_size,
            ),
            (
                "baseline_wafer_spec",
                candidate.baseline_wafer_spec,
                baseline.wafer_spec,
            ),
            (
                "baseline_source_grade",
                candidate.baseline_source_grade,
                baseline.source_grade,
            ),
            ("process_code", candidate.process_code, machine.process_code),
            ("workshop_code", candidate.workshop_code, workshop_code),
        )
        for field, actual, expected in baseline_pairs:
            self._require_equal(
                plan.plan_id, machine.machine_code, field, actual, expected
            )
        self._require_equal(
            plan.plan_id,
            machine.machine_code,
            "process_code output-side scope",
            machine.process_code,
            plan.process_code or plan.upstream_process_code,
        )
        self._require_equal(
            plan.plan_id,
            machine.machine_code,
            "workshop_code plan scope",
            workshop_code,
            plan.workshop_code,
        )

        target_order, target_product = self._require_order_product(
            plan_id=plan.plan_id,
            machine_code=machine.machine_code,
            field="expected target",
            order_code=candidate.expected_target_order_code,
            product_by_code=product_by_code,
            order_by_code=order_by_code,
        )
        target_pairs = (
            (
                "expected_target_product_code",
                candidate.expected_target_product_code,
                target_product.product_code,
            ),
            (
                "expected_target_product_name",
                candidate.expected_target_product_name,
                target_product.product_name,
            ),
            (
                "expected_target_wafer_size",
                candidate.expected_target_wafer_size,
                target_product.wafer_size,
            ),
            (
                "expected_target_source_grade",
                candidate.expected_target_source_grade,
                target_product.source_grade,
            ),
        )
        for field, actual, expected in target_pairs:
            self._require_equal(
                plan.plan_id, machine.machine_code, field, actual, expected
            )
        if not candidate.expected_target_wafer_spec.strip():
            raise PendingCutlinePlanConversionError(
                f"plan_id={plan.plan_id}, machine_code={machine.machine_code}: "
                "expected target wafer_spec must not be blank"
            )
        if (
            candidate.baseline_wafer_size
            != candidate.expected_target_wafer_size
        ):
            raise PendingCutlinePlanConversionError(
                f"plan_id={plan.plan_id}, machine_code={machine.machine_code}: "
                f"candidate wafer size {candidate.baseline_wafer_size!r} is "
                "incompatible with target wafer size "
                f"{candidate.expected_target_wafer_size!r}"
            )
        if not is_wafer_spec_compatible(
            current_wafer_spec=candidate.baseline_wafer_spec,
            target_wafer_spec=candidate.expected_target_wafer_spec,
            workshop_code=workshop_code,
            process_name=machine.process_name,
        ):
            raise PendingCutlinePlanConversionError(
                f"plan_id={plan.plan_id}, machine_code={machine.machine_code}: "
                f"candidate wafer spec {candidate.baseline_wafer_spec!r} is "
                "incompatible with target wafer spec "
                f"{candidate.expected_target_wafer_spec!r}"
            )
        if not is_source_grade_compatible(
            current_source_grade=candidate.baseline_source_grade,
            target_source_grade=candidate.expected_target_source_grade,
        ):
            raise PendingCutlinePlanConversionError(
                f"plan_id={plan.plan_id}, machine_code={machine.machine_code}: "
                f"candidate source grade {candidate.baseline_source_grade!r} "
                "is incompatible with target source grade "
                f"{candidate.expected_target_source_grade!r}"
            )
        if target_order.workshop_code != workshop_code:
            raise PendingCutlinePlanConversionError(
                f"plan_id={plan.plan_id}, machine_code={machine.machine_code}: "
                f"expected target order workshop={target_order.workshop_code!r} "
                f"conflicts with machine workshop={workshop_code!r}"
            )
        target_relation = self._require_buffer_relation(
            plan_id=plan.plan_id,
            machine_code=machine.machine_code,
            field="target_buffer_code",
            buffer_code=candidate.target_buffer_code,
            buffer_by_code=buffer_by_code,
            relation_by_buffer=relation_by_buffer,
        )
        self._require_interval(
            plan_id=plan.plan_id,
            machine_code=machine.machine_code,
            field="target interval",
            relation=target_relation,
            workshop_code=candidate.workshop_code,
            upstream_process_code=candidate.target_upstream_process_code,
            downstream_process_code=candidate.target_downstream_process_code,
        )
        if candidate.source_buffer_code is not None:
            source_relation = self._require_buffer_relation(
                plan_id=plan.plan_id,
                machine_code=machine.machine_code,
                field="source_buffer_code",
                buffer_code=candidate.source_buffer_code,
                buffer_by_code=buffer_by_code,
                relation_by_buffer=relation_by_buffer,
            )
            if (
                source_relation.workshop_code != plan.workshop_code
                or source_relation.upstream_process_code
                != plan.upstream_process_code
            ):
                raise PendingCutlinePlanConversionError(
                    f"plan_id={plan.plan_id}, machine_code={machine.machine_code}: "
                    f"source_buffer_code={candidate.source_buffer_code!r} "
                    "must belong to the plan workshop/output-side process"
                )

        if plan.warning_type == "stockout":
            if baseline.order_code == plan.monitored_order_code:
                raise PendingCutlinePlanConversionError(
                    f"plan_id={plan.plan_id}, machine_code={machine.machine_code}: "
                    "stockout candidate baseline must differ from monitored "
                    f"order {plan.monitored_order_code!r}"
                )
            if target_order.order_code != plan.monitored_order_code:
                raise PendingCutlinePlanConversionError(
                    f"plan_id={plan.plan_id}, machine_code={machine.machine_code}: "
                    f"stockout target={target_order.order_code!r} must equal "
                    f"monitored order {plan.monitored_order_code!r}"
                )
            if (
                candidate.target_buffer_code != plan.buffer_code
                or candidate.target_upstream_process_code
                != plan.upstream_process_code
                or candidate.target_downstream_process_code
                != plan.downstream_process_code
            ):
                raise PendingCutlinePlanConversionError(
                    f"plan_id={plan.plan_id}, machine_code={machine.machine_code}: "
                    "stockout target interval must equal warning interval"
                )
        else:
            if machine.machine_code not in plan.before_machine_codes:
                raise PendingCutlinePlanConversionError(
                    f"plan_id={plan.plan_id}, machine_code={machine.machine_code}: "
                    "overflow candidate must be present in "
                    "before_machine_codes at warning time"
                )
            if baseline.order_code != plan.monitored_order_code:
                raise PendingCutlinePlanConversionError(
                    f"plan_id={plan.plan_id}, machine_code={machine.machine_code}: "
                    "overflow candidate baseline must equal monitored order "
                    f"{plan.monitored_order_code!r}"
                )
            if target_order.order_code == plan.monitored_order_code:
                raise PendingCutlinePlanConversionError(
                    f"plan_id={plan.plan_id}, machine_code={machine.machine_code}: "
                    "overflow target must be different from monitored order"
                )
            if candidate.source_buffer_code != plan.buffer_code:
                raise PendingCutlinePlanConversionError(
                    f"plan_id={plan.plan_id}, machine_code={machine.machine_code}: "
                    "overflow source_buffer_code must equal warning buffer "
                    f"{plan.buffer_code!r}"
                )
            if candidate.target_buffer_code == plan.buffer_code:
                raise PendingCutlinePlanConversionError(
                    f"plan_id={plan.plan_id}, machine_code={machine.machine_code}: "
                    "overflow target_buffer_code must differ from warning buffer"
                )
            if (
                candidate.target_upstream_process_code
                != plan.upstream_process_code
            ):
                raise PendingCutlinePlanConversionError(
                    f"plan_id={plan.plan_id}, machine_code={machine.machine_code}: "
                    "overflow target interval must use the warning output-side "
                    f"process {plan.upstream_process_code!r}"
                )
        return candidate.model_copy(deep=True)

    def _validate_candidate_summaries(
        self,
        plan: PendingCutlinePlan,
        candidates: list[PendingCandidateMachine],
    ) -> None:
        summaries = (
            (
                "source_order_code",
                plan.source_order_code,
                {item.baseline_order_code for item in candidates},
            ),
            (
                "target_order_code",
                plan.target_order_code,
                {item.expected_target_order_code for item in candidates},
            ),
            (
                "source_product_code",
                plan.source_product_code,
                {item.baseline_product_code for item in candidates},
            ),
            (
                "target_product_code",
                plan.target_product_code,
                {item.expected_target_product_code for item in candidates},
            ),
        )
        for field, actual, candidate_values in summaries:
            if actual is None:
                continue
            if candidate_values != {actual}:
                raise PendingCutlinePlanConversionError(
                    f"plan_id={plan.plan_id}: {field}={actual!r} conflicts "
                    f"with unique candidate values={sorted(candidate_values)!r}"
                )

    def _require_machine(
        self,
        plan_id: str,
        machine_code: str,
        machine_by_code: dict[str, AlgorithmMachineMaster],
    ) -> AlgorithmMachineMaster:
        machine = machine_by_code.get(machine_code)
        if machine is None:
            raise PendingCutlinePlanConversionError(
                f"plan_id={plan_id}: machine_code={machine_code!r} "
                "does not exist as a standard machine code"
            )
        return machine

    def _resolve_machine_workshop(
        self,
        plan_id: str,
        machine: AlgorithmMachineMaster,
        resolver: MachineWorkshopResolver,
    ) -> str:
        try:
            return resolver.resolve_machine_workshop(machine)
        except MachineWorkshopResolutionError as exc:
            raise PendingCutlinePlanConversionError(
                f"plan_id={plan_id}, machine_code={machine.machine_code}: {exc}"
            ) from exc

    def _require_order_product(
        self,
        *,
        plan_id: str,
        machine_code: str | None,
        field: str,
        order_code: str,
        order_by_code: dict[str, AlgorithmOrder],
        product_by_code: dict[str, AlgorithmProduct],
    ) -> tuple[AlgorithmOrder, AlgorithmProduct]:
        location = f"plan_id={plan_id}"
        if machine_code is not None:
            location += f", machine_code={machine_code}"
        order = order_by_code.get(order_code)
        if order is None:
            raise PendingCutlinePlanConversionError(
                f"{location}: {field} order_code={order_code!r} does not exist"
            )
        product = product_by_code.get(order.product_code)
        if product is None:
            raise PendingCutlinePlanConversionError(
                f"{location}: {field} order {order_code!r} product_code="
                f"{order.product_code!r} does not exist"
            )
        if order.product_name != product.product_name:
            raise PendingCutlinePlanConversionError(
                f"{location}: {field} order {order_code!r} product_name="
                f"{order.product_name!r} conflicts with product catalog "
                f"{product.product_name!r}"
            )
        return order, product

    def _require_buffer_relation(
        self,
        *,
        plan_id: str,
        machine_code: str | None,
        field: str,
        buffer_code: str,
        buffer_by_code: dict[str, AlgorithmBufferMaster],
        relation_by_buffer: dict[str, AlgorithmBufferProcessRelation],
    ) -> AlgorithmBufferProcessRelation:
        location = f"plan_id={plan_id}"
        if machine_code is not None:
            location += f", machine_code={machine_code}"
        if buffer_code not in buffer_by_code:
            raise PendingCutlinePlanConversionError(
                f"{location}: {field}={buffer_code!r} buffer does not exist"
            )
        relation = relation_by_buffer.get(buffer_code)
        if relation is None:
            raise PendingCutlinePlanConversionError(
                f"{location}: {field}={buffer_code!r} has no process relation"
            )
        return relation

    def _require_interval(
        self,
        *,
        plan_id: str,
        machine_code: str | None,
        field: str,
        relation: AlgorithmBufferProcessRelation,
        workshop_code: str,
        upstream_process_code: str,
        downstream_process_code: str,
    ) -> None:
        expected = (
            relation.workshop_code,
            relation.upstream_process_code,
            relation.downstream_process_code,
        )
        actual = (
            workshop_code,
            upstream_process_code,
            downstream_process_code,
        )
        if actual != expected:
            location = f"plan_id={plan_id}"
            if machine_code is not None:
                location += f", machine_code={machine_code}"
            raise PendingCutlinePlanConversionError(
                f"{location}: {field}={actual!r} conflicts with Buffer "
                f"{relation.buffer_code!r} authoritative interval={expected!r}"
            )

    def _require_equal(
        self,
        plan_id: str,
        machine_code: str,
        field: str,
        actual: str,
        expected: str,
    ) -> None:
        if actual != expected:
            raise PendingCutlinePlanConversionError(
                f"plan_id={plan_id}, machine_code={machine_code}: "
                f"{field}={actual!r} conflicts with authoritative/baseline "
                f"value={expected!r}"
            )
