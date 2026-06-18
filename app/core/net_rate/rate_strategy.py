# 速率取数策略：把"实时速率→近30min量×2→静态产能"三级链显式化为可替换策略

from abc import ABC, abstractmethod

from app.schemas.common_schema import MachineRuntimeStatus
from app.utils.numeric import safe_float


class RateStrategy(ABC):
    """机台吞入/产出速率取数策略。"""

    @abstractmethod
    def input_rate(self, machine: MachineRuntimeStatus) -> float:
        ...

    @abstractmethod
    def output_rate(self, machine: MachineRuntimeStatus) -> float:
        ...


class RealtimeFirstRateStrategy(RateStrategy):
    """默认口径：实时速率优先，其次近30min量×2，再次静态产能，最后 0.0。"""

    def input_rate(self, machine: MachineRuntimeStatus) -> float:
        if machine.input_rate_per_hour is not None:
            return safe_float(machine.input_rate_per_hour)
        if machine.input_quantity_30min is not None:
            return safe_float(machine.input_quantity_30min) * 2
        if machine.actual_capacity_per_hour is not None:
            return safe_float(machine.actual_capacity_per_hour)
        return 0.0

    def output_rate(self, machine: MachineRuntimeStatus) -> float:
        if machine.output_rate_per_hour is not None:
            return safe_float(machine.output_rate_per_hour)
        if machine.out_quantity_30min is not None:
            return safe_float(machine.out_quantity_30min) * 2
        if machine.actual_capacity_per_hour is not None:
            return safe_float(machine.actual_capacity_per_hour)
        return 0.0
