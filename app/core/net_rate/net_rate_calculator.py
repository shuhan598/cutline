"""Calculate AlgorithmSnapshot interval net consumption rates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, TypeVar

from app.schemas.common_schema import (
    AlgorithmAgvRelation,
    AlgorithmBufferOrderInventory,
    AlgorithmBufferProcessRelation,
    AlgorithmLine,
    AlgorithmMachineLineRelation,
    AlgorithmMachineMaster,
    AlgorithmMachineRuntime,
    AlgorithmOrder,
    AlgorithmProduct,
)
from app.schemas.request_schema import AlgorithmSnapshot
from app.schemas.result_schema import AlgorithmIntervalNetRateResult


class NetRateCalculationError(ValueError):
    """区间净消耗速率无法计算时抛出的异常。"""


ModelT = TypeVar("ModelT")


@dataclass(frozen=True)
class _AlgorithmNetRateContext:
    machine_by_code: dict[str, AlgorithmMachineMaster]
    machine_line_by_code: dict[str, AlgorithmMachineLineRelation]
    line_by_code: dict[str, AlgorithmLine]
    order_by_code: dict[str, AlgorithmOrder]
    product_by_code: dict[str, AlgorithmProduct]
    buffer_relation_by_code: dict[str, AlgorithmBufferProcessRelation]
    agv_by_machine_code: dict[str, AlgorithmAgvRelation]


class NetRateCalculator:
    """Calculate interval net rates for an algorithm snapshot."""

    def calculate(
        self,
        snapshot: AlgorithmSnapshot,
    ) -> list[AlgorithmIntervalNetRateResult]:
        return self._calculate_algorithm_snapshot(snapshot)

    def _calculate_algorithm_snapshot(
        self,
        snapshot: AlgorithmSnapshot,
    ) -> list[AlgorithmIntervalNetRateResult]:
        context = self._build_machine_context(snapshot)
        return [
            self._calculate_inventory_net_rate(
                snapshot,
                inventory,
                buffer_codes,
                context,
            )
            for inventory, buffer_codes in self._group_buffer_inventories(
                snapshot.buffer_order_inventories,
                context,
            )
        ]

    def _group_buffer_inventories(
        self,
        inventories: Iterable[AlgorithmBufferOrderInventory],
        context: _AlgorithmNetRateContext,
    ) -> list[tuple[AlgorithmBufferOrderInventory, list[str]]]:
        quantities_by_group: dict[
            tuple[str, str, str, str, str], float
        ] = {}
        buffer_codes_by_group: dict[
            tuple[str, str, str, str, str], set[str]
        ] = {}
        interval_by_main_id: dict[str, tuple[str, str, str]] = {}
        main_id_by_buffer: dict[str, str] = {}
        seen_physical_inventory: set[tuple[str, str, str]] = set()

        for inventory in inventories:
            if not inventory.main_id.strip():
                raise NetRateCalculationError(
                    f"{inventory.buffer_code} buffer inventory main_id is blank"
                )
            relation = context.buffer_relation_by_code.get(
                inventory.buffer_code
            )
            if relation is None:
                raise NetRateCalculationError(
                    f"{inventory.buffer_code} process relation does not exist "
                    "for buffer inventory"
                )

            existing_main_id = main_id_by_buffer.get(inventory.buffer_code)
            if (
                existing_main_id is not None
                and existing_main_id != inventory.main_id
            ):
                raise NetRateCalculationError(
                    f"{inventory.buffer_code} buffer inventory belongs to "
                    f"multiple main_id values: {existing_main_id!r}, "
                    f"{inventory.main_id!r}"
                )
            main_id_by_buffer[inventory.buffer_code] = inventory.main_id

            physical_key = (
                inventory.main_id,
                inventory.buffer_code,
                inventory.order_code,
            )
            if physical_key in seen_physical_inventory:
                raise NetRateCalculationError(
                    f"{inventory.main_id} {inventory.buffer_code} "
                    f"{inventory.order_code} duplicate buffer inventory"
                )
            seen_physical_inventory.add(physical_key)

            interval = (
                relation.workshop_code,
                relation.upstream_process_code,
                relation.downstream_process_code,
            )
            expected_interval = interval_by_main_id.get(inventory.main_id)
            if expected_interval is None:
                interval_by_main_id[inventory.main_id] = interval
            elif expected_interval != interval:
                raise NetRateCalculationError(
                    f"{inventory.main_id} buffer group has multiple process "
                    f"intervals: {expected_interval!r}, {interval!r}"
                )

            group_key = (
                inventory.main_id,
                relation.workshop_code,
                relation.upstream_process_code,
                relation.downstream_process_code,
                inventory.order_code,
            )
            quantities_by_group[group_key] = (
                quantities_by_group.get(group_key, 0.0)
                + inventory.current_quantity
            )
            buffer_codes_by_group.setdefault(group_key, set()).add(
                inventory.buffer_code
            )

        grouped: list[
            tuple[AlgorithmBufferOrderInventory, list[str]]
        ] = []
        for group_key in sorted(quantities_by_group):
            main_id, _, _, _, order_code = group_key
            buffer_codes = sorted(buffer_codes_by_group[group_key])
            grouped.append(
                (
                    AlgorithmBufferOrderInventory(
                        main_id=main_id,
                        buffer_code=buffer_codes[0],
                        order_code=order_code,
                        current_quantity=quantities_by_group[group_key],
                    ),
                    buffer_codes,
                )
            )
        return grouped

    def _build_machine_context(
        self,
        snapshot: AlgorithmSnapshot,
    ) -> _AlgorithmNetRateContext:
        machine_by_code = self._unique_index(
            snapshot.machine_masters,
            "machine_code",
            "machine master",
        )
        line_by_code = self._unique_index(snapshot.lines, "line_code", "line")
        order_by_code = self._unique_index(snapshot.orders, "order_code", "order")
        product_by_code = self._unique_index(
            snapshot.products,
            "product_code",
            "product",
        )
        agv_by_machine_code = self._unique_index(
            snapshot.agv_relations,
            "machine_code",
            "AGV relation",
        )

        machine_line_by_code: dict[str, AlgorithmMachineLineRelation] = {}
        for relation in snapshot.machine_lines:
            if relation.machine_code in machine_line_by_code:
                raise NetRateCalculationError(
                    f"{relation.machine_code} has multiple machine-line relations"
                )
            if relation.machine_code not in machine_by_code:
                raise NetRateCalculationError(
                    f"{relation.machine_code} machine master does not exist "
                    "for machine-line relation"
                )
            if relation.line_code not in line_by_code:
                raise NetRateCalculationError(
                    f"{relation.line_code} line does not exist for machine "
                    f"{relation.machine_code}"
                )
            machine_line_by_code[relation.machine_code] = relation

        buffer_relation_by_code: dict[str, AlgorithmBufferProcessRelation] = {}
        for relation in snapshot.buffer_process_relations:
            if relation.buffer_code in buffer_relation_by_code:
                raise NetRateCalculationError(
                    f"{relation.buffer_code} has multiple process relations"
                )
            buffer_relation_by_code[relation.buffer_code] = relation

        for runtime in snapshot.machine_runtimes:
            if runtime.machine_code not in machine_by_code:
                raise NetRateCalculationError(
                    f"{runtime.machine_code} machine master does not exist for runtime"
                )
            if runtime.machine_code not in machine_line_by_code:
                raise NetRateCalculationError(
                    f"{runtime.machine_code} machine-line relation does not exist "
                    "for runtime"
                )
        return _AlgorithmNetRateContext(
            machine_by_code=machine_by_code,
            machine_line_by_code=machine_line_by_code,
            line_by_code=line_by_code,
            order_by_code=order_by_code,
            product_by_code=product_by_code,
            buffer_relation_by_code=buffer_relation_by_code,
            agv_by_machine_code=agv_by_machine_code,
        )

    def _resolve_order_wafer_spec(
        self,
        order_code: str,
        agv_relations: Iterable[AlgorithmAgvRelation],
    ) -> str:
        matching_relations = sorted(
            (
                relation
                for relation in agv_relations
                if relation.order_code == order_code
            ),
            key=lambda relation: relation.machine_code,
        )
        if not matching_relations:
            raise NetRateCalculationError(
                f"Order {order_code} wafer_spec cannot be determined from "
                "snapshot.agv_relations: no effective AGV relation matches "
                f"order {order_code}"
            )
        return matching_relations[0].wafer_spec

    def _calculate_inventory_net_rate(
        self,
        snapshot: AlgorithmSnapshot,
        inventory: AlgorithmBufferOrderInventory,
        buffer_codes: list[str],
        context: _AlgorithmNetRateContext,
    ) -> AlgorithmIntervalNetRateResult:
        if inventory.order_code not in context.order_by_code:
            raise NetRateCalculationError(
                f"{inventory.order_code} order does not exist for buffer inventory"
            )
        order = context.order_by_code[inventory.order_code]
        product = context.product_by_code.get(order.product_code)
        if product is None:
            raise NetRateCalculationError(
                f"{order.product_code} product does not exist for order "
                f"{order.order_code}"
            )
        if (
            not isinstance(product.wafer_size, str)
            or not product.wafer_size.strip()
        ):
            raise NetRateCalculationError(
                f"{product.product_code} product wafer_size is missing"
            )
        relation = context.buffer_relation_by_code.get(inventory.buffer_code)
        if relation is None:
            raise NetRateCalculationError(
                f"{inventory.buffer_code} process relation does not exist "
                "for buffer inventory"
            )

        wafer_spec = self._resolve_order_wafer_spec(
            inventory.order_code,
            snapshot.agv_relations,
        )
        upstream_output_rate = self._calculate_upstream_output_rate(
            snapshot,
            inventory.order_code,
            wafer_spec,
            relation,
            context,
        )
        downstream_input_rate = self._calculate_downstream_input_rate(
            snapshot,
            inventory.order_code,
            wafer_spec,
            relation,
            context,
        )
        return AlgorithmIntervalNetRateResult(
            main_id=inventory.main_id,
            buffer_code=inventory.buffer_code,
            buffer_codes=list(buffer_codes),
            order_code=inventory.order_code,
            wafer_size=product.wafer_size,
            wafer_spec=wafer_spec,
            workshop_code=relation.workshop_code,
            upstream_process_code=relation.upstream_process_code,
            downstream_process_code=relation.downstream_process_code,
            current_quantity=inventory.current_quantity,
            upstream_output_rate=upstream_output_rate,
            downstream_input_rate=downstream_input_rate,
            net_consumption_rate=downstream_input_rate - upstream_output_rate,
        )

    def _calculate_upstream_output_rate(
        self,
        snapshot: AlgorithmSnapshot,
        order_code: str,
        wafer_spec: str,
        relation: AlgorithmBufferProcessRelation,
        context: _AlgorithmNetRateContext,
    ) -> float:
        return sum(
            runtime.output_quantity_30m
            for runtime in self._matching_runtimes(
                snapshot,
                order_code,
                wafer_spec,
                relation.workshop_code,
                relation.upstream_process_code,
                context,
            )
        ) * 2

    def _calculate_downstream_input_rate(
        self,
        snapshot: AlgorithmSnapshot,
        order_code: str,
        wafer_spec: str,
        relation: AlgorithmBufferProcessRelation,
        context: _AlgorithmNetRateContext,
    ) -> float:
        return sum(
            runtime.input_quantity_30m
            for runtime in self._matching_runtimes(
                snapshot,
                order_code,
                wafer_spec,
                relation.workshop_code,
                relation.downstream_process_code,
                context,
            )
        ) * 2

    def _matching_runtimes(
        self,
        snapshot: AlgorithmSnapshot,
        order_code: str,
        wafer_spec: str,
        workshop_code: str,
        process_code: str,
        context: _AlgorithmNetRateContext,
    ) -> Iterable[AlgorithmMachineRuntime]:
        for runtime in snapshot.machine_runtimes:
            if not self._is_running(runtime):
                continue
            agv_relation = context.agv_by_machine_code.get(
                runtime.machine_code
            )
            if agv_relation is None:
                continue
            if agv_relation.order_code != order_code:
                continue
            if agv_relation.wafer_spec != wafer_spec:
                continue
            machine = context.machine_by_code[runtime.machine_code]
            machine_line = context.machine_line_by_code[runtime.machine_code]
            line = context.line_by_code[machine_line.line_code]
            if line.workshop_code != workshop_code:
                continue
            if machine.process_code != process_code:
                continue
            yield runtime

    def _is_running(self, runtime: AlgorithmMachineRuntime) -> bool:
        return runtime.status == "running"

    def _unique_index(
        self,
        items: Iterable[ModelT],
        field: str,
        label: str,
    ) -> dict[str, ModelT]:
        result: dict[str, ModelT] = {}
        for item in items:
            key = getattr(item, field)
            if key in result:
                raise NetRateCalculationError(f"Duplicate {label}: {key}")
            result[key] = item
        return result
