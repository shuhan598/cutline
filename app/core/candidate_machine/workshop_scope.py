from __future__ import annotations

from typing import Optional, Tuple

from app.core.workshop.workshop_resolver import WorkshopResolver
from app.schemas.common_schema import MachineRuntimeStatus
from app.schemas.request_schema import CutlineSnapshot


class WorkshopScopeChecker:
    """Check whether a candidate machine belongs to a warning's workshop."""

    def __init__(self, snapshot: CutlineSnapshot):
        self._resolver = WorkshopResolver(snapshot)

    def is_same_workshop(self, machine_status: MachineRuntimeStatus, warning) -> bool:
        warning_code, _ = self.resolve_warning_workshop(warning)
        machine_code, _ = self.resolve_machine_workshop(machine_status)
        return self._resolver.is_same_workshop(machine_code, warning_code)

    def resolve_warning_workshop(self, warning) -> Tuple[Optional[str], Optional[str]]:
        return self._resolver.resolve_warning_workshop(warning)

    def resolve_machine_workshop(
        self,
        machine_status: MachineRuntimeStatus,
    ) -> Tuple[Optional[str], Optional[str]]:
        return self._resolver.resolve_machine_workshop(machine_status)

    def _normalize_code(self, value: Optional[str]) -> str:
        return self._resolver.normalize_code(value)
