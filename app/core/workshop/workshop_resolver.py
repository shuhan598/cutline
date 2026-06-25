from __future__ import annotations

from typing import Optional, Tuple

from app.schemas.common_schema import (
    BufferInventoryItem,
    CycleMaster,
    LineMaster,
    MachineMaster,
    MachineRuntimeStatus,
)
from app.schemas.request_schema import CutlineSnapshot


class WorkshopResolver:
    """通过循环和产线查找车间解析器"""

    def __init__(self, snapshot: CutlineSnapshot):
        self._snapshot = snapshot

    def resolve_cycle_workshop(
        self,
        cycle_code: Optional[str],
    ) -> Tuple[Optional[str], Optional[str]]:
        cycle_master = self._find_cycle_master(cycle_code)
        if cycle_master is None:
            return None, None
        return cycle_master.workshop_code, cycle_master.workshop_name

    def resolve_inventory_workshop(
        self,
        inventory: BufferInventoryItem,
    ) -> Tuple[Optional[str], Optional[str]]:
        return self.resolve_cycle_workshop(inventory.cycle_code)

    def resolve_warning_workshop(self, warning) -> Tuple[Optional[str], Optional[str]]:
        cycle_code = getattr(warning, "cycle_code", None)
        cycle_workshop_code, cycle_workshop_name = self.resolve_cycle_workshop(cycle_code)
        return (
            getattr(warning, "workshop_code", None) or cycle_workshop_code,
            getattr(warning, "workshop_name", None) or cycle_workshop_name,
        )

    def resolve_machine_workshop(
        self,
        machine_status: MachineRuntimeStatus,
    ) -> Tuple[Optional[str], Optional[str]]:
        machine_master = self._find_machine_master(machine_status.equipment_code)
        if machine_master is None:
            return None, None

        line_master = self._find_line_master(machine_master.line_code)
        if line_master is None:
            return None, None
        return line_master.workshop_code, line_master.workshop_name

    def is_same_workshop(
        self,
        left_code: Optional[str],
        right_code: Optional[str],
    ) -> bool:
        left = self.normalize_code(left_code)
        right = self.normalize_code(right_code)
        if not left or not right:
            return False
        return left == right

    def normalize_code(self, value: Optional[str]) -> str:
        if value is None:
            return ""
        return value.strip().upper()

    def _find_cycle_master(self, cycle_code: Optional[str]) -> Optional[CycleMaster]:
        if not cycle_code:
            return None
        for cycle_master in self._snapshot.cycle_masters:
            if cycle_master.cycle_code == cycle_code:
                return cycle_master
        return None

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

    def _find_line_master(self, line_code: Optional[str]) -> Optional[LineMaster]:
        if not line_code:
            return None
        for line_master in self._snapshot.line_masters:
            if line_master.line_code == line_code:
                return line_master
        return None
