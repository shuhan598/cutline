"""预构建候选机台筛选所需的快照索引和业务查询上下文。"""

from __future__ import annotations

from typing import Iterable, TypeVar

from app.core.candidate_machine.errors import CandidateMachineCalculationError
from app.core.workshop.machine_workshop_resolver import (
    MachineWorkshopResolutionError,
    MachineWorkshopResolver,
)
from app.schemas.common_schema import (
    AlgorithmAgvRelation,
    AlgorithmBufferProcessRelation,
    AlgorithmMachineMaster,
    AlgorithmMachineRuntime,
    AlgorithmOrder,
    AlgorithmProduct,
)
from app.schemas.request_schema import AlgorithmSnapshot
from app.core.buffer_aggregation.models import (
    GroupKey,
    MainBufferGroup,
    PhysicalBufferKey,
)


ModelT = TypeVar("ModelT")


class CandidateContext:
    """新版候选筛选共用的唯一索引和引用解析上下文。"""

    def __init__(self, snapshot: AlgorithmSnapshot):
        self.main_buffer_batch = snapshot.main_buffer_batch
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
        if self.main_buffer_batch.groups_by_group_key:
            self.buffer_relation_by_code = self._unambiguous_index(
                snapshot.buffer_process_relations,
                "buffer_code",
            )
        else:
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
        self.workshop_resolver = MachineWorkshopResolver(
            snapshot.process_routes
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

    def _unambiguous_index(
        self,
        items: Iterable[ModelT],
        field_name: str,
    ) -> dict[str, ModelT]:
        grouped: dict[str, list[ModelT]] = {}
        for item in items:
            grouped.setdefault(getattr(item, field_name), []).append(item)
        return {
            key: matches[0]
            for key, matches in grouped.items()
            if len(matches) == 1
        }

    def _validate_references(self) -> None:
        for runtime in self.runtime_by_machine_code.values():
            if runtime.machine_code not in self.machine_by_code:
                raise CandidateMachineCalculationError(
                    f"{runtime.machine_code} machine master does not exist "
                    "for machine runtime"
                )
            try:
                self.workshop_resolver.resolve_machine_workshop(
                    self.machine_by_code[runtime.machine_code]
                )
            except MachineWorkshopResolutionError as exc:
                raise CandidateMachineCalculationError(str(exc)) from exc

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
    ) -> tuple[AlgorithmMachineRuntime, AlgorithmMachineMaster]:
        runtime = self.runtime_by_machine_code[machine_code]
        machine = self.machine_by_code[machine_code]
        return runtime, machine

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

    def machine_workshop_code(self, machine_code: str) -> str:
        machine = self.machine_by_code[machine_code]
        try:
            return self.workshop_resolver.resolve_machine_workshop(machine)
        except MachineWorkshopResolutionError as exc:
            raise CandidateMachineCalculationError(str(exc)) from exc

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

    def warning_group(self, warning) -> MainBufferGroup | None:
        if not self.main_buffer_batch.groups_by_group_key:
            return None
        group_key = getattr(warning, "group_key", None)
        if group_key is None:
            group_key = self.main_buffer_batch.group_key_by_buffer_code.get(
                warning.buffer_code
            )
        if group_key is None:
            raise CandidateMachineCalculationError(
                f"{warning.buffer_code} warning main Buffer group cannot be located"
            )
        group = self.main_buffer_batch.groups_by_group_key.get(group_key)
        if group is None:
            raise CandidateMachineCalculationError(
                f"{group_key} warning main Buffer group does not exist"
            )
        return group

    def unique_group_for_order(
        self,
        physical_buffer_key: PhysicalBufferKey,
        order_code: str,
    ) -> MainBufferGroup | None:
        matches = [
            self.main_buffer_batch.groups_by_group_key[group_key]
            for group_key in self.main_buffer_batch.group_keys_by_physical_buffer_key.get(
                physical_buffer_key, ()
            )
            if group_key.order_code == order_code
            and self.main_buffer_batch.groups_by_group_key[
                group_key
            ].auto_donate_eligible
        ]
        return matches[0] if len(matches) == 1 else None
