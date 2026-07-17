"""Calculate AlgorithmSnapshot interval net consumption rates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, TypeVar

from app.schemas.common_schema import (
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
            self._calculate_inventory_net_rate(snapshot, inventory, context)
            for inventory in snapshot.buffer_order_inventories
        ]

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
            if (
                runtime.current_order_code is not None
                and runtime.current_order_code not in order_by_code
            ):
                raise NetRateCalculationError(
                    f"{runtime.current_order_code} order does not exist for runtime "
                    f"{runtime.machine_code}"
                )

        return _AlgorithmNetRateContext(
            machine_by_code=machine_by_code,
            machine_line_by_code=machine_line_by_code,
            line_by_code=line_by_code,
            order_by_code=order_by_code,
            product_by_code=product_by_code,
            buffer_relation_by_code=buffer_relation_by_code,
        )

    def _resolve_order_wafer_spec(
        self,
        order_code: str,
        machine_runtimes: Iterable[AlgorithmMachineRuntime],
        machine_line_by_code: dict[str, AlgorithmMachineLineRelation],
        line_by_code: dict[str, AlgorithmLine],
    ) -> str:
        wafer_specs = {
            line_by_code[machine_line_by_code[runtime.machine_code].line_code].wafer_spec
            for runtime in machine_runtimes
            if self._is_running(runtime) and runtime.current_order_code == order_code
        }
        if not wafer_specs:
            raise NetRateCalculationError(
                f"Order {order_code} wafer_spec cannot be determined: "
                "no running machine is currently producing this order; "
                "expected inference chain is machine -> line -> wafer_spec"
            )
        if len(wafer_specs) > 1:
            values = ", ".join(sorted(wafer_specs))
            raise NetRateCalculationError(
                f"Order {order_code} has multiple wafer_spec values: {values}"
            )
        return next(iter(wafer_specs))

    def _calculate_inventory_net_rate(
        self,
        snapshot: AlgorithmSnapshot,
        inventory: AlgorithmBufferOrderInventory,
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
            snapshot.machine_runtimes,
            context.machine_line_by_code,
            context.line_by_code,
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
            buffer_code=inventory.buffer_code,
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
            if runtime.current_order_code != order_code:
                continue
            machine = context.machine_by_code[runtime.machine_code]
            machine_line = context.machine_line_by_code[runtime.machine_code]
            line = context.line_by_code[machine_line.line_code]
            if line.wafer_spec != wafer_spec:
                continue
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
