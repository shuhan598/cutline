from __future__ import annotations

from collections import defaultdict
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.adapters.agv_binding_selector import select_latest_effective_bindings
from app.adapters.backend_request_loader import BackendRequestLoader
from app.schemas.backend_request_schema import BackendAlgorithmRequest
from app.schemas.request_schema import AgvRelationRequest


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
    ("buffer_realtime", "main_id"),
)

_RELATIONSHIPS = (
    ("machine_realtime", "machine_code", "machine_master", "machine_code"),
    ("orders", "product_code", "products", "product_code"),
    ("orders", "workshop_code", "workshops", "workshop_code"),
    (
        "machine_process_times",
        "machine_code",
        "machine_master",
        "machine_code",
    ),
    ("machine_process_times", "product_code", "products", "product_code"),
    ("buffer_realtime", "buffer_code", "buffer_master", "buffer_code"),
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
}


class BackendRequestCompletenessValidator:
    """Report backend request completeness issues without mutating inputs."""

    def validate(
        self,
        request: BackendAlgorithmRequest,
    ) -> BackendRequestValidationResult:
        issues: list[BackendValidationIssue] = []
        normalized_agv_relations = [
            AgvRelationRequest.model_validate(record)
            for record in BackendRequestLoader().normalize_agv_relations(
                [
                    relation.model_dump(mode="python")
                    for relation in request.agv_relations
                ]
            )
        ]
        selected_agv_relations = select_latest_effective_bindings(
            normalized_agv_relations,
            request.snapshot_meta.snapshot_time,
        )
        self._validate_empty_datasets(request, issues)
        self._validate_required_nullable_fields(request, issues)
        self._validate_empty_codes(request, issues)
        self._validate_references(request, issues)
        self._validate_agv_bindings(
            request,
            selected_agv_relations,
            issues,
        )
        self._validate_routes(request, issues)
        self._validate_served_processes(request, issues)
        self._validate_capacity(request, issues)
        return BackendRequestValidationResult(valid=not issues, issues=issues)

    def _validate_empty_datasets(
        self,
        request: BackendAlgorithmRequest,
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
        request: BackendAlgorithmRequest,
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
        request: BackendAlgorithmRequest,
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
                    if field.endswith("_code") and value == "":
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
                            if process_code == "":
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

    def _validate_references(
        self,
        request: BackendAlgorithmRequest,
        issues: list[BackendValidationIssue],
    ) -> None:
        for source_dataset, source_field, target_dataset, target_field in _RELATIONSHIPS:
            targets = {
                value
                for record in getattr(request, target_dataset)
                if (value := getattr(record, target_field)) not in (None, "")
            }
            for index, record in enumerate(getattr(request, source_dataset)):
                value = getattr(record, source_field)
                if value in (None, ""):
                    continue
                if value not in targets:
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
        request: BackendAlgorithmRequest,
        selected_relations: dict[
            str,
            tuple[Any, list[AgvRelationRequest]],
        ],
        issues: list[BackendValidationIssue],
    ) -> None:
        machine_by_code = {
            machine.machine_code: machine for machine in request.machine_master
        }
        order_codes = {order.order_code for order in request.orders}
        relation_machine_codes: set[str] = set()

        for machine_code, (_, latest) in selected_relations.items():
            record_key = machine_code or "machine_code:<empty>"
            order_values = {relation.order_code for relation in latest}
            order_name_values = {relation.order_name for relation in latest}
            has_conflict = False
            for field, values in (
                ("order_code", order_values),
                ("order_name", order_name_values),
            ):
                if len(values) > 1:
                    has_conflict = True
                    issues.append(
                        self._issue(
                            code="binding_conflict",
                            dataset="agv_relations",
                            field=field,
                            record_key=record_key,
                            message=(
                                f"latest AGV {field} values conflict for "
                                f"machine {machine_code}: {sorted(values)}"
                            ),
                        )
                    )
            if has_conflict:
                continue

            relation = latest[0]
            relation_machine_codes.add(machine_code)
            for field, value, targets, target_name in (
                (
                    "machine_code",
                    relation.machine_code,
                    machine_by_code,
                    "machine_master.machine_code",
                ),
                (
                    "order_code",
                    relation.order_code,
                    order_codes,
                    "orders.order_code",
                ),
            ):
                if value == "":
                    issues.append(
                        self._issue(
                            code="empty_code",
                            dataset="agv_relations",
                            field=field,
                            record_key=record_key,
                            message=f"agv_relations.{field} must not be empty",
                        )
                    )
                elif value not in targets:
                    issues.append(
                        self._issue(
                            code="missing_reference",
                            dataset="agv_relations",
                            field=field,
                            record_key=record_key,
                            message=(
                                f"agv_relations.{field}={value!r} was not "
                                f"found in {target_name}"
                            ),
                        )
                    )

            machine = machine_by_code.get(machine_code)
            if (
                machine is not None
                and any(
                    relation.machine_name != machine.machine_name
                    for relation in latest
                )
            ):
                issues.append(
                    self._issue(
                        code="name_mismatch",
                        dataset="agv_relations",
                        field="machine_name",
                        record_key=record_key,
                        message=(
                            "agv_relations.machine_name does not match "
                            f"machine_master for {machine_code}"
                        ),
                    )
                )

        for index, runtime in enumerate(request.machine_realtime):
            if (
                self._is_running(runtime.status)
                and runtime.machine_code not in relation_machine_codes
            ):
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
                            f"running machine {runtime.machine_code} must have "
                            "at least one AGV binding record"
                        ),
                    )
                )

    def _validate_routes(
        self,
        request: BackendAlgorithmRequest,
        issues: list[BackendValidationIssue],
    ) -> None:
        grouped: dict[tuple[str, str], list[tuple[int, Any]]] = defaultdict(list)
        for index, route in enumerate(request.process_routes):
            grouped[(route.workshop_code, route.loop_code)].append((index, route))

        for (workshop_code, loop_code), indexed_routes in grouped.items():
            by_sequence: dict[int, list[Any]] = defaultdict(list)
            for _, route in indexed_routes:
                by_sequence[route.sequence].append(route)

            for sequence, duplicates in by_sequence.items():
                if len(duplicates) > 1:
                    issues.append(
                        self._issue(
                            code="duplicate_sequence",
                            dataset="process_routes",
                            field="sequence",
                            record_key=(
                                f"{workshop_code}|{loop_code}|sequence:{sequence}"
                            ),
                            message=(
                                "process_routes.sequence must be unique within "
                                f"({workshop_code}, {loop_code})"
                            ),
                        )
                    )

            min_sequence = min(by_sequence)
            max_sequence = max(by_sequence)
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
                                    "found in the same workshop and loop"
                                ),
                            )
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
        request: BackendAlgorithmRequest,
        issues: list[BackendValidationIssue],
    ) -> None:
        route_codes = {
            (route.loop_code, route.process_code)
            for route in request.process_routes
            if route.loop_code != "" and route.process_code != ""
        }
        for index, buffer in enumerate(request.buffer_master):
            for code_index, process_code in enumerate(buffer.served_process_codes):
                if process_code == "":
                    continue
                if (buffer.loop_code, process_code) not in route_codes:
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
                                f"found in loop {buffer.loop_code!r}"
                            ),
                        )
                    )

    def _validate_capacity(
        self,
        request: BackendAlgorithmRequest,
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
