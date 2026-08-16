"""把自动切线决策转换为首轮可持久化的 Pending 计划。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import timedelta

from pydantic import ValidationError

from app.core.workshop.machine_workshop_resolver import (
    MachineWorkshopResolutionError,
    MachineWorkshopResolver,
)
from app.schemas.common_schema import (
    AlgorithmBufferProcessRelation,
    AlgorithmAgvRelation,
    AlgorithmMachineMaster,
    AlgorithmMachineRuntime,
    AlgorithmOrder,
    AlgorithmProduct,
)
from app.schemas.pending_cutline_schema import (
    BaselineMachineBinding,
    PendingCandidateMachine,
    PendingCutlinePlan,
    PendingCutlinePlanStatus,
)
from app.schemas.request_schema import AlgorithmSnapshot
from app.schemas.result_schema import (
    AlgorithmCutlineDecisionResult,
    AlgorithmOverflowCutlinePlan,
    AlgorithmSelectedMachineEvaluation,
    AlgorithmStockoutCutlinePlan,
)


class PendingCutlinePlanCreationError(ValueError):
    """自动计划无法投影为完整的 Pending 状态。"""


class PendingCutlinePlanFactory:
    """记录确定性的当前快照状态，供后续轮次确认切线。"""

    def create(
        self,
        snapshot: AlgorithmSnapshot,
        decision: AlgorithmCutlineDecisionResult,
    ) -> PendingCutlinePlan | None:
        """根据当前快照和业务规则执行【create】计算，返回类型标注所声明的结果。"""
        plan = decision.plan
        if plan is None:
            return None
        if not plan.selected_machines:
            raise PendingCutlinePlanCreationError(
                f"plan_id={plan.plan_id}: selected_machines must not be empty"
            )

        process_code = self._resolve_selected_process(plan.selected_machines)
        workshop_code = plan.workshop_code.strip()
        if not workshop_code:
            raise PendingCutlinePlanCreationError(
                f"plan_id={plan.plan_id}: workshop_code must not be blank"
            )

        orders, products = self._build_order_product_indexes(snapshot)
        warning_relation = self._resolve_buffer_relation(
            snapshot,
            plan.buffer_code,
        )
        self._require_interval(
            context=f"plan_id={plan.plan_id} warning Buffer {plan.buffer_code}",
            relation=warning_relation,
            workshop_code=workshop_code,
            process_code=process_code,
            upstream_process_code=plan.upstream_process_code,
            downstream_process_code=plan.downstream_process_code,
        )

        monitored_order_code = (
            plan.order_code
            if isinstance(plan, AlgorithmStockoutCutlinePlan)
            else plan.source_order_code
        )
        monitored_order, _ = self._resolve_order_product(
            monitored_order_code,
            orders,
            products,
            context=f"plan_id={plan.plan_id} monitored order",
        )
        if monitored_order.workshop_code.strip() != workshop_code:
            raise PendingCutlinePlanCreationError(
                f"plan_id={plan.plan_id}: monitored order "
                f"{monitored_order_code!r} workshop "
                f"{monitored_order.workshop_code!r} does not match plan "
                f"workshop {workshop_code!r}"
            )

        scope_masters = self._resolve_scope_masters(
            snapshot,
            workshop_code=workshop_code,
            process_code=process_code,
        )
        # 保存计划窗口开始时的机台订单基线，后续确认只比较真实绑定变化。
        baselines, runtime_by_machine = self._capture_baselines(
            snapshot,
            scope_masters=scope_masters,
            workshop_code=workshop_code,
            process_code=process_code,
            orders=orders,
            products=products,
        )
        baseline_by_machine = {
            item.machine_code: item for item in baselines
        }

        candidates = self._create_candidates(
            snapshot,
            plan=plan,
            workshop_code=workshop_code,
            process_code=process_code,
            baseline_by_machine=baseline_by_machine,
            orders=orders,
            products=products,
        )
        candidate_codes = [item.machine_code for item in candidates]
        if len(candidate_codes) != len(set(candidate_codes)):
            duplicate = self._first_duplicate(candidate_codes)
            raise PendingCutlinePlanCreationError(
                f"plan_id={plan.plan_id}: selected_machines contains "
                f"duplicate standard machine_code {duplicate!r}"
            )

        if isinstance(plan, AlgorithmStockoutCutlinePlan):
            before_order_codes = {monitored_order_code}
        else:
            # 动态 source overflow 中，每台候选机可能来自不同订单，
            # 因此 before scope 必须使用各候选自己的 baseline。
            before_order_codes = {
                item.baseline_order_code for item in candidates
            }
        before_codes = sorted(
            machine_code
            for machine_code, runtime in runtime_by_machine.items()
            if runtime.status == "running"
            and runtime.current_order_code in before_order_codes
        )
        before_count = len(before_codes)
        candidate_count = len(candidate_codes)
        self._validate_candidate_direction(
            plan=plan,
            candidates=candidates,
            before_codes=before_codes,
            monitored_order_code=monitored_order_code,
        )
        # stockout 预期目标机台数增加，overflow 预期来源机台数减少；
        # 状态机本身仍沿用 Pending -> Confirmed -> Active。
        if isinstance(plan, AlgorithmStockoutCutlinePlan):
            expected_count = before_count + candidate_count
            direction = "increase"
            warning_id = (
                f"stockout:{plan.calculation_time.isoformat()}:"
                f"{plan.buffer_code}:{plan.order_code}"
            )
            warning_type = "stockout"
        else:
            expected_count = before_count - candidate_count
            if expected_count < 0:
                raise PendingCutlinePlanCreationError(
                    f"plan_id={plan.plan_id}: overflow expected machine "
                    f"count {expected_count} is negative; before={before_count}, "
                    f"candidates={candidate_count}"
                )
            direction = "decrease"
            warning_id = (
                f"overflow:{plan.calculation_time.isoformat()}:"
                f"{plan.buffer_code}"
            )
            warning_type = "overflow"

        created_at = snapshot.current_time
        expire_at = created_at + timedelta(
            minutes=snapshot.config.cutline_confirmation_window_minutes
        )
        try:
            return PendingCutlinePlan(
                plan_id=plan.plan_id,
                warning_id=warning_id,
                warning_type=warning_type,
                warning_time=plan.calculation_time,
                created_at=created_at,
                expire_at=expire_at,
                status=PendingCutlinePlanStatus.PENDING,
                workshop_code=workshop_code,
                buffer_code=plan.buffer_code,
                upstream_process_code=warning_relation.upstream_process_code,
                downstream_process_code=(
                    warning_relation.downstream_process_code
                ),
                monitored_order_code=monitored_order_code,
                process_code=process_code,
                source_order_code=self._single_or_none(
                    item.baseline_order_code for item in candidates
                ),
                target_order_code=self._single_or_none(
                    item.expected_target_order_code for item in candidates
                ),
                source_product_code=self._single_or_none(
                    item.baseline_product_code for item in candidates
                ),
                target_product_code=self._single_or_none(
                    item.expected_target_product_code for item in candidates
                ),
                before_machine_count=before_count,
                before_machine_codes=before_codes,
                expected_machine_count=expected_count,
                expected_delta_direction=direction,
                candidate_machines=candidates,
                candidate_machine_codes=candidate_codes,
                baseline_machine_bindings=baselines,
                confirmed_machine_codes=[],
            )
        except ValidationError as exc:
            raise PendingCutlinePlanCreationError(
                f"plan_id={plan.plan_id}: invalid Pending plan: {exc}"
            ) from exc

    def _build_order_product_indexes(
        self,
        snapshot: AlgorithmSnapshot,
    ) -> tuple[dict[str, AlgorithmOrder], dict[str, AlgorithmProduct]]:
        """根据当前快照和业务规则执行【_build_order_product_indexes】计算，返回类型标注所声明的结果。"""
        products: dict[str, AlgorithmProduct] = {}
        product_code_by_name: dict[str, str] = {}
        for product in snapshot.products:
            code = product.product_code.strip()
            name = product.product_name.strip()
            if not code or not name:
                raise PendingCutlinePlanCreationError(
                    "snapshot product_code and product_name must not be blank"
                )
            if code in products:
                raise PendingCutlinePlanCreationError(
                    f"snapshot product_code {code!r} is not unique"
                )
            existing_code = product_code_by_name.get(name)
            if existing_code is not None:
                raise PendingCutlinePlanCreationError(
                    f"snapshot product_name {name!r} maps to multiple products: "
                    f"{existing_code!r}, {code!r}"
                )
            products[code] = product
            product_code_by_name[name] = code

        orders: dict[str, AlgorithmOrder] = {}
        for order in snapshot.orders:
            code = order.order_code.strip()
            if not code:
                raise PendingCutlinePlanCreationError(
                    "snapshot order_code must not be blank"
                )
            if code in orders:
                raise PendingCutlinePlanCreationError(
                    f"snapshot order_code {code!r} is not unique"
                )
            product = products.get(order.product_code.strip())
            if product is None:
                raise PendingCutlinePlanCreationError(
                    f"snapshot order {code!r} product_code "
                    f"{order.product_code!r} has no unique product"
                )
            if order.product_name.strip() != product.product_name.strip():
                raise PendingCutlinePlanCreationError(
                    f"snapshot order {code!r} product_name "
                    f"{order.product_name!r} conflicts with product "
                    f"{product.product_name!r}"
                )
            orders[code] = order
        return orders, products

    def _resolve_selected_process(
        self,
        selected_machines: list[AlgorithmSelectedMachineEvaluation],
    ) -> str:
        """根据当前快照和业务规则执行【_resolve_selected_process】计算，返回类型标注所声明的结果。"""
        process_codes = {
            item.process_code.strip() for item in selected_machines
        }
        if "" in process_codes:
            raise PendingCutlinePlanCreationError(
                "selected_machines process_code must not be blank"
            )
        if len(process_codes) != 1:
            raise PendingCutlinePlanCreationError(
                "selected_machines process_code must resolve uniquely; got "
                f"{sorted(process_codes)}"
            )
        return next(iter(process_codes))

    def _resolve_scope_masters(
        self,
        snapshot: AlgorithmSnapshot,
        *,
        workshop_code: str,
        process_code: str,
    ) -> list[AlgorithmMachineMaster]:
        """根据当前快照和业务规则执行【_resolve_scope_masters】计算，返回类型标注所声明的结果。"""
        masters_by_code: dict[str, AlgorithmMachineMaster] = {}
        for master in snapshot.machine_masters:
            code = master.machine_code.strip()
            if not code:
                raise PendingCutlinePlanCreationError(
                    "snapshot machine master machine_code must not be blank"
                )
            if code in masters_by_code:
                raise PendingCutlinePlanCreationError(
                    f"machine master {code!r} is not unique"
                )
            masters_by_code[code] = master

        resolver = MachineWorkshopResolver(snapshot.process_routes)
        scoped: list[AlgorithmMachineMaster] = []
        for master in masters_by_code.values():
            if master.process_code.strip() != process_code:
                continue
            try:
                resolved_workshop = resolver.resolve_machine_workshop(master)
            except MachineWorkshopResolutionError as exc:
                raise PendingCutlinePlanCreationError(str(exc)) from exc
            if resolved_workshop == workshop_code:
                scoped.append(master)
        if not scoped:
            raise PendingCutlinePlanCreationError(
                f"no machine masters found for workshop {workshop_code!r} "
                f"and process {process_code!r}"
            )
        return sorted(scoped, key=lambda item: item.machine_code.strip())

    def _capture_baselines(
        self,
        snapshot: AlgorithmSnapshot,
        *,
        scope_masters: list[AlgorithmMachineMaster],
        workshop_code: str,
        process_code: str,
        orders: dict[str, AlgorithmOrder],
        products: dict[str, AlgorithmProduct],
    ) -> tuple[
        list[BaselineMachineBinding],
        dict[str, AlgorithmMachineRuntime],
    ]:
        """内部辅助步骤【_capture_baselines】，为上层业务流程提供数据处理或共用判断。"""
        runtimes_by_machine: dict[str, list[AlgorithmMachineRuntime]] = (
            defaultdict(list)
        )
        for runtime in snapshot.machine_runtimes:
            runtimes_by_machine[runtime.machine_code.strip()].append(runtime)
        agv_by_machine: dict[str, list[AlgorithmAgvRelation]] = defaultdict(
            list
        )
        for relation in snapshot.agv_relations:
            agv_by_machine[relation.machine_code.strip()].append(relation)

        baselines: list[BaselineMachineBinding] = []
        runtime_by_machine: dict[str, AlgorithmMachineRuntime] = {}
        for master in scope_masters:
            machine_code = master.machine_code.strip()
            runtimes = runtimes_by_machine.get(machine_code, [])
            if len(runtimes) != 1:
                raise PendingCutlinePlanCreationError(
                    f"machine {machine_code!r} requires exactly one runtime; "
                    f"found {len(runtimes)}"
                )
            bindings = agv_by_machine.get(machine_code, [])
            if len(bindings) != 1:
                raise PendingCutlinePlanCreationError(
                    f"machine {machine_code!r} requires exactly one current "
                    f"AGV binding; found {len(bindings)}"
                )
            runtime = runtimes[0]
            binding = bindings[0]
            order, product = self._resolve_order_product(
                binding.order_code,
                orders,
                products,
                context=f"machine {machine_code!r} AGV binding",
            )
            if (
                binding.product_code.strip() != product.product_code.strip()
                or binding.product_name.strip() != product.product_name.strip()
            ):
                raise PendingCutlinePlanCreationError(
                    f"machine {machine_code!r} AGV binding product identity "
                    f"does not match order {order.order_code!r}"
                )
            if runtime.current_order_code != order.order_code:
                raise PendingCutlinePlanCreationError(
                    f"machine {machine_code!r} runtime current_order_code "
                    f"{runtime.current_order_code!r} conflicts with AGV "
                    f"baseline {order.order_code!r}"
                )
            try:
                observed_after_creation = (
                    binding.binding_time > snapshot.current_time
                )
            except TypeError as exc:
                raise PendingCutlinePlanCreationError(
                    f"machine {machine_code!r} AGV binding_time timezone "
                    "awareness conflicts with snapshot.current_time"
                ) from exc
            if observed_after_creation:
                raise PendingCutlinePlanCreationError(
                    f"machine {machine_code!r} AGV binding observed_at "
                    f"{binding.binding_time.isoformat()} is after created_at "
                    f"{snapshot.current_time.isoformat()}"
                )
            if not binding.wafer_spec.strip():
                raise PendingCutlinePlanCreationError(
                    f"machine {machine_code!r} AGV wafer_spec must not be blank"
                )
            baselines.append(
                BaselineMachineBinding(
                    machine_code=machine_code,
                    order_code=order.order_code.strip(),
                    product_code=product.product_code.strip(),
                    product_name=product.product_name.strip(),
                    wafer_size=product.wafer_size,
                    wafer_spec=binding.wafer_spec,
                    source_grade=product.source_grade,
                    process_code=process_code,
                    workshop_code=workshop_code,
                    machine_status=runtime.status,
                    observed_at=binding.binding_time,
                )
            )
            runtime_by_machine[machine_code] = runtime
        return baselines, runtime_by_machine

    def _create_candidates(
        self,
        snapshot: AlgorithmSnapshot,
        *,
        plan: AlgorithmStockoutCutlinePlan | AlgorithmOverflowCutlinePlan,
        workshop_code: str,
        process_code: str,
        baseline_by_machine: dict[str, BaselineMachineBinding],
        orders: dict[str, AlgorithmOrder],
        products: dict[str, AlgorithmProduct],
    ) -> list[PendingCandidateMachine]:
        """根据当前快照和业务规则执行【_create_candidates】计算，返回类型标注所声明的结果。"""
        candidates: list[PendingCandidateMachine] = []
        for selected in plan.selected_machines:
            machine_code = selected.machine_code.strip()
            if selected.workshop_code.strip() != workshop_code:
                raise PendingCutlinePlanCreationError(
                    f"candidate machine {machine_code!r} workshop "
                    f"{selected.workshop_code!r} does not match plan "
                    f"workshop {workshop_code!r}"
                )
            if selected.process_code.strip() != process_code:
                raise PendingCutlinePlanCreationError(
                    f"candidate machine {machine_code!r} process "
                    f"{selected.process_code!r} does not match selected "
                    f"process {process_code!r}"
                )
            baseline = baseline_by_machine.get(machine_code)
            if baseline is None:
                raise PendingCutlinePlanCreationError(
                    f"candidate machine {machine_code!r} is outside workshop "
                    f"{workshop_code!r} process {process_code!r} baseline scope"
                )
            source_order, source_product = self._resolve_order_product(
                selected.source_order_code,
                orders,
                products,
                context=f"candidate machine {machine_code!r} source",
            )
            target_order, target_product = self._resolve_order_product(
                selected.target_order_code,
                orders,
                products,
                context=f"candidate machine {machine_code!r} target",
            )
            if selected.source_order_code.strip() != baseline.order_code:
                raise PendingCutlinePlanCreationError(
                    f"candidate machine {machine_code!r} source_order_code "
                    f"{selected.source_order_code!r} conflicts with AGV "
                    f"baseline {baseline.order_code!r}"
                )
            if selected.source_wafer_spec != baseline.wafer_spec:
                raise PendingCutlinePlanCreationError(
                    f"candidate machine {machine_code!r} source_wafer_spec "
                    f"{selected.source_wafer_spec!r} conflicts with AGV "
                    f"baseline {baseline.wafer_spec!r}"
                )
            if source_order.workshop_code.strip() != workshop_code:
                raise PendingCutlinePlanCreationError(
                    f"candidate machine {machine_code!r} source order "
                    f"{source_order.order_code!r} is outside workshop "
                    f"{workshop_code!r}"
                )
            if target_order.workshop_code.strip() != workshop_code:
                raise PendingCutlinePlanCreationError(
                    f"candidate machine {machine_code!r} target order "
                    f"{target_order.order_code!r} is outside workshop "
                    f"{workshop_code!r}"
                )
            if (
                selected.wafer_size != source_product.wafer_size
                or selected.wafer_size != target_product.wafer_size
            ):
                raise PendingCutlinePlanCreationError(
                    f"candidate machine {machine_code!r} wafer_size "
                    f"{selected.wafer_size!r} conflicts with snapshot products"
                )

            source_relation = self._resolve_buffer_relation(
                snapshot,
                selected.source_buffer_code,
            )
            self._require_interval_scope(
                context=(
                    f"candidate machine {machine_code!r} source Buffer "
                    f"{selected.source_buffer_code}"
                ),
                relation=source_relation,
                workshop_code=workshop_code,
                process_code=process_code,
            )
            target_relation = self._resolve_buffer_relation(
                snapshot,
                selected.target_buffer_code,
            )
            self._require_interval_scope(
                context=(
                    f"candidate machine {machine_code!r} target Buffer "
                    f"{selected.target_buffer_code}"
                ),
                relation=target_relation,
                workshop_code=workshop_code,
                process_code=process_code,
            )
            candidates.append(
                PendingCandidateMachine(
                    machine_code=machine_code,
                    baseline_order_code=baseline.order_code,
                    baseline_product_code=baseline.product_code,
                    baseline_product_name=baseline.product_name,
                    baseline_wafer_size=baseline.wafer_size,
                    baseline_wafer_spec=baseline.wafer_spec,
                    baseline_source_grade=baseline.source_grade,
                    expected_target_order_code=target_order.order_code.strip(),
                    expected_target_product_code=(
                        target_product.product_code.strip()
                    ),
                    expected_target_product_name=(
                        target_product.product_name.strip()
                    ),
                    expected_target_wafer_size=target_product.wafer_size,
                    expected_target_wafer_spec=selected.target_wafer_spec,
                    expected_target_source_grade=target_product.source_grade,
                    process_code=process_code,
                    workshop_code=workshop_code,
                    source_buffer_code=selected.source_buffer_code,
                    target_buffer_code=selected.target_buffer_code,
                    target_upstream_process_code=(
                        target_relation.upstream_process_code
                    ),
                    target_downstream_process_code=(
                        target_relation.downstream_process_code
                    ),
                )
            )
        return candidates

    def _validate_candidate_direction(
        self,
        *,
        plan: AlgorithmStockoutCutlinePlan | AlgorithmOverflowCutlinePlan,
        candidates: list[PendingCandidateMachine],
        before_codes: list[str],
        monitored_order_code: str,
    ) -> None:
        """校验【_validate_candidate_direction】所需数据和业务前置条件，失败时按本模块契约报告问题。"""
        before_set = set(before_codes)
        for candidate in candidates:
            if isinstance(plan, AlgorithmStockoutCutlinePlan):
                is_valid = (
                    candidate.machine_code not in before_set
                    and candidate.baseline_order_code != monitored_order_code
                    and candidate.expected_target_order_code
                    == monitored_order_code
                )
                direction = "stockout"
                requirement = (
                    "source/baseline must differ from monitored order, "
                    "machine must be outside before_machine_codes, and target "
                    "must equal monitored order"
                )
            else:
                is_valid = (
                    candidate.machine_code in before_set
                    and candidate.expected_target_order_code
                    != candidate.baseline_order_code
                )
                direction = "overflow"
                requirement = (
                    "machine must be in before_machine_codes and target must "
                    "differ from its source/baseline order"
                )
            if not is_valid:
                raise PendingCutlinePlanCreationError(
                    f"plan_id={plan.plan_id}, machine="
                    f"{candidate.machine_code}: invalid {direction} direction; "
                    f"{requirement}; baseline="
                    f"{candidate.baseline_order_code!r}, target="
                    f"{candidate.expected_target_order_code!r}, monitored="
                    f"{monitored_order_code!r}, in_before="
                    f"{candidate.machine_code in before_set}"
                )

    def _resolve_order_product(
        self,
        order_code: str,
        orders: dict[str, AlgorithmOrder],
        products: dict[str, AlgorithmProduct],
        *,
        context: str,
    ) -> tuple[AlgorithmOrder, AlgorithmProduct]:
        """根据当前快照和业务规则执行【_resolve_order_product】计算，返回类型标注所声明的结果。"""
        normalized = order_code.strip()
        order = orders.get(normalized)
        if order is None:
            raise PendingCutlinePlanCreationError(
                f"{context} order_code {order_code!r} has no unique order"
            )
        product = products.get(order.product_code.strip())
        if product is None:
            raise PendingCutlinePlanCreationError(
                f"{context} order {normalized!r} has no unique product"
            )
        return order, product

    def _resolve_buffer_relation(
        self,
        snapshot: AlgorithmSnapshot,
        buffer_code: str,
    ) -> AlgorithmBufferProcessRelation:
        """根据当前快照和业务规则执行【_resolve_buffer_relation】计算，返回类型标注所声明的结果。"""
        normalized = buffer_code.strip()
        masters = [
            item
            for item in snapshot.buffer_masters
            if item.buffer_code.strip() == normalized
        ]
        if len(masters) != 1:
            raise PendingCutlinePlanCreationError(
                f"Buffer {normalized!r} requires exactly one master; "
                f"found {len(masters)}"
            )
        relations = [
            item
            for item in snapshot.buffer_process_relations
            if item.buffer_code.strip() == normalized
        ]
        if not relations:
            raise PendingCutlinePlanCreationError(
                f"Buffer {normalized!r} has no process relation"
            )
        if len(relations) > 1:
            raise PendingCutlinePlanCreationError(
                f"Buffer {normalized!r} maps to multiple process relations"
            )
        return relations[0]

    def _require_interval(
        self,
        *,
        context: str,
        relation: AlgorithmBufferProcessRelation,
        workshop_code: str,
        process_code: str,
        upstream_process_code: str,
        downstream_process_code: str,
    ) -> None:
        """内部辅助步骤【_require_interval】，为上层业务流程提供数据处理或共用判断。"""
        self._require_interval_scope(
            context=context,
            relation=relation,
            workshop_code=workshop_code,
            process_code=process_code,
        )
        if (
            relation.upstream_process_code != upstream_process_code
            or relation.downstream_process_code != downstream_process_code
        ):
            raise PendingCutlinePlanCreationError(
                f"{context} authoritative interval "
                f"{relation.upstream_process_code!r}->"
                f"{relation.downstream_process_code!r} conflicts with plan "
                f"{upstream_process_code!r}->{downstream_process_code!r}"
            )

    def _require_interval_scope(
        self,
        *,
        context: str,
        relation: AlgorithmBufferProcessRelation,
        workshop_code: str,
        process_code: str,
    ) -> None:
        """内部辅助步骤【_require_interval_scope】，为上层业务流程提供数据处理或共用判断。"""
        if relation.workshop_code != workshop_code:
            raise PendingCutlinePlanCreationError(
                f"{context} workshop {relation.workshop_code!r} does not "
                f"match plan workshop {workshop_code!r}"
            )
        if relation.upstream_process_code != process_code:
            raise PendingCutlinePlanCreationError(
                f"{context} upstream process "
                f"{relation.upstream_process_code!r} does not match selected "
                f"process {process_code!r}"
            )

    @staticmethod
    def _single_or_none(values: Iterable[str]) -> str | None:
        """内部辅助步骤【_single_or_none】，为上层业务流程提供数据处理或共用判断。"""
        unique = set(values)
        if len(unique) == 1:
            return next(iter(unique))
        return None

    @staticmethod
    def _first_duplicate(values: list[str]) -> str:
        """内部辅助步骤【_first_duplicate】，为上层业务流程提供数据处理或共用判断。"""
        seen: set[str] = set()
        for value in values:
            if value in seen:
                return value
            seen.add(value)
        raise PendingCutlinePlanCreationError(
            "duplicate lookup was requested without a duplicate"
        )
