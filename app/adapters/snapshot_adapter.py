"""Convert backend snapshot requests into algorithm-owned snapshot models."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable, TypeVar

from pydantic import ValidationError

from app.adapters.agv_binding_selector import select_latest_effective_bindings
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
            workshops = self._convert_workshops(request.workshops)
            workshop_by_code = self._index_unique(
                workshops, "workshop_code", "workshop"
            )

            lines = self._convert_lines(request.lines, workshop_by_code)
            line_by_code = self._index_unique(lines, "line_code", "line")

            machine_masters = self._convert_machine_masters(request.machine_master)
            machine_by_code = self._index_unique(
                machine_masters, "machine_code", "machine"
            )

            products = self._convert_products(request.products)
            product_by_code = self._index_unique(
                products, "product_code", "product"
            )

            orders = self._convert_orders(
                request.orders, workshop_by_code, product_by_code
            )
            order_by_code = self._index_unique(orders, "order_code", "order")

            machine_lines = self._convert_machine_lines(
                request.machine_lines, machine_by_code, line_by_code
            )
            agv_relations = self._convert_agv_relations(
                request.agv_relations,
                snapshot_time=request.snapshot_meta.snapshot_time,
                machine_by_code=machine_by_code,
                order_by_code=order_by_code,
            )
            agv_by_machine = self._index_unique(
                agv_relations,
                "machine_code",
                "selected AGV binding",
            )
            machine_runtimes = self._convert_machine_runtimes(
                request.machine_realtime,
                machine_by_code,
                agv_by_machine,
            )
            self._validate_runtime_machine_lines(machine_runtimes, machine_lines)
            capacities = self._convert_capacities(
                request.machine_process_times, machine_by_code, product_by_code
            )

            process_routes = self._convert_process_routes(
                request.process_routes, workshop_by_code
            )
            route_by_key = self._index_process_routes(process_routes)

            buffer_masters = self._convert_buffer_masters(request.buffer_master)
            buffer_by_code = self._index_unique(
                buffer_masters, "buffer_code", "buffer"
            )
            buffer_process_relations = self._build_buffer_process_relations(
                buffer_masters, process_routes, route_by_key
            )
            relation_by_buffer = self._index_unique(
                buffer_process_relations, "buffer_code", "buffer process relation"
            )
            buffer_order_inventories = self._convert_buffer_order_inventories(
                request.buffer_realtime,
                orders,
                buffer_by_code,
                relation_by_buffer,
            )

            active_cutline_events = self._convert_active_cutline_events(
                request.active_cutline_events,
                snapshot_time=request.snapshot_meta.snapshot_time,
                machine_by_code=machine_by_code,
                order_by_code=order_by_code,
                workshop_by_code=workshop_by_code,
                buffer_by_code=buffer_by_code,
                process_routes=process_routes,
            )

            return AlgorithmSnapshot(
                current_time=request.snapshot_meta.snapshot_time,
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
                active_cutline_events=active_cutline_events,
                config=AlgorithmConfig(),
            )
        except SnapshotConversionError:
            raise
        except (ValidationError, ValueError) as exc:
            raise SnapshotConversionError(
                f"Snapshot model validation failed: {exc}"
            ) from exc

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

    def _convert_machine_masters(
        self, source: Iterable[Any]
    ) -> list[AlgorithmMachineMaster]:
        return [
            AlgorithmMachineMaster(
                machine_code=item.machine_code,
                machine_name=item.machine_name,
                process_code=item.process_code,
                process_name=item.process_name,
            )
            for item in source
        ]

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
        machine_by_code: dict[str, AlgorithmMachineMaster],
        agv_by_machine: dict[str, AlgorithmAgvRelation],
    ) -> list[AlgorithmMachineRuntime]:
        result: list[AlgorithmMachineRuntime] = []
        seen_machine_codes: set[str] = set()
        for item in source:
            if item.machine_code in seen_machine_codes:
                raise SnapshotConversionError(
                    f"Duplicate machine runtime: {item.machine_code}"
                )
            seen_machine_codes.add(item.machine_code)
            if item.machine_code not in machine_by_code:
                raise SnapshotConversionError(
                    f"{item.machine_code} machine does not exist for machine runtime"
                )
            status = self._map_machine_status(item.status)
            binding = agv_by_machine.get(item.machine_code)
            if status == "running" and binding is None:
                raise SnapshotConversionError(
                    f"{item.machine_code} running machine has no effective AGV "
                    "binding at snapshot_time"
                )
            result.append(
                AlgorithmMachineRuntime(
                    machine_code=item.machine_code,
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

    def _validate_runtime_machine_lines(
        self,
        machine_runtimes: Iterable[AlgorithmMachineRuntime],
        machine_lines: Iterable[AlgorithmMachineLineRelation],
    ) -> None:
        line_relation_machine_codes = {
            relation.machine_code for relation in machine_lines
        }
        for runtime in machine_runtimes:
            if runtime.machine_code not in line_relation_machine_codes:
                raise SnapshotConversionError(
                    f"Machine {runtime.machine_code} has no machine-line relation"
                )

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
        product_by_code: dict[str, AlgorithmProduct],
    ) -> list[AlgorithmOrder]:
        result: list[AlgorithmOrder] = []
        for item in source:
            order_name = item.order_name.strip() if item.order_name else ""
            if not order_name:
                raise SnapshotConversionError(
                    f"Order {item.order_code} name is required"
                )
            if item.product_code not in product_by_code:
                raise SnapshotConversionError(
                    f"{item.product_code} product does not exist for order {item.order_code}"
                )
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
                    order_name=order_name,
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
        route_by_key: dict[tuple[str, str, str], AlgorithmProcessRoute],
    ) -> list[AlgorithmBufferProcessRelation]:
        # Keep the complete key index as part of the adapter contract and use it to
        # derive loop/process candidates without guessing a workshop.
        all_routes = list(routes)
        if len(route_by_key) != len(all_routes):
            raise SnapshotConversionError("Process route index is incomplete")

        result: list[AlgorithmBufferProcessRelation] = []
        for buffer in buffers:
            upstream_code, downstream_code = buffer.served_process_codes
            upstream_candidates = [
                route
                for route in all_routes
                if route.loop_code == buffer.loop_code
                and route.process_code == upstream_code
            ]
            downstream_candidates = [
                route
                for route in all_routes
                if route.loop_code == buffer.loop_code
                and route.process_code == downstream_code
            ]
            if not upstream_candidates:
                raise SnapshotConversionError(
                    f"Buffer {buffer.buffer_code} process {upstream_code} has no route in loop {buffer.loop_code}"
                )
            if not downstream_candidates:
                raise SnapshotConversionError(
                    f"Buffer {buffer.buffer_code} process {downstream_code} has no route in loop {buffer.loop_code}"
                )

            pairs = [
                (upstream, downstream)
                for upstream in upstream_candidates
                for downstream in downstream_candidates
                if upstream.workshop_code == downstream.workshop_code
            ]
            if not pairs:
                raise SnapshotConversionError(
                    f"Buffer {buffer.buffer_code} served processes must belong to the same workshop"
                )
            if len(pairs) > 1:
                raise SnapshotConversionError(
                    f"Buffer {buffer.buffer_code} process routes match multiple workshops"
                )

            upstream, downstream = pairs[0]
            if upstream.sequence >= downstream.sequence:
                raise SnapshotConversionError(
                    f"Buffer {buffer.buffer_code} upstream sequence must precede downstream sequence"
                )
            if downstream.sequence != upstream.sequence + 1:
                raise SnapshotConversionError(
                    f"Buffer {buffer.buffer_code} served processes must be adjacent"
                )
            result.append(
                AlgorithmBufferProcessRelation(
                    buffer_code=buffer.buffer_code,
                    workshop_code=upstream.workshop_code,
                    upstream_process_code=upstream_code,
                    downstream_process_code=downstream_code,
                )
            )
        return result

    def _convert_buffer_order_inventories(
        self,
        source: Iterable[Any],
        orders: Iterable[AlgorithmOrder],
        buffer_by_code: dict[str, AlgorithmBufferMaster],
        relation_by_buffer: dict[str, AlgorithmBufferProcessRelation],
    ) -> list[AlgorithmBufferOrderInventory]:
        orders_by_workshop_and_name: dict[
            tuple[str, str], list[AlgorithmOrder]
        ] = defaultdict(list)
        for order in orders:
            orders_by_workshop_and_name[
                (order.workshop_code, order.order_name)
            ].append(order)

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
            if not source_name:
                raise SnapshotConversionError(
                    f"Buffer {item.buffer_code} source name is required"
                )
            matches = orders_by_workshop_and_name.get(
                (relation.workshop_code, source_name), []
            )
            if not matches:
                raise SnapshotConversionError(
                    f"Buffer {item.buffer_code} source name {source_name} did not match an order"
                )
            if len(matches) > 1:
                raise SnapshotConversionError(
                    f"Buffer {item.buffer_code} source name {source_name} matched multiple orders"
                )
            order = matches[0]

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
        machine_by_code: dict[str, AlgorithmMachineMaster],
        order_by_code: dict[str, AlgorithmOrder],
    ) -> list[AlgorithmAgvRelation]:
        effective_by_machine = select_latest_effective_bindings(
            source,
            snapshot_time,
        )

        result: list[AlgorithmAgvRelation] = []
        for machine_code, (latest_time, latest) in effective_by_machine.items():
            order_codes = {item.order_code for item in latest}
            if len(order_codes) > 1:
                raise SnapshotConversionError(
                    f"{machine_code} latest AGV order_code conflict at "
                    f"{latest_time.isoformat()}: {sorted(order_codes)}"
                )
            order_names = {item.order_name for item in latest}
            if len(order_names) > 1:
                raise SnapshotConversionError(
                    f"{machine_code} latest AGV order_name conflict at "
                    f"{latest_time.isoformat()}: {sorted(order_names)}"
                )

            machine = machine_by_code.get(machine_code)
            if machine is None:
                raise SnapshotConversionError(
                    f"{machine_code} machine does not exist for selected AGV binding"
                )
            invalid_machine_names = sorted(
                {
                    item.machine_name
                    for item in latest
                    if item.machine_name != machine.machine_name
                }
            )
            if invalid_machine_names:
                raise SnapshotConversionError(
                    f"{machine_code} AGV machine_name "
                    f"{invalid_machine_names[0]!r} does not match machine "
                    f"master {machine.machine_name!r}"
                )

            order_code = next(iter(order_codes))
            order = order_by_code.get(order_code)
            if order is None:
                raise SnapshotConversionError(
                    f"{order_code} order does not exist for selected AGV "
                    f"binding on machine {machine_code}"
                )
            order_name = next(iter(order_names))
            if order_name != order.order_name:
                raise SnapshotConversionError(
                    f"{order_code} AGV order_name {order_name!r} does not "
                    f"match order master {order.order_name!r}"
                )

            result.append(
                AlgorithmAgvRelation(
                    machine_code=machine_code,
                    machine_name=machine.machine_name,
                    order_code=order_code,
                    order_name=order.order_name,
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
        workshop_by_code: dict[str, AlgorithmWorkshop],
        buffer_by_code: dict[str, AlgorithmBufferMaster],
        process_routes: Iterable[AlgorithmProcessRoute],
    ) -> list[AlgorithmActiveCutlineEvent]:
        routes = list(process_routes)
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

            self._validate_active_event_time(
                event.event_id,
                "negative_start_time",
                event.negative_start_time,
                snapshot_time,
            )
            self._validate_active_event_time(
                event.event_id,
                "cutline_start_time",
                event.cutline_start_time,
                snapshot_time,
            )
            result.append(
                AlgorithmActiveCutlineEvent(
                    event_id=event.event_id,
                    machine_code=event.machine_code,
                    source_order_code=event.source_order_code,
                    target_order_code=event.target_order_code,
                    workshop_code=event.workshop_code,
                    target_buffer_code=event.target_buffer_code,
                    upstream_process_code=event.upstream_process_code,
                    downstream_process_code=event.downstream_process_code,
                    target_wafer_size=event.target_wafer_size,
                    target_wafer_spec=event.target_wafer_spec,
                    cutline_start_time=event.cutline_start_time,
                    negative_start_time=event.negative_start_time,
                    status="active",
                )
            )

        return result

    def _validate_active_event_time(
        self,
        event_id: str,
        field: str,
        event_time: datetime | None,
        snapshot_time: datetime,
    ) -> None:
        if event_time is None:
            return

        event_is_aware = event_time.utcoffset() is not None
        snapshot_is_aware = snapshot_time.utcoffset() is not None
        if event_is_aware != snapshot_is_aware:
            raise SnapshotConversionError(
                f"Active cutline event {event_id} {field} cannot be compared "
                f"with snapshot_time because timezone awareness differs"
            )
        if event_time > snapshot_time:
            raise SnapshotConversionError(
                f"Active cutline event {event_id} {field} {event_time.isoformat()} "
                f"is later than snapshot_time {snapshot_time.isoformat()}"
            )

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
