"""依据工艺路线解析机台的权威车间，不依赖 line 关系。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from app.schemas.common_schema import (
    AlgorithmMachineMaster,
    AlgorithmProcessRoute,
)


class MachineWorkshopResolutionError(ValueError):
    """机台工序无法映射到唯一车间。"""


class MachineWorkshopResolver:
    """以工艺路线为权威来源解析工序和机台所属车间。"""

    def __init__(self, process_routes: Iterable[AlgorithmProcessRoute]):
        """初始化【__init__】对象的状态、索引和依赖。"""
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
        """返回指定工序编码唯一对应的车间。"""
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
        """返回机台所属车间，并在失败时提供机台维度诊断。"""
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
