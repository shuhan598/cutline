"""校验后端请求的引用完整性，并收集结构化数据问题。"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.adapters.agv_binding_selector import (
    normalize_local_time,
    select_latest_effective_bindings,
)
from app.adapters.backend_request_loader import BackendRequestLoader
from app.adapters.snapshot_reference_index import is_current_order_status
from app.core.workshop.buffer_process_resolver import (
    BufferProcessResolution,
    BufferProcessResolutionError,
    BufferProcessResolver,
)
from app.core.workshop.process_loop_catalog import (
    UnknownProcessNameError,
    normalize_process_name,
    resolve_process_loop,
)
from app.schemas.backend_request_schema import (
    BackendAlgorithmRequest,
    BackendBufferMaster,
    BackendMachineMaster,
    BackendOrder,
    BackendProduct,
)
from app.schemas.request_schema import (
    AgvRelationRequest,
    BufferMasterRequest,
    CutlineAlgorithmRequest,
    MachineMasterRequest,
    OrderRequest,
    ProductRequest,
)
from app.schemas.pending_cutline_schema import (
    PendingCutlinePlan,
    PendingCutlinePlanStatus,
)
from app.utils.buffer_binding import is_multi_value_bound_source_name


class BackendValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    dataset: str
    field: str | None
    record_key: str | None
    message: str


class BackendRequestValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    issues: list[BackendValidationIssue]


_REQUIRED_DATASETS = (
    "machine_realtime",
    "machine_master",
    "machine_process_times",
    "workshops",
    "orders",
    "products",
    "process_routes",
    "buffer_realtime",
    "buffer_master",
)

_REQUIRED_NULLABLE_FIELDS = (
    ("workshops", "workshop_name"),
)

_RELATIONSHIPS = (
    (
        "machine_realtime",
        "machine_code",
        "machine_master",
        "p166_jt_group",
    ),
    ("orders", "product_code", "products", "product_code"),
    ("orders", "workshop_code", "workshops", "workshop_code"),
    (
        "machine_process_times",
        "machine_code",
        "machine_master",
        "machine_code",
    ),
    ("machine_process_times", "product_code", "products", "product_code"),
)

_RECORD_KEY_FIELDS = {
    "machine_realtime": "machine_code",
    "machine_master": "machine_code",
    "machine_process_times": "machine_code",
    "workshops": "workshop_code",
    "lines": "line_code",
    "machine_lines": "machine_code",
    "orders": "order_code",
    "products": "product_code",
    "process_routes": "process_code",
    "buffer_realtime": "buffer_code",
    "buffer_master": "buffer_code",
    "agv_relations": "equipmentid",
    "pending_cutline_plans": "plan_id",
}

CompletenessRequest = BackendAlgorithmRequest | CutlineAlgorithmRequest
ProductRecord = BackendProduct | ProductRequest
OrderRecord = BackendOrder | OrderRequest
BufferMasterRecord = BackendBufferMaster | BufferMasterRequest
MachineMasterRecord = BackendMachineMaster | MachineMasterRequest


class BackendRequestCompletenessValidator:
    """在不修改输入的前提下报告后端请求完整性问题。"""

    def validate(
        self,
        request: CompletenessRequest,
    ) -> BackendRequestValidationResult:
        issues: list[BackendValidationIssue] = []
        # 多值绑定记录仅保留“数据集已提供”的事实，其余完整性检查全部跳过。
        filtered_request = request.model_copy(
            update={
                "buffer_realtime": [
                    record
                    for record in request.buffer_realtime
                    if not is_multi_value_bound_source_name(
                        record.bound_source_name
                    )
                ]
            }
        )
        normalized_agv_relations = [
            AgvRelationRequest.model_validate(record)
            for record in BackendRequestLoader().normalize_agv_relations(
                [
                    relation.model_dump(mode="python")
                    for relation in filtered_request.agv_relations
                ]
            )
        ]
        selected_agv_relations = select_latest_effective_bindings(
            normalized_agv_relations,
            filtered_request.snapshot_meta.snapshot_time,
        )
        self._validate_empty_datasets(request, issues)
        self._validate_required_nullable_fields(filtered_request, issues)
        self._validate_empty_codes(filtered_request, issues)
        self._validate_pending_plans(
            filtered_request.pending_cutline_plans,
            snapshot_time=filtered_request.snapshot_meta.snapshot_time,
            issues=issues,
        )
        self._validate_unique_reference_fields(filtered_request, issues)
        self._validate_references(filtered_request, issues)
        self._validate_order_products(filtered_request, issues)
        self._validate_agv_bindings(
            filtered_request,
            selected_agv_relations,
            issues,
        )
        self._validate_routes(filtered_request, issues)
        self._validate_served_processes(filtered_request, issues)
        self._validate_capacity(filtered_request, issues)
        return BackendRequestValidationResult(valid=not issues, issues=issues)

    def _validate_pending_plans(
        self,
        plans: list[PendingCutlinePlan],
        *,
        snapshot_time: datetime,
        issues: list[BackendValidationIssue],
    ) -> None:
        by_plan_id: dict[str, list[PendingCutlinePlan]] = defaultdict(list)
        by_business_key: dict[
            tuple[str, str, str, str, str, str],
            list[PendingCutlinePlan],
        ] = defaultdict(list)
        for plan in plans:
            by_plan_id[plan.plan_id].append(plan)
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
                by_business_key[key].append(plan)
            self._validate_pending_nested_codes(plan, issues)

        for plan_id, duplicates in by_plan_id.items():
            if len(duplicates) < 2:
                continue
            issues.append(
                self._issue(
                    code="duplicate_key",
                    dataset="pending_cutline_plans",
                    field="plan_id",
                    record_key=plan_id,
                    message=(
                        f"pending_cutline_plans.plan_id={plan_id!r} must be "
                        f"unique; conflicting count={len(duplicates)}"
                    ),
                )
            )
        for key, duplicates in by_business_key.items():
            if len(duplicates) < 2:
                continue
            plan_ids = sorted(plan.plan_id for plan in duplicates)
            issues.append(
                self._issue(
                    code="duplicate_key",
                    dataset="pending_cutline_plans",
                    field="business_key",
                    record_key="|".join(plan_ids),
                    message=(
                        f"pending_cutline_plans business_key={key!r} must be "
                        f"unique; conflicting plan_ids={plan_ids!r}"
                    ),
                )
            )

    def _validate_pending_nested_codes(
        self,
        plan: PendingCutlinePlan,
        issues: list[BackendValidationIssue],
    ) -> None:
        collections = (
            ("before_machine_codes", plan.before_machine_codes),
            ("confirmed_machine_codes", plan.confirmed_machine_codes),
        )
        for field, codes in collections:
            for index, code in enumerate(codes):
                if not code.strip():
                    issues.append(
                        self._issue(
                            code="empty_code",
                            dataset="pending_cutline_plans",
                            field=f"{field}[{index}]",
                            record_key=plan.plan_id,
                            message=(
                                f"pending_cutline_plans.{field}[{index}] "
                                "must not be blank"
                            ),
                        )
                    )
        nested_collections = (
            ("baseline_machine_bindings", plan.baseline_machine_bindings),
            ("candidate_machines", plan.candidate_machines),
        )
        for collection_name, records in nested_collections:
            for index, record in enumerate(records):
                for field in type(record).model_fields:
                    value = getattr(record, field)
                    if (
                        field.endswith("_code")
                        and isinstance(value, str)
                        and not value.strip()
                    ):
                        location = f"{collection_name}[{index}].{field}"
                        issues.append(
                            self._issue(
                                code="empty_code",
                                dataset="pending_cutline_plans",
                                field=location,
                                record_key=plan.plan_id,
                                message=(
                                    f"pending_cutline_plans.{location} "
                                    "must not be blank"
                                ),
                            )
                        )

    def _validate_empty_datasets(
        self,
        request: CompletenessRequest,
        issues: list[BackendValidationIssue],
    ) -> None:
        for dataset in _REQUIRED_DATASETS:
            if not getattr(request, dataset):
                issues.append(
                    self._issue(
                        code="empty_dataset",
                        dataset=dataset,
                        field=None,
                        record_key=None,
                        message=f"{dataset} must not be empty",
                    )
                )

    def _validate_required_nullable_fields(
        self,
        request: CompletenessRequest,
        issues: list[BackendValidationIssue],
    ) -> None:
        for dataset, field in _REQUIRED_NULLABLE_FIELDS:
            for index, record in enumerate(getattr(request, dataset)):
                if getattr(record, field) is None:
                    issues.append(
                        self._issue(
                            code="null_field",
                            dataset=dataset,
                            field=field,
                            record_key=self._record_key(dataset, record, index),
                            message=f"{dataset}.{field} must not be null",
                        )
                    )

    def _validate_empty_codes(
        self,
        request: CompletenessRequest,
        issues: list[BackendValidationIssue],
    ) -> None:
        for dataset in request.__class__.model_fields:
            if dataset == "snapshot_meta":
                continue
            records = getattr(request, dataset)
            if not isinstance(records, list):
                continue
            for index, record in enumerate(records):
                for field, value in record.model_dump().items():
                    if dataset == "process_routes" and field == "loop_code":
                        continue
                    if (
                        field.endswith("_code")
                        and isinstance(value, str)
                        and not value.strip()
                    ):
                        issues.append(
                            self._issue(
                                code="empty_code",
                                dataset=dataset,
                                field=field,
                                record_key=self._record_key(
                                    dataset,
                                    record,
                                    index,
                                ),
                                message=f"{dataset}.{field} must not be empty",
                            )
                        )
                    if field == "served_process_codes":
                        for code_index, process_code in enumerate(value):
                            if not process_code.strip():
                                issues.append(
                                    self._issue(
                                        code="empty_code",
                                        dataset=dataset,
                                        field=(
                                            f"served_process_codes[{code_index}]"
                                        ),
                                        record_key=self._record_key(
                                            dataset,
                                            record,
                                            index,
                                        ),
                                        message=(
                                            "buffer_master.served_process_codes "
                                            "must not contain empty codes"
                                        ),
                                    )
                                )

    def _validate_unique_reference_fields(
        self,
        request: CompletenessRequest,
        issues: list[BackendValidationIssue],
    ) -> None:
        specifications = (
            ("machine_master", "machine_code"),
            ("machine_master", "p166_jt_group"),
            ("products", "product_code"),
            ("products", "product_name"),
            ("orders", "order_code"),
        )
        for dataset, field in specifications:
            grouped: dict[str, list[tuple[int, BaseModel]]] = defaultdict(list)
            for index, record in enumerate(getattr(request, dataset)):
                raw_value = getattr(record, field)
                value = raw_value.strip()
                if not value:
                    issues.append(
                        self._issue(
                            code="empty_value",
                            dataset=dataset,
                            field=field,
                            record_key=self._record_key(dataset, record, index),
                            message=f"{dataset}.{field} must not be blank",
                        )
                    )
                    continue
                if (
                    dataset == "orders"
                    and field == "product_name"
                    and not is_current_order_status(record.order_status)
                ):
                    continue
                grouped[value].append((index, record))

            for value, records in grouped.items():
                if len(records) < 2:
                    continue
                record_keys = [
                    self._record_key(dataset, record, index)
                    for index, record in records
                ]
                issues.append(
                    self._issue(
                        code="duplicate_key",
                        dataset=dataset,
                        field=field,
                        record_key="|".join(record_keys),
                        message=(
                            f"{dataset}.{field}={value!r} must be unique; "
                            f"conflicting records={record_keys}"
                        ),
                    )
                )

    def _validate_order_products(
        self,
        request: CompletenessRequest,
        issues: list[BackendValidationIssue],
    ) -> None:
        products_by_code: dict[str, list[ProductRecord]] = defaultdict(list)
        for product in request.products:
            products_by_code[product.product_code.strip()].append(product)

        for index, order in enumerate(request.orders):
            matches = products_by_code.get(order.product_code.strip(), [])
            if len(matches) != 1:
                continue
            product = matches[0]
            if order.product_name.strip() == product.product_name.strip():
                continue
            issues.append(
                self._issue(
                    code="name_mismatch",
                    dataset="orders",
                    field="product_name",
                    record_key=self._record_key("orders", order, index),
                    message=(
                        f"Order {order.order_code!r} product_code "
                        f"{order.product_code!r} maps to product_name "
                        f"{product.product_name!r}, not "
                        f"{order.product_name!r}"
                    ),
                )
            )

    def _validate_buffer_bindings(
        self,
        request: CompletenessRequest,
        issues: list[BackendValidationIssue],
    ) -> None:
        orders_by_product_name: dict[
            str,
            list[OrderRecord],
        ] = defaultdict(list)
        for order in request.orders:
            if not is_current_order_status(order.order_status):
                continue
            orders_by_product_name[order.product_name.strip()].append(order)

        buffers_by_code: dict[
            str,
            list[tuple[int, BufferMasterRecord]],
        ] = defaultdict(list)
        for index, buffer in enumerate(request.buffer_master):
            buffers_by_code[buffer.buffer_code.strip()].append((index, buffer))

        resolver = BufferProcessResolver(request.process_routes)
        resolutions_by_buffer: dict[str, BufferProcessResolution] = {}
        for buffer_code, matches in buffers_by_code.items():
            if len(matches) != 1:
                continue
            index, buffer = matches[0]
            try:
                resolutions_by_buffer[buffer_code] = resolver.resolve(buffer)
            except BufferProcessResolutionError as exc:
                issues.append(
                    self._issue(
                        code="invalid_reference",
                        dataset="buffer_master",
                        field="served_process_codes",
                        record_key=self._record_key(
                            "buffer_master",
                            buffer,
                            index,
                        ),
                        message=str(exc),
                    )
                )

        for index, realtime in enumerate(request.buffer_realtime):
            record_key = self._record_key("buffer_realtime", realtime, index)
            if is_multi_value_bound_source_name(realtime.bound_source_name):
                # 多值绑定暂不参与校验，整条实时 Buffer 记录由后续环节忽略。
                continue
            product_name = realtime.bound_source_name.strip()
            if not product_name:
                issues.append(
                    self._issue(
                        code="empty_value",
                        dataset="buffer_realtime",
                        field="bound_source_name",
                        record_key=record_key,
                        message=(
                            "buffer_realtime.bound_source_name must not be blank"
                        ),
                    )
                )
                continue

            order_matches = orders_by_product_name.get(product_name, [])
            if len(order_matches) != 1:
                # Buffer 的订单映射由 MainBufferAggregator 按 main 独立解析，
                # 单个异常 main 不应阻断其他健康 main；AGV 和机台订单引用仍严格校验。
                continue

            buffer_code = realtime.buffer_code.strip()
            buffer_matches = buffers_by_code.get(buffer_code, [])
            if len(buffer_matches) != 1:
                continue
            resolution = resolutions_by_buffer.get(buffer_code)
            if resolution is None:
                continue

            order = order_matches[0]
            order_workshop = order.workshop_code.strip()
            buffer_workshop = resolution.workshop_code.strip()
            if buffer_workshop == order_workshop:
                continue
            issues.append(
                self._issue(
                    code="workshop_mismatch",
                    dataset="buffer_realtime",
                    field="bound_source_name",
                    record_key=record_key,
                    message=(
                        f"Buffer {realtime.buffer_code!r} resolves to workshop "
                        f"{buffer_workshop!r}, but current order "
                        f"{order.order_code!r} resolves to workshop "
                        f"{order_workshop!r}"
                    ),
                )
            )

    def _validate_references(
        self,
        request: CompletenessRequest,
        issues: list[BackendValidationIssue],
    ) -> None:
        for source_dataset, source_field, target_dataset, target_field in _RELATIONSHIPS:
            targets = {
                self._normalized_reference_value(value)
                for record in getattr(request, target_dataset)
                if (value := getattr(record, target_field)) not in (None, "")
            }
            for index, record in enumerate(getattr(request, source_dataset)):
                value = getattr(record, source_field)
                if value in (None, ""):
                    continue
                if self._normalized_reference_value(value) not in targets:
                    issues.append(
                        self._issue(
                            code="missing_reference",
                            dataset=source_dataset,
                            field=source_field,
                            record_key=self._record_key(
                                source_dataset,
                                record,
                                index,
                            ),
                            message=(
                                f"{source_dataset}.{source_field}={value!r} "
                                f"was not found in {target_dataset}.{target_field}"
                            ),
                        )
                    )

    def _validate_agv_bindings(
        self,
        request: CompletenessRequest,
        selected_relations: dict[
            str,
            tuple[datetime, list[AgvRelationRequest]],
        ],
        issues: list[BackendValidationIssue],
    ) -> None:
        machines_by_standard_code: dict[
            str,
            list[MachineMasterRecord],
        ] = defaultdict(list)
        machines_by_realtime_code: dict[
            str,
            list[MachineMasterRecord],
        ] = defaultdict(list)
        for machine in request.machine_master:
            machines_by_standard_code[machine.machine_code.strip()].append(
                machine
            )
            machines_by_realtime_code[machine.p166_jt_group.strip()].append(
                machine
            )

        products_by_name: dict[str, list[ProductRecord]] = defaultdict(list)
        for product in request.products:
            products_by_name[product.product_name.strip()].append(product)

        orders_by_product_name: dict[
            str,
            list[OrderRecord],
        ] = defaultdict(list)
        for order in request.orders:
            if not is_current_order_status(order.order_status):
                continue
            orders_by_product_name[order.product_name.strip()].append(order)

        workshops_by_process: dict[str, set[str]] = defaultdict(set)
        for route in request.process_routes:
            workshops_by_process[route.process_code.strip()].add(
                route.workshop_code.strip()
            )

        relation_machine_codes: set[str] = set()

        for raw_machine_code, (_, latest) in selected_relations.items():
            machine_code = raw_machine_code.strip()
            record_key = raw_machine_code or "equipmentid:<empty>"
            has_conflict = False
            for field, attribute in (
                ("equipmentname", "machine_name"),
                ("linename", "product_name"),
                ("lastlinename", "previous_product_name"),
                ("waferspec", "wafer_spec"),
            ):
                values = {getattr(relation, attribute) for relation in latest}
                if len(values) > 1:
                    has_conflict = True
                    rendered_values = sorted(
                        (repr(value) for value in values),
                    )
                    issues.append(
                        self._issue(
                            code="binding_conflict",
                            dataset="agv_relations",
                            field=field,
                            record_key=record_key,
                            message=(
                                f"latest AGV {field} values conflict for "
                                f"machine {raw_machine_code}: "
                                f"{rendered_values}"
                            ),
                        )
                    )
            if has_conflict:
                continue

            relation = latest[0]
            machine_matches = machines_by_standard_code.get(machine_code, [])
            if not machine_code:
                issues.append(
                    self._issue(
                        code="empty_code",
                        dataset="agv_relations",
                        field="equipmentid",
                        record_key=record_key,
                        message="agv_relations.equipmentid must not be empty",
                    )
                )
            elif len(machine_matches) != 1:
                issues.append(
                    self._issue(
                        code="missing_reference"
                        if not machine_matches
                        else "ambiguous_reference",
                        dataset="agv_relations",
                        field="equipmentid",
                        record_key=record_key,
                        message=(
                            "agv_relations.equipmentid="
                            f"{relation.machine_code!r} did not uniquely match "
                            "machine_master.machine_code"
                        ),
                    )
                )

            product_name = relation.product_name.strip()
            product_matches = products_by_name.get(product_name, [])
            order_matches = orders_by_product_name.get(product_name, [])
            if not product_name:
                issues.append(
                    self._issue(
                        code="empty_value",
                        dataset="agv_relations",
                        field="linename",
                        record_key=record_key,
                        message="agv_relations.linename must not be blank",
                    )
                )
            elif len(product_matches) != 1:
                issues.append(
                    self._issue(
                        code="missing_reference"
                        if not product_matches
                        else "ambiguous_reference",
                        dataset="agv_relations",
                        field="linename",
                        record_key=record_key,
                        message=(
                            f"agv_relations.linename={relation.product_name!r} "
                            "did not uniquely match products.product_name"
                        ),
                    )
                )
            elif len(order_matches) != 1:
                issues.append(
                    self._issue(
                        code="missing_reference"
                        if not order_matches
                        else "ambiguous_reference",
                        dataset="agv_relations",
                        field="linename",
                        record_key=record_key,
                        message=(
                            f"agv_relations.linename={relation.product_name!r} "
                            "did not uniquely match a current "
                            "orders.product_name"
                        ),
                    )
                )

            machine = machine_matches[0] if len(machine_matches) == 1 else None
            product = (
                product_matches[0] if len(product_matches) == 1 else None
            )
            order = order_matches[0] if len(order_matches) == 1 else None
            machine_name_mismatch = (
                machine is not None
                and relation.machine_name.strip() != machine.machine_name.strip()
            )
            if machine_name_mismatch:
                issues.append(
                    self._issue(
                        code="name_mismatch",
                        dataset="agv_relations",
                        field="equipmentname",
                        record_key=record_key,
                        message=(
                            "agv_relations.equipmentname does not match "
                            f"machine_master for {machine_code}"
                        ),
                    )
                )

            workshop_matches = False
            if machine is not None and order is not None:
                workshop_codes = workshops_by_process.get(
                    machine.process_code.strip(),
                    set(),
                )
                if len(workshop_codes) != 1:
                    issues.append(
                        self._issue(
                            code="ambiguous_reference"
                            if workshop_codes
                            else "missing_reference",
                            dataset="agv_relations",
                            field="equipmentid",
                            record_key=record_key,
                            message=(
                                f"machine {machine.machine_code!r} process "
                                f"{machine.process_code!r} did not uniquely "
                                "resolve a process_routes workshop"
                            ),
                        )
                    )
                else:
                    machine_workshop = next(iter(workshop_codes))
                    order_workshop = order.workshop_code.strip()
                    if machine_workshop != order_workshop:
                        issues.append(
                            self._issue(
                                code="workshop_mismatch",
                                dataset="agv_relations",
                                field="linename",
                                record_key=record_key,
                                message=(
                                    f"machine {machine.machine_code!r} resolves "
                                    f"to workshop {machine_workshop!r}, but "
                                    f"current order {order.order_code!r} resolves "
                                    f"to workshop {order_workshop!r}"
                                ),
                            )
                        )
                    else:
                        workshop_matches = True

            if (
                machine is not None
                and product is not None
                and order is not None
                and not machine_name_mismatch
                and order.product_code.strip() == product.product_code.strip()
                and workshop_matches
            ):
                relation_machine_codes.add(machine.machine_code.strip())

        for index, runtime in enumerate(request.machine_realtime):
            realtime_code = runtime.machine_code.strip()
            machine_matches = machines_by_realtime_code.get(realtime_code, [])
            if not self._is_running(runtime.status):
                continue
            standard_code = (
                machine_matches[0].machine_code.strip()
                if len(machine_matches) == 1
                else None
            )
            if (
                standard_code is not None
                and standard_code in relation_machine_codes
            ):
                continue
            mapping_detail = (
                f"maps to standard machine {standard_code!r}"
                if standard_code is not None
                else "does not uniquely match machine_master.p166_jt_group"
            )
            issues.append(
                self._issue(
                    code="missing_agv_binding",
                    dataset="machine_realtime",
                    field="machine_code",
                    record_key=self._record_key(
                        "machine_realtime",
                        runtime,
                        index,
                    ),
                    message=(
                        f"running realtime machine {runtime.machine_code!r} "
                        f"{mapping_detail} and therefore has no valid "
                        "effective AGV binding record"
                    ),
                )
            )

    @staticmethod
    def _normalized_reference_value(value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    def _validate_routes(
        self,
        request: CompletenessRequest,
        issues: list[BackendValidationIssue],
    ) -> None:
        grouped: dict[str, list[tuple[int, Any]]] = defaultdict(list)
        for index, route in enumerate(request.process_routes):
            try:
                resolve_process_loop(route.process_name)
            except UnknownProcessNameError:
                issues.append(
                    self._issue(
                        code="unknown_process_name",
                        dataset="process_routes",
                        field="process_name",
                        record_key=route.process_code,
                        message=(
                            f"process_code={route.process_code!r}, "
                            f"process_name={route.process_name!r} cannot be "
                            "mapped to an internal loop"
                        ),
                    )
                )
            grouped[route.workshop_code].append((index, route))

        for workshop_code, indexed_routes in grouped.items():
            by_sequence: dict[int, list[Any]] = defaultdict(list)
            for _, route in indexed_routes:
                by_sequence[route.sequence].append(route)

            has_duplicate_sequence = False
            for sequence, duplicates in by_sequence.items():
                if len(duplicates) > 1:
                    has_duplicate_sequence = True
                    issues.append(
                        self._issue(
                            code="duplicate_sequence",
                            dataset="process_routes",
                            field="sequence",
                            record_key=(
                                f"{workshop_code}|sequence:{sequence}"
                            ),
                            message=(
                                "process_routes.sequence must be unique within "
                                f"workshop {workshop_code!r}"
                            ),
                        )
                    )

            min_sequence = min(by_sequence)
            max_sequence = max(by_sequence)
            ordered_routes = sorted(
                indexed_routes,
                key=lambda item: item[1].sequence,
            )
            self._validate_silk_screen_route(
                workshop_code=workshop_code,
                indexed_routes=ordered_routes,
                max_sequence=max_sequence,
                issues=issues,
            )
            if not has_duplicate_sequence:
                self._validate_route_adjacency(
                    workshop_code=workshop_code,
                    indexed_routes=ordered_routes,
                    issues=issues,
                )

            route_codes = {
                route.process_code
                for _, route in indexed_routes
                if route.process_code not in (None, "")
            }

            for index, route in indexed_routes:
                if route.sequence != min_sequence:
                    self._require_route_fields(
                        route,
                        index,
                        ("upstream_process_code", "upstream_process_name"),
                        issues,
                    )
                if route.sequence != max_sequence:
                    self._require_route_fields(
                        route,
                        index,
                        ("downstream_process_code", "downstream_process_name"),
                        issues,
                    )

                for field in ("upstream_process_code", "downstream_process_code"):
                    value = getattr(route, field)
                    if value in (None, ""):
                        continue
                    if value not in route_codes:
                        issues.append(
                            self._issue(
                                code="missing_reference",
                                dataset="process_routes",
                                field=field,
                                record_key=self._record_key(
                                    "process_routes",
                                    route,
                                    index,
                                ),
                                message=(
                                    f"process_routes.{field}={value!r} was not "
                                    "found in the same workshop"
                                ),
                            )
                        )

    def _validate_silk_screen_route(
        self,
        *,
        workshop_code: str,
        indexed_routes: list[tuple[int, Any]],
        max_sequence: int,
        issues: list[BackendValidationIssue],
    ) -> None:
        route_key = workshop_code
        silk_routes = [
            (index, route)
            for index, route in indexed_routes
            if normalize_process_name(route.process_name) == "丝网"
        ]
        if not silk_routes:
            issues.append(
                self._issue(
                    code="missing_silk_screen_process",
                    dataset="process_routes",
                    field="process_name",
                    record_key=route_key,
                    message=(
                        f"process route workshop {workshop_code!r} must "
                        'contain exactly one process_name="丝网"'
                    ),
                )
            )
            return
        if len(silk_routes) > 1:
            locations = [
                self._route_record_key(workshop_code, route)
                for _, route in silk_routes
            ]
            issues.append(
                self._issue(
                    code="duplicate_silk_screen_process",
                    dataset="process_routes",
                    field="process_name",
                    record_key="|".join(locations),
                    message=(
                        f"process route workshop {workshop_code!r} has "
                        f"multiple process_name=\"丝网\": {locations}"
                    ),
                )
            )
            return

        _, silk_route = silk_routes[0]
        if silk_route.sequence != max_sequence:
            issues.append(
                self._issue(
                    code="silk_screen_not_last",
                    dataset="process_routes",
                    field="sequence",
                    record_key=self._route_record_key(
                        workshop_code,
                        silk_route,
                    ),
                    message=(
                        f'process_name="丝网" must be the maximum sequence '
                        f"in workshop {workshop_code!r}; got "
                        f"sequence={silk_route.sequence}, max={max_sequence}"
                    ),
                )
            )

    def _validate_route_adjacency(
        self,
        *,
        workshop_code: str,
        indexed_routes: list[tuple[int, Any]],
        issues: list[BackendValidationIssue],
    ) -> None:
        for position, (_, route) in enumerate(indexed_routes):
            previous = (
                indexed_routes[position - 1][1] if position > 0 else None
            )
            following = (
                indexed_routes[position + 1][1]
                if position + 1 < len(indexed_routes)
                else None
            )
            expected_fields = (
                (
                    "upstream_process_code",
                    previous.process_code if previous is not None else None,
                ),
                (
                    "upstream_process_name",
                    previous.process_name if previous is not None else None,
                ),
                (
                    "downstream_process_code",
                    following.process_code if following is not None else None,
                ),
                (
                    "downstream_process_name",
                    following.process_name if following is not None else None,
                ),
            )
            for field, expected in expected_fields:
                actual = getattr(route, field)
                if actual == expected:
                    continue
                is_last_downstream = (
                    following is None and field.startswith("downstream_")
                )
                issues.append(
                    self._issue(
                        code=(
                            "invalid_last_process_downstream"
                            if is_last_downstream
                            else "broken_process_route"
                        ),
                        dataset="process_routes",
                        field=field,
                        record_key=self._route_record_key(
                            workshop_code,
                            route,
                        ),
                        message=(
                            f"process route workshop {workshop_code!r} "
                            f"process_code={route.process_code!r}, "
                            f"process_name={route.process_name!r}, "
                            f"sequence={route.sequence} requires {field}="
                            f"{expected!r}, got {actual!r}"
                        ),
                    )
                )

    @staticmethod
    def _route_record_key(
        workshop_code: str,
        route: Any,
    ) -> str:
        return (
            f"{workshop_code}|process:{route.process_code}|"
            f"name:{route.process_name}|sequence:{route.sequence}"
        )

    def _require_route_fields(
        self,
        route: Any,
        index: int,
        fields: tuple[str, str],
        issues: list[BackendValidationIssue],
    ) -> None:
        for field in fields:
            if getattr(route, field) is None:
                issues.append(
                    self._issue(
                        code="null_field",
                        dataset="process_routes",
                        field=field,
                        record_key=self._record_key(
                            "process_routes",
                            route,
                            index,
                        ),
                        message=f"process_routes.{field} must not be null here",
                    )
                )

    def _validate_served_processes(
        self,
        request: CompletenessRequest,
        issues: list[BackendValidationIssue],
    ) -> None:
        route_codes = {
            route.process_code
            for route in request.process_routes
            if route.process_code != ""
        }
        for index, buffer in enumerate(request.buffer_master):
            for code_index, process_code in enumerate(buffer.served_process_codes):
                if process_code == "":
                    continue
                if process_code not in route_codes:
                    field = f"served_process_codes[{code_index}]"
                    issues.append(
                        self._issue(
                            code="missing_reference",
                            dataset="buffer_master",
                            field=field,
                            record_key=self._record_key(
                                "buffer_master",
                                buffer,
                                index,
                            ),
                            message=(
                                f"buffer_master.{field}={process_code!r} was not "
                                "found in process_routes"
                            ),
                        )
                    )

    def _validate_capacity(
        self,
        request: CompletenessRequest,
        issues: list[BackendValidationIssue],
    ) -> None:
        for index, buffer in enumerate(request.buffer_master):
            if buffer.max_capacity <= 0:
                issues.append(
                    self._issue(
                        code="invalid_value",
                        dataset="buffer_master",
                        field="max_capacity",
                        record_key=self._record_key(
                            "buffer_master",
                            buffer,
                            index,
                        ),
                        message="buffer_master.max_capacity must be greater than 0",
                    )
                )

    def _record_key(self, dataset: str, record: Any, index: int) -> str:
        field = _RECORD_KEY_FIELDS.get(dataset)
        if field is None:
            return f"index:{index}"
        value = getattr(record, field, None)
        return str(value) if value not in (None, "") else f"index:{index}"

    @staticmethod
    def _is_running(status: str) -> bool:
        normalized = status.strip()
        return normalized == "运行" or normalized.casefold() == "running"

    @staticmethod
    def _issue(
        *,
        code: str,
        dataset: str,
        field: str | None,
        record_key: str | None,
        message: str,
    ) -> BackendValidationIssue:
        return BackendValidationIssue(
            code=code,
            dataset=dataset,
            field=field,
            record_key=record_key,
            message=message,
        )
