"""管理 V6 正式评估按车间隔离的跨轮持久化状态。

算法输出中的待确认切线计划、活跃切线事件等状态需要在下一轮恢复。该组件采用
“开始、提交、终止”三段式操作：同一车间同一时刻仅允许一轮评估，只有算法成功
后才替换旧状态，从而避免失败计算写入半成品状态。
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from uuid import uuid4
from typing import Any


@dataclass(frozen=True)
class EvaluationState:
    """一次已开始评估的状态快照及其初始化标记。"""
    state_generation: str
    workshop_id: str
    state: dict[str, Any]
    state_reset: bool


class AlgorithmStateStore:
    """线程安全的车间状态仓库，提供单车间互斥与深拷贝隔离。"""
    def __init__(self, *, state_generation: str | None = None):
        """创建状态仓库；未指定时生成本进程生命周期内唯一的代际编号。"""
        self.state_generation = state_generation or uuid4().hex
        self._states: dict[str, dict[str, Any]] = {}
        self._in_flight: set[str] = set()
        self._lock = RLock()

    def begin(self, workshop_id: str) -> EvaluationState:
        """锁定车间并返回上一轮成功状态的副本。

        若车间已有进行中的评估则立即报错，调用方必须等待该轮结束后再提交，以免
        两轮结果以不可预期的顺序覆盖。
        """
        with self._lock:
            if workshop_id in self._in_flight:
                raise RuntimeError(f"workshop evaluation already running: {workshop_id}")
            self._in_flight.add(workshop_id)
            state = deepcopy(self._states.get(workshop_id, {}))
            return EvaluationState(
                self.state_generation,
                workshop_id,
                state,
                workshop_id not in self._states,
            )

    def commit(self, workshop_id: str, state: dict[str, Any]) -> None:
        """将本轮成功计算的状态原子写入，并释放该车间的评估锁。"""
        with self._lock:
            if workshop_id not in self._in_flight:
                raise RuntimeError(f"workshop evaluation was not started: {workshop_id}")
            self._states[workshop_id] = deepcopy(state)
            self._in_flight.remove(workshop_id)

    def abort(self, workshop_id: str) -> None:
        """放弃本轮未成功的评估，仅释放锁而不修改已保存状态。"""
        with self._lock:
            self._in_flight.discard(workshop_id)

    def get(self, workshop_id: str) -> dict[str, Any]:
        """读取指定车间的状态副本，供诊断或测试使用。"""
        with self._lock:
            return deepcopy(self._states.get(workshop_id, {}))

