"""把标准工序名称解析为所属车间和生产循环。"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping


class UnknownProcessNameError(ValueError):
    """工序名称未登记在中央循环目录中。"""


@dataclass(frozen=True, slots=True)
class ProcessLoopAssignment:
    """标准工序名称及其所属生产循环。"""

    process_name: str
    loop_code: str
    loop_name: str


_PROCESS_LOOP_CATALOG: Final[
    Mapping[str, ProcessLoopAssignment]
] = MappingProxyType(
    {
        "发料机": ProcessLoopAssignment("发料机", "LOOP1", "一循环"),
        "制绒": ProcessLoopAssignment("制绒", "LOOP2", "二循环"),
        "硼扩": ProcessLoopAssignment("硼扩", "LOOP2", "二循环"),
        "氧化": ProcessLoopAssignment("氧化", "LOOP2", "二循环"),
        "碱抛": ProcessLoopAssignment("碱抛", "LOOP3", "三循环"),
        "POLY": ProcessLoopAssignment("POLY", "LOOP3", "三循环"),
        "退火": ProcessLoopAssignment("退火", "LOOP3", "三循环"),
        "RCA": ProcessLoopAssignment("RCA", "LOOP4", "四循环"),
        "ALD": ProcessLoopAssignment("ALD", "LOOP5", "五循环"),
        "正膜": ProcessLoopAssignment("正膜", "LOOP5", "五循环"),
        "背膜": ProcessLoopAssignment("背膜", "LOOP5", "五循环"),
        "丝网": ProcessLoopAssignment("丝网", "LOOP5", "五循环"),
    }
)

_CASE_INSENSITIVE_PROCESS_NAMES = frozenset({"POLY", "RCA", "ALD"})


# 中文工序名严格匹配，英文缩写按不区分大小写规则归一，防止同一工序形成多个目录键。
def normalize_process_name(process_name: str) -> str:
    """去除工序名称空白，并标准化支持的 ASCII 缩写。"""
    normalized_name = process_name.strip()
    uppercase_name = normalized_name.upper()
    if uppercase_name in _CASE_INSENSITIVE_PROCESS_NAMES:
        return uppercase_name
    return normalized_name


# 从集中维护的工序目录取得循环归属；未知名称必须失败，避免使用猜测的车间或循环。
def resolve_process_loop(process_name: str) -> ProcessLoopAssignment:
    """返回工序在中央目录中的精确循环分配。"""
    normalized_name = normalize_process_name(process_name)
    assignment = _PROCESS_LOOP_CATALOG.get(normalized_name)
    if assignment is None:
        raise UnknownProcessNameError(
            f"Unknown process name: {process_name!r}"
        )
    return assignment
