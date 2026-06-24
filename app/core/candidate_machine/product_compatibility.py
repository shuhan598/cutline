from __future__ import annotations

from typing import Optional

from app.core.workshop.workshop_resolver import WorkshopResolver
from app.schemas.common_schema import (
    MachineMaster,
    MachineRuntimeStatus,
    ProductModel,
)
from app.schemas.request_schema import CutlineSnapshot


class ProductCompatibilityChecker:
    """S2车间产品P/R兼容性检查"""

    def __init__(self, snapshot: CutlineSnapshot):
        self._snapshot = snapshot
        self._workshop_resolver = WorkshopResolver(snapshot)

    def is_compatible(
        self,
        machine_status: MachineRuntimeStatus,
        source_model: Optional[ProductModel],
        target_model: Optional[ProductModel],
    ) -> bool:
        if source_model is None or target_model is None:
            return False
        if not self._is_same_wafer_size(source_model, target_model):
            return False
        if self._is_same_shape(source_model, target_model):
            return True
        if not self._is_pr_pair(source_model.shape_code, target_model.shape_code):
            return False
        return self._is_s2_machine(machine_status) and self._is_before_silk_screen(
            machine_status
        )

    def _is_same_wafer_size(
        self,
        source_model: ProductModel,
        target_model: ProductModel,
    ) -> bool:
        return source_model.wafer_size == target_model.wafer_size

    def _is_same_shape(
        self,
        source_model: ProductModel,
        target_model: ProductModel,
    ) -> bool:
        return self._normalize_code(source_model.shape_code) == self._normalize_code(
            target_model.shape_code
        )

    def _is_pr_pair(
        self,
        source_shape_code: Optional[str],
        target_shape_code: Optional[str],
    ) -> bool:
        source_shape = self._normalize_code(source_shape_code)
        target_shape = self._normalize_code(target_shape_code)
        return {source_shape, target_shape} == {"P", "R"}

    def _is_s2_machine(self, machine_status: MachineRuntimeStatus) -> bool:
        workshop_code, workshop_name = self._workshop_resolver.resolve_machine_workshop(
            machine_status
        )
        if self._workshop_resolver.normalize_code(workshop_code) == "S2":
            return True
        return "S2" in self._normalize_text(workshop_name)

    def _is_before_silk_screen(self, machine_status: MachineRuntimeStatus) -> bool:
        process_name = self._resolve_process_name(machine_status)
        if not process_name:
            return False
        return "丝网" not in process_name

    def _find_machine_master(
        self,
        equipment_code: Optional[str],
    ) -> Optional[MachineMaster]:
        if not equipment_code:
            return None
        for machine_master in self._snapshot.machine_masters:
            if machine_master.equipment_code == equipment_code:
                return machine_master
        return None

    def _resolve_process_name(
        self,
        machine_status: MachineRuntimeStatus,
    ) -> Optional[str]:
        process_code = machine_status.process_code

        for route_step in self._snapshot.process_route_steps:
            if route_step.process_code == process_code and route_step.process_name:
                return route_step.process_name

        machine_master = self._find_machine_master(machine_status.equipment_code)
        if machine_master is not None and machine_master.process_name:
            return machine_master.process_name

        for machine_master in self._snapshot.machine_masters:
            if (
                machine_master.process_code == process_code
                and machine_master.process_name
            ):
                return machine_master.process_name
        return None

    def _normalize_code(self, value: Optional[str]) -> str:
        return self._workshop_resolver.normalize_code(value)

    def _normalize_text(self, value: Optional[str]) -> str:
        if value is None:
            return ""
        return value.strip().upper()
