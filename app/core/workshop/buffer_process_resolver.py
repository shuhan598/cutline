"""从 Buffer Master 与工艺路线解析权威工艺区间和车间。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


class BufferProcessResolutionError(ValueError):
    """Buffer 无法映射到唯一且无歧义的工艺区间。"""


class ProcessRouteView(Protocol):
    """类 【ProcessRouteView】 封装该领域的数据或服务能力，对外提供稳定的业务契约。"""
    process_code: str
    sequence: int
    workshop_code: str


class BufferMasterView(Protocol):
    """类 【BufferMasterView】 封装该领域的数据或服务能力，对外提供稳定的业务契约。"""
    buffer_code: str
    served_process_codes: list[str]


@dataclass(frozen=True)
class BufferProcessResolution:
    """类 【BufferProcessResolution】 封装该领域的数据或服务能力，对外提供稳定的业务契约。"""
    workshop_code: str
    upstream_process_code: str
    downstream_process_code: str


class BufferProcessResolver:
    """在适配转换和校验中统一应用车间与工艺解析规则。"""

    def __init__(self, routes: Iterable[ProcessRouteView]):
        """初始化【__init__】对象的状态、索引和依赖。"""
        self._routes = list(routes)

    def resolve(self, buffer: BufferMasterView) -> BufferProcessResolution:
        """根据当前快照和业务规则执行【resolve】计算，返回类型标注所声明的结果。"""
        if len(buffer.served_process_codes) != 2:
            raise BufferProcessResolutionError(
                f"Buffer {buffer.buffer_code} must serve exactly two processes"
            )

        first_code, second_code = buffer.served_process_codes
        first_candidates = [
            route
            for route in self._routes
            if route.process_code == first_code
        ]
        second_candidates = [
            route
            for route in self._routes
            if route.process_code == second_code
        ]
        if not first_candidates:
            raise BufferProcessResolutionError(
                f"Buffer {buffer.buffer_code} process {first_code} has no route"
            )
        if not second_candidates:
            raise BufferProcessResolutionError(
                f"Buffer {buffer.buffer_code} process {second_code} has no route"
            )

        pairs = [
            (first, second)
            for first in first_candidates
            for second in second_candidates
            if first.workshop_code == second.workshop_code
        ]
        if not pairs:
            raise BufferProcessResolutionError(
                f"Buffer {buffer.buffer_code} served processes {first_code} "
                f"and {second_code} must belong to the same workshop"
            )
        if len(pairs) > 1:
            raise BufferProcessResolutionError(
                f"Buffer {buffer.buffer_code} process routes for {first_code} "
                f"and {second_code} match multiple workshop pairs"
            )

        first, second = pairs[0]
        if first.sequence == second.sequence:
            raise BufferProcessResolutionError(
                f"Buffer {buffer.buffer_code} served process routes have "
                "equal sequence"
            )
        upstream, downstream = sorted(
            (first, second),
            key=lambda route: route.sequence,
        )
        return BufferProcessResolution(
            workshop_code=upstream.workshop_code,
            upstream_process_code=upstream.process_code,
            downstream_process_code=downstream.process_code,
        )
