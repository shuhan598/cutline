"""Resolve canonical workshop process names to their production loops."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping


class UnknownProcessNameError(ValueError):
    """A process name is not present in the central loop catalog."""


@dataclass(frozen=True, slots=True)
class ProcessLoopAssignment:
    """The canonical process name and its assigned production loop."""

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


def normalize_process_name(process_name: str) -> str:
    """Trim a process name and canonicalize supported ASCII acronyms."""
    normalized_name = process_name.strip()
    uppercase_name = normalized_name.upper()
    if uppercase_name in _CASE_INSENSITIVE_PROCESS_NAMES:
        return uppercase_name
    return normalized_name


def resolve_process_loop(process_name: str) -> ProcessLoopAssignment:
    """Return the exact central-catalog loop assignment for a process."""
    normalized_name = normalize_process_name(process_name)
    assignment = _PROCESS_LOOP_CATALOG.get(normalized_name)
    if assignment is None:
        raise UnknownProcessNameError(
            f"Unknown process name: {process_name!r}"
        )
    return assignment
