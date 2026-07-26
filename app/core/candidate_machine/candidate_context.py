from __future__ import annotations

from typing import Iterable, TypeVar

from app.core.candidate_machine.errors import CandidateMachineCalculationError
from app.schemas.common_schema import (
    AlgorithmAgvRelation,
    AlgorithmBufferProcessRelation,
    AlgorithmLine,
    AlgorithmMachineLineRelation,
    AlgorithmMachineMaster,
    AlgorithmMachineRuntime,
    AlgorithmOrder,
    AlgorithmProduct,
)
from app.schemas.request_schema import AlgorithmSnapshot


ModelT = TypeVar("ModelT")


class CandidateContext:
    """新版候选筛选共用的唯一索引和引用解析上下文。"""

    def __init__(self, snapshot: AlgorithmSnapshot):
        self.runtime_by_machine_code = self._unique_index(
            snapshot.machine_runtimes,
            "machine_code",
            "machine runtime",
        )
        self.machine_by_code = self._unique_index(
            snapshot.machine_masters,
            "machine_code",
            "machine master",
        )
        self.line_by_code = self._unique_index(
            snapshot.lines,
            "line_code",
            "line",
        )
        self.order_by_code = self._unique_index(
            snapshot.orders,
            "order_code",
            "order",
        )
        self.product_by_code = self._unique_index(
            snapshot.products,
            "product_code",
            "product",
        )
        self.buffer_relation_by_code = self._unique_index(
            snapshot.buffer_process_relations,
            "buffer_code",
            "buffer process relation",
        )
        self.agv_by_machine_code = self._unique_index(
            snapshot.agv_relations,
            "machine_code",
            "AGV relation",
        )
        self.machine_line_by_machine_code = self._machine_line_index(
            snapshot.machine_lines
        )
        self._validate_references()

    def _unique_index(
        self,
        items: Iterable[ModelT],
        field_name: str,
        label: str,
    ) -> dict[str, ModelT]:
        result: dict[str, ModelT] = {}
        for item in items:
            key = getattr(item, field_name)
            if key in result:
                raise CandidateMachineCalculationError(
                    f"{key} duplicate {label}"
                )
            result[key] = item
        return result

    def _machine_line_index(
        self,
        relations: Iterable[AlgorithmMachineLineRelation],
    ) -> dict[str, AlgorithmMachineLineRelation]:
        result: dict[str, AlgorithmMachineLineRelation] = {}
        for relation in relations:
            if relation.machine_code in result:
                raise CandidateMachineCalculationError(
                    f"{relation.machine_code} has multiple machine-line relations"
                )
            if relation.machine_code not in self.machine_by_code:
                raise CandidateMachineCalculationError(
                    f"{relation.machine_code} machine master does not exist "
                    "for machine-line relation"
                )
            if relation.line_code not in self.line_by_code:
                raise CandidateMachineCalculationError(
                    f"{relation.line_code} line does not exist for machine "
                    f"{relation.machine_code}"
                )
            result[relation.machine_code] = relation
        return result

    def _validate_references(self) -> None:
        for runtime in self.runtime_by_machine_code.values():
            if runtime.machine_code not in self.machine_by_code:
                raise CandidateMachineCalculationError(
                    f"{runtime.machine_code} machine master does not exist "
                    "for machine runtime"
                )
            if runtime.machine_code not in self.machine_line_by_machine_code:
                raise CandidateMachineCalculationError(
                    f"{runtime.machine_code} machine-line relation does not exist "
                    "for machine runtime"
                )

        for relation in self.agv_by_machine_code.values():
            if relation.machine_code not in self.machine_by_code:
                raise CandidateMachineCalculationError(
                    f"{relation.machine_code} machine master does not exist "
                    "for AGV relation"
                )
            if relation.order_code not in self.order_by_code:
                raise CandidateMachineCalculationError(
                    f"{relation.order_code} order does not exist for "
                    f"AGV relation {relation.machine_code}"
                )

        for order in self.order_by_code.values():
            if order.product_code not in self.product_by_code:
                raise CandidateMachineCalculationError(
                    f"{order.product_code} product does not exist for order "
                    f"{order.order_code}"
                )

    def machine_context(
        self,
        machine_code: str,
    ) -> tuple[AlgorithmMachineRuntime, AlgorithmMachineMaster, AlgorithmLine]:
        runtime = self.runtime_by_machine_code[machine_code]
        machine = self.machine_by_code[machine_code]
        relation = self.machine_line_by_machine_code[machine_code]
        line = self.line_by_code[relation.line_code]
        return runtime, machine, line

    def order_product(
        self,
        order_code: str,
    ) -> tuple[AlgorithmOrder, AlgorithmProduct]:
        order = self.order_by_code.get(order_code)
        if order is None:
            raise CandidateMachineCalculationError(
                f"{order_code} order does not exist"
            )
        product = self.product_by_code[order.product_code]
        return order, product

    def candidate_agv(self, machine_code: str) -> AlgorithmAgvRelation:
        relation = self.agv_by_machine_code.get(machine_code)
        if relation is None:
            raise CandidateMachineCalculationError(
                f"{machine_code} running candidate has no AGV relation"
            )
        return relation

    def validate_warning_relation(self, warning) -> AlgorithmBufferProcessRelation:
        relation = self.buffer_relation_by_code.get(warning.buffer_code)
        if relation is None:
            raise CandidateMachineCalculationError(
                f"{warning.buffer_code} buffer process relation does not exist"
            )
        expected = (
            warning.workshop_code,
            warning.upstream_process_code,
            warning.downstream_process_code,
        )
        actual = (
            relation.workshop_code,
            relation.upstream_process_code,
            relation.downstream_process_code,
        )
        if actual != expected:
            raise CandidateMachineCalculationError(
                f"{warning.buffer_code} warning interval does not match buffer "
                f"process relation: warning={expected}, relation={actual}"
            )
        return relation
