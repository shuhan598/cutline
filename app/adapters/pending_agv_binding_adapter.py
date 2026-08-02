"""Convert only AGV records relevant to Pending confirmation windows."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from app.adapters.agv_binding_selector import normalize_local_time
from app.adapters.snapshot_reference_index import (
    CurrentOrderIndex,
    MachineMasterIndex,
    ProductCatalogIndex,
    SnapshotReferenceIndexError,
)
from app.core.workshop.machine_workshop_resolver import (
    MachineWorkshopResolutionError,
    MachineWorkshopResolver,
)
from app.schemas.common_schema import AlgorithmAgvRelation
from app.schemas.pending_cutline_schema import (
    PendingCutlinePlan,
    PendingCutlinePlanStatus,
)
from app.schemas.request_schema import AgvRelationRequest


class PendingAgvBindingConversionError(ValueError):
    """A relevant AGV record is ambiguous or conflicts with master data."""


class PendingAgvBindingAdapter:
    """Project relevant raw bindings into deterministic internal history."""

    def convert(
        self,
        relations: Iterable[AgvRelationRequest],
        *,
        plans: Iterable[PendingCutlinePlan],
        snapshot_time: datetime,
        machine_index: MachineMasterIndex,
        product_catalog: ProductCatalogIndex,
        order_index: CurrentOrderIndex,
        workshop_resolver: MachineWorkshopResolver,
    ) -> list[AlgorithmAgvRelation]:
        plan_list = [
            plan
            for plan in plans
            if plan.status
            in {
                PendingCutlinePlanStatus.PENDING,
                PendingCutlinePlanStatus.PARTIALLY_CONFIRMED,
            }
        ]
        comparable_snapshot = normalize_local_time(snapshot_time)
        scoped_records_by_plan: dict[
            str,
            list[tuple[AgvRelationRequest, datetime]],
        ] = {plan.plan_id: [] for plan in plan_list}
        machine_by_code = machine_index.by_standard_code

        for relation in relations:
            machine_code = relation.machine_code.strip()
            machine = machine_by_code.get(machine_code)
            if machine is None:
                continue
            process_plans = [
                plan
                for plan in plan_list
                if (plan.process_code or plan.upstream_process_code)
                == machine.process_code
            ]
            if not process_plans:
                continue
            try:
                machine_workshop = (
                    workshop_resolver.resolve_machine_workshop(machine)
                )
            except MachineWorkshopResolutionError as exc:
                plan_ids = sorted(plan.plan_id for plan in process_plans)
                raise PendingAgvBindingConversionError(
                    f"Pending plans={plan_ids!r}, "
                    f"machine_code={machine_code!r}: {exc}"
                ) from exc

            binding_time = normalize_local_time(relation.binding_time)
            for plan in process_plans:
                if machine_workshop != plan.workshop_code:
                    continue
                expire_at = normalize_local_time(plan.expire_at)
                if (
                    binding_time > expire_at
                    or binding_time > comparable_snapshot
                ):
                    continue
                baseline_codes = {
                    baseline.machine_code
                    for baseline in plan.baseline_machine_bindings
                }
                if machine_code not in baseline_codes:
                    raise PendingAgvBindingConversionError(
                        f"plan_id={plan.plan_id}, machine_code={machine_code}, "
                        f"binding_time={binding_time.isoformat()} is observable "
                        "in the Pending plan scope but is absent from "
                        "baseline_machine_bindings"
                    )
                scoped_records_by_plan[plan.plan_id].append(
                    (relation, binding_time)
                )

        self._validate_saved_baselines(
            plans=plan_list,
            scoped_records_by_plan=scoped_records_by_plan,
            machine_index=machine_index,
            product_catalog=product_catalog,
            order_index=order_index,
            workshop_resolver=workshop_resolver,
        )

        grouped: dict[
            tuple[str, datetime],
            list[tuple[set[str], AlgorithmAgvRelation]],
        ] = {}
        for plan in plan_list:
            created_at = normalize_local_time(plan.created_at)
            for relation, binding_time in scoped_records_by_plan[plan.plan_id]:
                if binding_time <= created_at:
                    continue
                converted = self.convert_binding(
                    relation,
                    binding_time=binding_time,
                    machine_index=machine_index,
                    product_catalog=product_catalog,
                    order_index=order_index,
                    workshop_resolver=workshop_resolver,
                    context=(
                        f"Pending plans={[plan.plan_id]!r}, "
                        f"machine_code={relation.machine_code.strip()!r}, "
                        f"binding_time={binding_time.isoformat()}"
                    ),
                )
                key = (converted.machine_code, converted.binding_time)
                grouped.setdefault(key, []).append(
                    ({plan.plan_id}, converted)
                )

        result: list[AlgorithmAgvRelation] = []
        for (machine_code, binding_time), records in sorted(
            grouped.items(), key=lambda item: item[0]
        ):
            result.append(
                self._collapse_same_time_records(
                    records,
                    machine_code=machine_code,
                    binding_time=binding_time,
                )
            )
        return result

    def _validate_saved_baselines(
        self,
        *,
        plans: list[PendingCutlinePlan],
        scoped_records_by_plan: dict[
            str,
            list[tuple[AgvRelationRequest, datetime]],
        ],
        machine_index: MachineMasterIndex,
        product_catalog: ProductCatalogIndex,
        order_index: CurrentOrderIndex,
        workshop_resolver: MachineWorkshopResolver,
    ) -> None:
        for plan in plans:
            created_at = normalize_local_time(plan.created_at)
            records_by_machine: dict[
                str,
                list[tuple[AgvRelationRequest, datetime]],
            ] = {}
            for relation, binding_time in scoped_records_by_plan[plan.plan_id]:
                if binding_time <= created_at:
                    records_by_machine.setdefault(
                        relation.machine_code.strip(), []
                    ).append((relation, binding_time))

            for baseline in plan.baseline_machine_bindings:
                records = records_by_machine.get(baseline.machine_code, [])
                if not records:
                    continue
                latest_time = max(binding_time for _, binding_time in records)
                latest_records = [
                    relation
                    for relation, binding_time in records
                    if binding_time == latest_time
                ]
                converted_records = [
                    (
                        {plan.plan_id},
                        self.convert_binding(
                            relation,
                            binding_time=latest_time,
                            machine_index=machine_index,
                            product_catalog=product_catalog,
                            order_index=order_index,
                            workshop_resolver=workshop_resolver,
                            context=(
                                f"Pending plans={[plan.plan_id]!r}, "
                                f"machine_code={baseline.machine_code!r}, "
                                f"binding_time={latest_time.isoformat()}"
                            ),
                        ),
                    )
                    for relation in latest_records
                ]
                observed = self._collapse_same_time_records(
                    converted_records,
                    machine_code=baseline.machine_code,
                    binding_time=latest_time,
                )
                saved_values = (
                    normalize_local_time(baseline.observed_at),
                    baseline.order_code,
                    baseline.product_code,
                    baseline.product_name,
                    baseline.wafer_size,
                    baseline.wafer_spec,
                )
                observed_values = (
                    observed.binding_time,
                    observed.order_code,
                    observed.product_code,
                    observed.product_name,
                    product_catalog.by_code[observed.product_code].wafer_size,
                    observed.wafer_spec,
                )
                if saved_values != observed_values:
                    raise PendingAgvBindingConversionError(
                        f"plan_id={plan.plan_id}, "
                        f"machine_code={baseline.machine_code}: saved baseline "
                        f"values={saved_values!r} conflict with latest "
                        f"observable at-or-before-created binding values="
                        f"{observed_values!r}"
                    )

    def _collapse_same_time_records(
        self,
        records: list[tuple[set[str], AlgorithmAgvRelation]],
        *,
        machine_code: str,
        binding_time: datetime,
    ) -> AlgorithmAgvRelation:
        first = records[0][1]
        if any(record != first for _, record in records[1:]):
            plan_ids = sorted(
                {
                    plan_id
                    for record_plan_ids, _ in records
                    for plan_id in record_plan_ids
                }
            )
            values = sorted(
                {
                    (
                        record.machine_name,
                        record.order_code,
                        record.product_code,
                        record.product_name,
                        record.previous_product_code,
                        record.previous_product_name,
                        record.wafer_spec,
                    )
                    for _, record in records
                },
                key=repr,
            )
            raise PendingAgvBindingConversionError(
                f"Pending plans={plan_ids!r}, machine_code={machine_code!r}, "
                f"binding_time={binding_time.isoformat()}: same-time AGV "
                f"business values conflict: {values!r}"
            )
        return first

    def convert_binding(
        self,
        relation: AgvRelationRequest,
        *,
        binding_time: datetime,
        machine_index: MachineMasterIndex,
        product_catalog: ProductCatalogIndex,
        order_index: CurrentOrderIndex,
        workshop_resolver: MachineWorkshopResolver,
        context: str,
    ) -> AlgorithmAgvRelation:
        try:
            machine = machine_index.resolve_agv_code(relation.machine_code)
            if relation.machine_name != machine.machine_name:
                raise PendingAgvBindingConversionError(
                    f"{context}: AGV machine_name={relation.machine_name!r} "
                    f"does not match machine master {machine.machine_name!r}"
                )
            product_name = relation.product_name.strip()
            product = product_catalog.resolve_name(
                product_name,
                source=f"{context} current linename",
            )
            order = order_index.resolve_product_name(
                product_name,
                source=f"{context} current linename",
            )
            if order.product_code != product.product_code:
                raise PendingAgvBindingConversionError(
                    f"{context}: current product_code={product.product_code!r} "
                    f"conflicts with order {order.order_code!r} product_code="
                    f"{order.product_code!r}"
                )
            machine_workshop = workshop_resolver.resolve_machine_workshop(
                machine
            )
            if machine_workshop != order.workshop_code:
                raise PendingAgvBindingConversionError(
                    f"{context}: machine workshop={machine_workshop!r} "
                    f"conflicts with current order workshop="
                    f"{order.workshop_code!r}"
                )
            if not relation.wafer_spec.strip():
                raise PendingAgvBindingConversionError(
                    f"{context}: wafer_spec must not be blank"
                )

            previous_name = relation.previous_product_name
            normalized_previous_name = (
                previous_name.strip() if previous_name is not None else ""
            )
            previous_product = (
                product_catalog.resolve_name(
                    normalized_previous_name,
                    source=f"{context} previous lastlinename",
                )
                if normalized_previous_name
                else None
            )
            return AlgorithmAgvRelation(
                machine_code=machine.machine_code,
                machine_name=machine.machine_name,
                order_code=order.order_code,
                product_code=product.product_code,
                product_name=product.product_name,
                previous_product_code=(
                    previous_product.product_code
                    if previous_product is not None
                    else None
                ),
                previous_product_name=(
                    previous_product.product_name
                    if previous_product is not None
                    else None
                ),
                wafer_spec=relation.wafer_spec,
                binding_time=normalize_local_time(binding_time),
            )
        except PendingAgvBindingConversionError:
            raise
        except (
            SnapshotReferenceIndexError,
            MachineWorkshopResolutionError,
        ) as exc:
            raise PendingAgvBindingConversionError(
                f"{context}: {exc}"
            ) from exc
