"""Convert backend snapshot requests into algorithm-owned snapshot models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable, TypeVar

from pydantic import ValidationError

from app.adapters.agv_binding_selector import select_latest_effective_bindings
from app.adapters.pending_agv_binding_adapter import (
    PendingAgvBindingAdapter,
)
from app.adapters.pending_cutline_plan_adapter import (
    PendingCutlinePlanAdapter,
)
from app.adapters.snapshot_reference_index import (
    CurrentOrderIndex,
    MachineMasterIndex,
    ProductCatalogIndex,
    SnapshotReferenceIndexError,
)
from app.core.workshop.buffer_process_resolver import (
    BufferProcessResolutionError,
    BufferProcessResolver,
)
from app.core.workshop.machine_workshop_resolver import (
    MachineWorkshopResolutionError,
    MachineWorkshopResolver,
)
from app.schemas.common_schema import (
    AlgorithmActiveCutlineEvent,
    AlgorithmAgvRelation,
    AlgorithmBufferMaster,
    AlgorithmBufferOrderInventory,
    AlgorithmBufferProcessRelation,
    AlgorithmConfig,
    AlgorithmLine,
    AlgorithmMachineLineRelation,
    AlgorithmMachineMaster,
    AlgorithmMachineProductCapacity,
    AlgorithmMachineRuntime,
    AlgorithmOrder,
    AlgorithmProcessRoute,
    AlgorithmProduct,
    AlgorithmWorkshop,
)
from app.schemas.request_schema import (
    ActiveCutlineEventRequest,
    AlgorithmSnapshot,
    CutlineAlgorithmRequest,
)
from app.utils.time_utils import normalize_local_time


class SnapshotConversionError(ValueError):
    """请求数据无法转换为完整算法快照。"""


ModelT = TypeVar("ModelT")


class SnapshotAdapter:
    """Convert the backend request format into an algorithm snapshot."""

    def to_algorithm_snapshot(
        self, request: CutlineAlgorithmRequest
    ) -> AlgorithmSnapshot:
        """Convert a validated backend request into a complete algorithm snapshot."""
        try:
            config = AlgorithmConfig()
            snapshot_time = normalize_local_time(
                request.snapshot_meta.snapshot_time
            )
            if request.machine_lines and not request.lines:
                raise SnapshotConversionError(
                    "machine_lines were provided but lines are empty"
                )

            workshops = self._convert_workshops(request.workshops)
            workshop_by_code = self._index_unique(
                workshops, "workshop_code", "workshop"
            )

            lines = self._convert_lines(request.lines, workshop_by_code)
            line_by_code = self._index_unique(lines, "line_code", "line")

            machine_index = MachineMasterIndex(request.machine_master)
            machine_masters = machine_index.machine_masters
            machine_by_code = machine_index.by_standard_code

            product_catalog = ProductCatalogIndex(
                self._convert_products(request.products)
            )
            products = product_catalog.products

            order_index = CurrentOrderIndex(
                self._convert_orders(
                    request.orders,
                    workshop_by_code,
                ),
                product_catalog,
            )
            orders = order_index.orders
            order_by_code = order_index.by_code

            process_routes = self._convert_process_routes(
                request.process_routes, workshop_by_code
            )
            self._index_process_routes(process_routes)
            machine_workshop_resolver = MachineWorkshopResolver(process_routes)

            machine_lines = self._convert_machine_lines(
                request.machine_lines, machine_by_code, line_by_code
            )
            agv_relations = self._convert_agv_relations(
                request.agv_relations,
                snapshot_time=snapshot_time,
                machine_index=machine_index,
                product_catalog=product_catalog,
                order_index=order_index,
                workshop_resolver=machine_workshop_resolver,
            )
            agv_by_machine = self._index_unique(
                agv_relations,
                "machine_code",
                "selected AGV binding",
            )
            machine_runtimes = self._convert_machine_runtimes(
                request.machine_realtime,
                machine_index,
                agv_by_machine,
            )
            capacities = self._convert_capacities(
                request.machine_process_times,
                machine_by_code,
                product_catalog.by_code,
            )

            self._validate_runtime_machine_workshops(
                machine_runtimes=machine_runtimes,
                machine_by_code=machine_by_code,
                process_routes=process_routes,
            )

            buffer_masters = self._convert_buffer_masters(request.buffer_master)
            buffer_by_code = self._index_unique(
                buffer_masters, "buffer_code", "buffer"
            )
            buffer_process_relations = self._build_buffer_process_relations(
                buffer_masters,
                process_routes,
            )
            relation_by_buffer = self._index_unique(
                buffer_process_relations, "buffer_code", "buffer process relation"
            )
            buffer_order_inventories = self._convert_buffer_order_inventories(
                request.buffer_realtime,
                order_index,
                buffer_by_code,
                relation_by_buffer,
            )

            pending_cutline_plans = PendingCutlinePlanAdapter().convert(
                request.pending_cutline_plans,
                config=config,
                snapshot_time=snapshot_time,
                machine_by_code=machine_by_code,
                order_by_code=order_by_code,
                product_by_code=product_catalog.by_code,
                buffer_by_code=buffer_by_code,
                relation_by_buffer=relation_by_buffer,
                workshop_codes=set(workshop_by_code),
                workshop_resolver=machine_workshop_resolver,
            )
            agv_binding_history = PendingAgvBindingAdapter().convert(
                request.agv_relations,
                plans=pending_cutline_plans,
                snapshot_time=snapshot_time,
                machine_index=machine_index,
                product_catalog=product_catalog,
                order_index=order_index,
                workshop_resolver=machine_workshop_resolver,
            )

            active_cutline_events = self._convert_active_cutline_events(
                request.active_cutline_events,
                snapshot_time=snapshot_time,
                machine_by_code=machine_by_code,
                order_by_code=order_by_code,
                product_by_code=product_catalog.by_code,
                workshop_by_code=workshop_by_code,
                buffer_by_code=buffer_by_code,
                relation_by_buffer=relation_by_buffer,
                process_routes=process_routes,
            )

            return AlgorithmSnapshot(
                current_time=snapshot_time,
                workshops=workshops,
                lines=lines,
                machine_lines=machine_lines,
                machine_runtimes=machine_runtimes,
                machine_masters=machine_masters,
                machine_product_capacities=capacities,
                orders=orders,
                products=products,
                process_routes=process_routes,
                buffer_masters=buffer_masters,
                buffer_process_relations=buffer_process_relations,
                buffer_order_inventories=buffer_order_inventories,
                agv_relations=agv_relations,
                pending_cutline_plans=pending_cutline_plans,
                agv_binding_history=agv_binding_history,
                active_cutline_events=active_cutline_events,
                return_suggested_event_ids=list(
                    request.return_suggested_event_ids
                ),
                mixed_cutline_event_ids=list(request.mixed_cutline_event_ids),
                config=config,
            )
        except SnapshotConversionError:
            raise
        except SnapshotReferenceIndexError as exc:
            raise SnapshotConversionError(str(exc)) from exc
        except (ValidationError, ValueError) as exc:
            raise SnapshotConversionError(
                f"Snapshot model validation failed: {exc}"
            ) from exc

    def _validate_runtime_machine_workshops(
        self,
        *,
        machine_runtimes: Iterable[AlgorithmMachineRuntime],
        machine_by_code: dict[str, AlgorithmMachineMaster],
        process_routes: Iterable[AlgorithmProcessRoute],
    ) -> None:
        resolver = MachineWorkshopResolver(process_routes)
        for runtime in machine_runtimes:
            machine = machine_by_code[runtime.machine_code]
            try:
                resolver.resolve_machine_workshop(machine)
            except MachineWorkshopResolutionError as exc:
                raise SnapshotConversionError(str(exc)) from exc

    def _convert_workshops(self, source: Iterable[Any]) -> list[AlgorithmWorkshop]:
        return [
            AlgorithmWorkshop(
                workshop_code=item.workshop_code,
                workshop_name=item.workshop_name,
            )
            for item in source
        ]

    def _convert_lines(
        self, source: Iterable[Any], workshop_by_code: dict[str, AlgorithmWorkshop]
    ) -> list[AlgorithmLine]:
        result: list[AlgorithmLine] = []
        for item in source:
            if item.workshop_code not in workshop_by_code:
                raise SnapshotConversionError(
                    f"{item.workshop_code} workshop does not exist for line {item.line_code}"
                )
            if item.wafer_spec not in {"N", "R", "P"}:
                raise SnapshotConversionError(
                    f"{item.line_code} line wafer_spec must be one of N, R, P"
                )
            result.append(
                AlgorithmLine(
                    line_code=item.line_code,
                    line_name=item.line_name,
                    wafer_spec=item.wafer_spec,
                    workshop_code=item.workshop_code,
                    workshop_name=item.workshop_name,
                )
            )
        return result

    def _convert_machine_lines(
        self,
        source: Iterable[Any],
        machine_by_code: dict[str, AlgorithmMachineMaster],
        line_by_code: dict[str, AlgorithmLine],
    ) -> list[AlgorithmMachineLineRelation]:
        result: list[AlgorithmMachineLineRelation] = []
        line_by_machine: dict[str, str] = {}
        seen: set[tuple[str, str]] = set()
        for item in source:
            if item.machine_code not in machine_by_code:
                raise SnapshotConversionError(
                    f"{item.machine_code} machine does not exist for machine-line relation"
                )
            if item.line_code not in line_by_code:
                raise SnapshotConversionError(
                    f"{item.line_code} line does not exist for machine {item.machine_code}"
                )
            key = (item.machine_code, item.line_code)
            if key in seen:
                raise SnapshotConversionError(
                    f"Duplicate machine-line relation: "
                    f"{item.machine_code} -> {item.line_code}"
                )
            seen.add(key)
            previous_line = line_by_machine.setdefault(
                item.machine_code, item.line_code
            )
            if previous_line != item.line_code:
                raise SnapshotConversionError(
                    f"{item.machine_code} machine is bound to multiple different lines"
                )
            result.append(
                AlgorithmMachineLineRelation(
                    machine_code=item.machine_code,
                    line_code=item.line_code,
                )
            )
        return result

    def _convert_machine_runtimes(
        self,
        source: Iterable[Any],
        machine_index: MachineMasterIndex,
        agv_by_machine: dict[str, AlgorithmAgvRelation],
    ) -> list[AlgorithmMachineRuntime]:
        result: list[AlgorithmMachineRuntime] = []
        seen_machine_codes: set[str] = set()
        for item in source:
            machine = machine_index.resolve_realtime_code(item.machine_code)
            standard_code = machine.machine_code
            if standard_code in seen_machine_codes:
                raise SnapshotConversionError(
                    "Duplicate machine runtime after p166_jt_group mapping: "
                    f"source machine_code={item.machine_code!r}, "
                    f"standard machine_code={standard_code!r}"
                )
            seen_machine_codes.add(standard_code)
            status = self._map_machine_status(item.status)
            binding = agv_by_machine.get(standard_code)
            if status == "running" and binding is None:
                raise SnapshotConversionError(
                    "Running machine has no effective AGV binding at "
                    f"snapshot_time: source machine_code={item.machine_code!r}, "
                    f"standard machine_code={standard_code!r}"
                )
            result.append(
                AlgorithmMachineRuntime(
                    machine_code=standard_code,
                    status=status,
                    current_order_code=(
                        binding.order_code if binding is not None else None
                    ),
                    tangent_time=item.tangent_time,
                    input_quantity_30m=item.input_quantity,
                    output_quantity_30m=item.output_quantity,
                    period_quantity_30m=item.period_quantity,
                    out_time=item.out_time,
                )
            )
        return result

    @staticmethod
    def _map_machine_status(status: str) -> str:
        normalized = status.strip()
        if normalized == "运行" or normalized.casefold() == "running":
            return "running"
        return "stopped"

    def _convert_products(self, source: Iterable[Any]) -> list[AlgorithmProduct]:
        return [
            AlgorithmProduct(
                product_code=item.product_code,
                product_name=item.product_name,
                wafer_size=item.wafer_size,
                source_grade=item.source_grade,
                material_code=item.material_code,
                material_name=item.material_name,
            )
            for item in source
        ]

    def _convert_orders(
        self,
        source: Iterable[Any],
        workshop_by_code: dict[str, AlgorithmWorkshop],
    ) -> list[AlgorithmOrder]:
        result: list[AlgorithmOrder] = []
        for item in source:
            if item.workshop_code not in workshop_by_code:
                raise SnapshotConversionError(
                    f"{item.workshop_code} workshop does not exist for order {item.order_code}"
                )
            expected_remaining = item.total_quantity - item.produced_quantity
            difference = abs(
                Decimal(str(item.total_quantity))
                - Decimal(str(item.produced_quantity))
                - Decimal(str(item.remaining_quantity))
            )
            if difference > Decimal("0.000001"):
                raise SnapshotConversionError(
                    f"Order {item.order_code} remaining quantity mismatch: "
                    f"backend={item.remaining_quantity}, computed={expected_remaining}"
                )
            result.append(
                AlgorithmOrder(
                    order_code=item.order_code,
                    order_status=item.order_status,
                    product_code=item.product_code,
                    product_name=item.product_name,
                    workshop_code=item.workshop_code,
                    workshop_name=item.workshop_name,
                    total_quantity=item.total_quantity,
                    produced_quantity=item.produced_quantity,
                    piece_source=item.piece_source,
                    estimated_yield=item.estimated_yield,
                )
            )
        return result

    def _convert_capacities(
        self,
        source: Iterable[Any],
        machine_by_code: dict[str, AlgorithmMachineMaster],
        product_by_code: dict[str, AlgorithmProduct],
    ) -> list[AlgorithmMachineProductCapacity]:
        result: list[AlgorithmMachineProductCapacity] = []
        seen: set[tuple[str, str]] = set()
        for item in source:
            if item.machine_code not in machine_by_code:
                raise SnapshotConversionError(
                    f"{item.machine_code} machine does not exist for capacity"
                )
            if item.product_code not in product_by_code:
                raise SnapshotConversionError(
                    f"{item.product_code} product does not exist for capacity"
                )
            key = (item.machine_code, item.product_code)
            if key in seen:
                raise SnapshotConversionError(
                    f"{item.machine_code} {item.product_code} duplicate machine product capacity"
                )
            seen.add(key)
            result.append(
                AlgorithmMachineProductCapacity(
                    machine_code=item.machine_code,
                    product_code=item.product_code,
                    proc_seconds=item.proc_seconds,
                    actual_capacity=item.actual_capacity,
                )
            )
        return result

    def _convert_process_routes(
        self,
        source: Iterable[Any],
        workshop_by_code: dict[str, AlgorithmWorkshop],
    ) -> list[AlgorithmProcessRoute]:
        result: list[AlgorithmProcessRoute] = []
        for item in source:
            if item.sequence < 1:
                raise SnapshotConversionError(
                    f"{item.process_code} process route sequence must be at least 1"
                )
            if item.workshop_code not in workshop_by_code:
                raise SnapshotConversionError(
                    f"{item.workshop_code} workshop does not exist for process {item.process_code}"
                )
            result.append(
                AlgorithmProcessRoute(
                    process_code=item.process_code,
                    process_name=item.process_name,
                    sequence=item.sequence,
                    cache_type=item.cache_type,
                    workshop_code=item.workshop_code,
                    workshop_name=item.workshop_name,
                    loop_code=item.loop_code,
                    loop_name=item.loop_name,
                    upstream_process_code=item.upstream_process_code,
                    upstream_process_name=item.upstream_process_name,
                    downstream_process_code=item.downstream_process_code,
                    downstream_process_name=item.downstream_process_name,
                )
            )
        return result

    def _convert_buffer_masters(
        self, source: Iterable[Any]
    ) -> list[AlgorithmBufferMaster]:
        result: list[AlgorithmBufferMaster] = []
        for item in source:
            if len(item.served_process_codes) != len(item.served_process_names):
                raise SnapshotConversionError(
                    f"Buffer {item.buffer_code} served process code/name length mismatch"
                )
            if len(item.served_process_codes) != 2:
                raise SnapshotConversionError(
                    f"Buffer {item.buffer_code} must serve exactly two processes"
                )
            result.append(
                AlgorithmBufferMaster(
                    buffer_code=item.buffer_code,
                    buffer_name=item.buffer_name,
                    buffer_type=item.buffer_type,
                    buffer_type_title=item.buffer_type_title,
                    max_capacity=item.max_capacity,
                    safety_low=item.safety_low,
                    served_process_codes=list(item.served_process_codes),
                    served_process_names=list(item.served_process_names),
                    loop_code=item.loop_code,
                    loop_name=item.loop_name,
                )
            )
        return result

    def _build_buffer_process_relations(
        self,
        buffers: Iterable[AlgorithmBufferMaster],
        routes: Iterable[AlgorithmProcessRoute],
    ) -> list[AlgorithmBufferProcessRelation]:
        all_routes = list(routes)
        resolver = BufferProcessResolver(all_routes)
        result: list[AlgorithmBufferProcessRelation] = []
        for buffer in buffers:
            try:
                resolution = resolver.resolve(buffer)
            except BufferProcessResolutionError as exc:
                raise SnapshotConversionError(str(exc)) from exc
            result.append(
                AlgorithmBufferProcessRelation(
                    buffer_code=buffer.buffer_code,
                    workshop_code=resolution.workshop_code,
                    upstream_process_code=(
                        resolution.upstream_process_code
                    ),
                    downstream_process_code=(
                        resolution.downstream_process_code
                    ),
                )
            )
        return result

    def _convert_buffer_order_inventories(
        self,
        source: Iterable[Any],
        order_index: CurrentOrderIndex,
        buffer_by_code: dict[str, AlgorithmBufferMaster],
        relation_by_buffer: dict[str, AlgorithmBufferProcessRelation],
    ) -> list[AlgorithmBufferOrderInventory]:
        result: list[AlgorithmBufferOrderInventory] = []
        seen: set[tuple[str, str, str]] = set()
        main_id_by_buffer: dict[str, str] = {}
        group_context_by_main_id: dict[
            str, tuple[str, dict[str, str]]
        ] = {}
        for item in source:
            if item.buffer_code not in buffer_by_code:
                raise SnapshotConversionError(
                    f"{item.buffer_code} buffer does not exist for realtime inventory"
                )

            main_id = item.main_id
            if main_id is None or not main_id.strip():
                raise SnapshotConversionError(
                    f"Buffer {item.buffer_code} main_id is required and must not be blank"
                )

            relation = relation_by_buffer[item.buffer_code]
            buffer = buffer_by_code[item.buffer_code]
            context = {
                "workshop_code": relation.workshop_code,
                "upstream_process_code": relation.upstream_process_code,
                "downstream_process_code": relation.downstream_process_code,
                "loop_code": buffer.loop_code,
            }
            existing_group_context = group_context_by_main_id.get(main_id)
            if existing_group_context is None:
                group_context_by_main_id[main_id] = (
                    item.buffer_code,
                    context,
                )
            else:
                existing_buffer_code, expected_context = (
                    existing_group_context
                )
                for field_name, expected_value in expected_context.items():
                    actual_value = context[field_name]
                    if actual_value != expected_value:
                        raise SnapshotConversionError(
                            f"Buffer main_id {main_id} conflict for "
                            f"{field_name}: buffer_code "
                            f"{existing_buffer_code}={expected_value!r}, "
                            f"buffer_code {item.buffer_code}={actual_value!r}"
                        )

            source_name = item.bound_source_name.strip()
            order = order_index.resolve_product_name(
                source_name,
                source=(
                    f"Buffer {item.buffer_code} bound_source_name"
                ),
            )
            if order.workshop_code != relation.workshop_code:
                raise SnapshotConversionError(
                    f"Buffer {item.buffer_code} product_name {source_name!r} "
                    f"resolved order {order.order_code!r} in workshop "
                    f"{order.workshop_code!r}, but the Buffer process relation "
                    f"belongs to workshop {relation.workshop_code!r}"
                )

            existing_main_id = main_id_by_buffer.get(item.buffer_code)
            if (
                existing_main_id is not None
                and existing_main_id != main_id
            ):
                raise SnapshotConversionError(
                    f"Buffer {item.buffer_code} main_id conflict: "
                    f"existing main_id={existing_main_id!r}, "
                    f"current main_id={main_id!r}, "
                    f"order_code={order.order_code!r}"
                )
            main_id_by_buffer[item.buffer_code] = main_id

            key = (main_id, item.buffer_code, order.order_code)
            if key in seen:
                raise SnapshotConversionError(
                    f"Buffer main_id {main_id} buffer_code "
                    f"{item.buffer_code} order {order.order_code} "
                    "duplicate inventory"
                )
            seen.add(key)
            result.append(
                AlgorithmBufferOrderInventory(
                    main_id=main_id,
                    buffer_code=item.buffer_code,
                    order_code=order.order_code,
                    current_quantity=item.current_quantity,
                )
            )
        return result

    def _convert_agv_relations(
        self,
        source: Iterable[Any],
        *,
        snapshot_time: datetime,
        machine_index: MachineMasterIndex,
        product_catalog: ProductCatalogIndex,
        order_index: CurrentOrderIndex,
        workshop_resolver: MachineWorkshopResolver,
    ) -> list[AlgorithmAgvRelation]:
        effective_by_machine = select_latest_effective_bindings(
            source,
            snapshot_time,
        )

        result: list[AlgorithmAgvRelation] = []
        for machine_code, (latest_time, latest) in effective_by_machine.items():
            for raw_field, standard_field in (
                ("equipmentname", "machine_name"),
                ("linename", "product_name"),
                ("waferspec", "wafer_spec"),
            ):
                values = {getattr(item, standard_field) for item in latest}
                if len(values) > 1:
                    rendered_values = ", ".join(
                        sorted((repr(value) for value in values))
                    )
                    raise SnapshotConversionError(
                        f"AGV equipmentid {machine_code!r} latest binding "
                        f"conflict at {latest_time.isoformat()}: "
                        f"{raw_field} values=[{rendered_values}]"
                    )

            previous_names = {
                item.previous_product_name.strip()
                if item.previous_product_name is not None
                and item.previous_product_name.strip()
                else None
                for item in latest
            }
            if len(previous_names) > 1:
                rendered_values = ", ".join(
                    sorted(repr(value) for value in previous_names)
                )
                raise SnapshotConversionError(
                    f"AGV equipmentid {machine_code!r} latest binding "
                    f"conflict at {latest_time.isoformat()}: "
                    f"lastlinename values=[{rendered_values}]"
                )

            machine = machine_index.resolve_agv_code(machine_code)
            invalid_machine_names = sorted(
                {
                    item.machine_name
                    for item in latest
                    if item.machine_name != machine.machine_name
                }
            )
            if invalid_machine_names:
                raise SnapshotConversionError(
                    f"{machine.machine_code} AGV equipmentname "
                    f"{invalid_machine_names[0]!r} does not match machine "
                    f"master {machine.machine_name!r}"
                )

            product_name = latest[0].product_name.strip()
            product = product_catalog.resolve_name(
                product_name,
                source=f"AGV equipmentid {machine_code!r} linename",
            )
            order = order_index.resolve_product_name(
                product_name,
                source=f"AGV equipmentid {machine_code!r} linename",
            )
            if order.product_code != product.product_code:
                raise SnapshotConversionError(
                    f"AGV equipmentid {machine_code!r} linename "
                    f"{product_name!r} resolved product_code "
                    f"{product.product_code!r}, but current order "
                    f"{order.order_code!r} uses {order.product_code!r}"
                )
            try:
                machine_workshop = workshop_resolver.resolve_machine_workshop(
                    machine
                )
            except MachineWorkshopResolutionError as exc:
                raise SnapshotConversionError(str(exc)) from exc
            if machine_workshop != order.workshop_code:
                raise SnapshotConversionError(
                    f"AGV machine {machine.machine_code!r} resolved order "
                    f"{order.order_code!r}: machine workshop "
                    f"{machine_workshop!r} does not match order workshop "
                    f"{order.workshop_code!r}"
                )
            wafer_spec = latest[0].wafer_spec
            if not wafer_spec.strip():
                raise SnapshotConversionError(
                    f"AGV equipmentid {machine_code!r} wafer_spec must not "
                    "be blank"
                )
            previous_name = next(iter(previous_names))
            previous_product = (
                product_catalog.resolve_name(
                    previous_name,
                    source=(
                        f"AGV equipmentid {machine_code!r} lastlinename"
                    ),
                )
                if previous_name is not None
                else None
            )

            result.append(
                AlgorithmAgvRelation(
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
                    wafer_spec=wafer_spec,
                    binding_time=latest_time,
                )
            )
        return result

    def _convert_active_cutline_events(
        self,
        source: Iterable[ActiveCutlineEventRequest],
        *,
        snapshot_time: datetime,
        machine_by_code: dict[str, AlgorithmMachineMaster],
        order_by_code: dict[str, AlgorithmOrder],
        product_by_code: dict[str, AlgorithmProduct],
        workshop_by_code: dict[str, AlgorithmWorkshop],
        buffer_by_code: dict[str, AlgorithmBufferMaster],
        relation_by_buffer: dict[str, AlgorithmBufferProcessRelation],
        process_routes: Iterable[AlgorithmProcessRoute],
    ) -> list[AlgorithmActiveCutlineEvent]:
        routes = list(process_routes)
        workshop_resolver = MachineWorkshopResolver(routes)
        result: list[AlgorithmActiveCutlineEvent] = []
        seen_event_ids: set[str] = set()

        for event in source:
            if event.event_id in seen_event_ids:
                raise SnapshotConversionError(
                    f"Active cutline event {event.event_id} event_id duplicate: "
                    f"{event.event_id}"
                )
            seen_event_ids.add(event.event_id)

            references = (
                ("machine_code", event.machine_code, machine_by_code, "machine"),
                (
                    "source_order_code",
                    event.source_order_code,
                    order_by_code,
                    "order",
                ),
                (
                    "target_order_code",
                    event.target_order_code,
                    order_by_code,
                    "order",
                ),
                (
                    "workshop_code",
                    event.workshop_code,
                    workshop_by_code,
                    "workshop",
                ),
                (
                    "target_buffer_code",
                    event.target_buffer_code,
                    buffer_by_code,
                    "buffer",
                ),
            )
            for field, code, index, label in references:
                if code not in index:
                    raise SnapshotConversionError(
                        f"Active cutline event {event.event_id} {field} {code} "
                        f"{label} does not exist"
                    )

            optional_buffers = (
                ("source_buffer_code", event.source_buffer_code),
                ("warning_buffer_code", event.warning_buffer_code),
            )
            for field, buffer_code in optional_buffers:
                if buffer_code is not None and buffer_code not in buffer_by_code:
                    raise SnapshotConversionError(
                        f"Active cutline event {event.event_id} {field} "
                        f"{buffer_code} buffer does not exist"
                    )

            for field in ("upstream_process_code", "downstream_process_code"):
                process_code = getattr(event, field)
                if not any(
                    route.workshop_code == event.workshop_code
                    and route.process_code == process_code
                    for route in routes
                ):
                    raise SnapshotConversionError(
                        f"Active cutline event {event.event_id} {field} "
                        f"{process_code} workshop {event.workshop_code} "
                        f"process route does not exist"
                    )

            optional_processes = (
                ("process_code", event.process_code),
                (
                    "warning_upstream_process_code",
                    event.warning_upstream_process_code,
                ),
                (
                    "warning_downstream_process_code",
                    event.warning_downstream_process_code,
                ),
            )
            for field, process_code in optional_processes:
                if process_code is None:
                    continue
                if not any(
                    route.workshop_code == event.workshop_code
                    and route.process_code == process_code
                    for route in routes
                ):
                    raise SnapshotConversionError(
                        f"Active cutline event {event.event_id} {field} "
                        f"{process_code} workshop {event.workshop_code} "
                        "process route does not exist"
                    )
            try:
                machine_workshop = workshop_resolver.resolve_machine_workshop(
                    machine_by_code[event.machine_code]
                )
            except MachineWorkshopResolutionError as exc:
                raise SnapshotConversionError(
                    f"Active cutline event {event.event_id} machine "
                    f"{event.machine_code}: {exc}"
                ) from exc
            if machine_workshop != event.workshop_code:
                raise SnapshotConversionError(
                    f"Active cutline event {event.event_id} machine "
                    f"{event.machine_code} workshop {machine_workshop} "
                    f"does not match event workshop {event.workshop_code}"
                )
            if (
                event.process_code is not None
                and event.process_code
                != machine_by_code[event.machine_code].process_code
            ):
                raise SnapshotConversionError(
                    f"Active cutline event {event.event_id} process_code "
                    f"{event.process_code} does not match machine "
                    f"{event.machine_code} process_code "
                    f"{machine_by_code[event.machine_code].process_code}"
                )

            if event.warning_buffer_code is not None:
                warning_relation = relation_by_buffer[event.warning_buffer_code]
                if warning_relation.workshop_code != event.workshop_code:
                    raise SnapshotConversionError(
                        f"Active cutline event {event.event_id} "
                        f"warning_buffer_code {event.warning_buffer_code} "
                        f"workshop {warning_relation.workshop_code} does not "
                        f"match event workshop {event.workshop_code}"
                    )
                if (
                    event.warning_upstream_process_code is not None
                    and event.warning_upstream_process_code
                    != warning_relation.upstream_process_code
                ):
                    raise SnapshotConversionError(
                        f"Active cutline event {event.event_id} "
                        "warning_upstream_process_code conflicts with "
                        f"warning_buffer_code {event.warning_buffer_code}"
                    )
                if (
                    event.warning_downstream_process_code is not None
                    and event.warning_downstream_process_code
                    != warning_relation.downstream_process_code
                ):
                    raise SnapshotConversionError(
                        f"Active cutline event {event.event_id} "
                        "warning_downstream_process_code conflicts with "
                        f"warning_buffer_code {event.warning_buffer_code}"
                    )

            source_order = order_by_code[event.source_order_code]
            source_product = product_by_code[source_order.product_code]
            if (
                event.source_wafer_size is not None
                and event.source_wafer_size != source_product.wafer_size
            ):
                raise SnapshotConversionError(
                    f"Active cutline event {event.event_id} source_wafer_size "
                    f"{event.source_wafer_size!r} conflicts with source order "
                    f"product wafer_size {source_product.wafer_size!r}"
                )

            negative_start_time = (
                self._normalize_active_event_time(
                    event.event_id,
                    "negative_start_time",
                    event.negative_start_time,
                    snapshot_time,
                )
                if event.negative_start_time is not None
                else None
            )
            cutline_start_time = self._normalize_active_event_time(
                event.event_id,
                "cutline_start_time",
                event.cutline_start_time,
                snapshot_time,
            )
            result.append(
                AlgorithmActiveCutlineEvent(
                    event_id=event.event_id,
                    plan_id=event.plan_id,
                    warning_id=event.warning_id,
                    machine_code=event.machine_code,
                    source_order_code=event.source_order_code,
                    target_order_code=event.target_order_code,
                    workshop_code=event.workshop_code,
                    source_buffer_code=event.source_buffer_code,
                    target_buffer_code=event.target_buffer_code,
                    upstream_process_code=event.upstream_process_code,
                    downstream_process_code=event.downstream_process_code,
                    source_wafer_size=event.source_wafer_size,
                    source_wafer_spec=event.source_wafer_spec,
                    target_wafer_size=event.target_wafer_size,
                    target_wafer_spec=event.target_wafer_spec,
                    cutline_start_time=cutline_start_time,
                    negative_start_time=negative_start_time,
                    status=event.status,
                    contribution_capacity=event.contribution_capacity,
                    warning_type=event.warning_type,
                    process_code=event.process_code,
                    warning_buffer_code=event.warning_buffer_code,
                    warning_upstream_process_code=(
                        event.warning_upstream_process_code
                    ),
                    warning_downstream_process_code=(
                        event.warning_downstream_process_code
                    ),
                    is_recommended_candidate=(
                        event.is_recommended_candidate
                    ),
                )
            )

        return result

    def _normalize_active_event_time(
        self,
        event_id: str,
        field: str,
        event_time: datetime,
        snapshot_time: datetime,
    ) -> datetime:
        normalized_event_time = normalize_local_time(event_time)
        normalized_snapshot_time = normalize_local_time(snapshot_time)
        if normalized_event_time > normalized_snapshot_time:
            raise SnapshotConversionError(
                f"Active cutline event {event_id} {field} "
                f"{normalized_event_time.isoformat()} is later than "
                f"snapshot_time {normalized_snapshot_time.isoformat()}"
            )
        return normalized_event_time

    def _index_unique(
        self, items: Iterable[ModelT], field: str, label: str
    ) -> dict[str, ModelT]:
        result: dict[str, ModelT] = {}
        for item in items:
            key = getattr(item, field)
            if key in result:
                raise SnapshotConversionError(f"{key} duplicate {label}")
            result[key] = item
        return result

    def _index_process_routes(
        self, routes: Iterable[AlgorithmProcessRoute]
    ) -> dict[tuple[str, str, str], AlgorithmProcessRoute]:
        result: dict[tuple[str, str, str], AlgorithmProcessRoute] = {}
        for route in routes:
            key = (route.workshop_code, route.loop_code, route.process_code)
            if key in result:
                raise SnapshotConversionError(
                    f"{route.workshop_code} {route.loop_code} {route.process_code} duplicate process route"
                )
            result[key] = route
        return result
