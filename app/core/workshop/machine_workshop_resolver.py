"""Resolve a machine's authoritative workshop from its process routes."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from app.schemas.common_schema import (
    AlgorithmMachineMaster,
    AlgorithmProcessRoute,
)


class MachineWorkshopResolutionError(ValueError):
    """A machine process cannot be mapped to exactly one workshop."""


class MachineWorkshopResolver:
    """Resolve process and machine workshops using process-route authority."""

    def __init__(self, process_routes: Iterable[AlgorithmProcessRoute]):
        workshops_by_process: dict[str, set[str]] = defaultdict(set)
        for route in process_routes:
            workshops_by_process[route.process_code].add(
                route.workshop_code
            )
        self._workshops_by_process = {
            process_code: frozenset(workshop_codes)
            for process_code, workshop_codes in workshops_by_process.items()
        }

    def resolve_by_process_code(self, process_code: str) -> str:
        """Return the unique workshop for a process code."""
        workshop_codes = self._workshops_by_process.get(process_code)
        if not workshop_codes:
            raise MachineWorkshopResolutionError(
                f"Process {process_code} has no process route"
            )
        if len(workshop_codes) > 1:
            raise MachineWorkshopResolutionError(
                f"Process {process_code} belongs to multiple workshops: "
                f"{', '.join(sorted(workshop_codes))}"
            )
        return next(iter(workshop_codes))

    def resolve_machine_workshop(
        self,
        machine: AlgorithmMachineMaster,
    ) -> str:
        """Return a machine's workshop with machine-aware diagnostics."""
        workshop_codes = self._workshops_by_process.get(
            machine.process_code
        )
        if not workshop_codes:
            raise MachineWorkshopResolutionError(
                f"Machine {machine.machine_code} process "
                f"{machine.process_code} has no process route"
            )
        if len(workshop_codes) > 1:
            raise MachineWorkshopResolutionError(
                f"Machine {machine.machine_code} process "
                f"{machine.process_code} belongs to multiple workshops: "
                f"{', '.join(sorted(workshop_codes))}"
            )
        return next(iter(workshop_codes))
