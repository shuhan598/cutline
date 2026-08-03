"""Resolve a Buffer's authoritative process interval and workshop."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


class BufferProcessResolutionError(ValueError):
    """A Buffer cannot be mapped to one valid adjacent process interval."""


class ProcessRouteView(Protocol):
    process_code: str
    sequence: int
    workshop_code: str
    loop_code: str


class BufferMasterView(Protocol):
    buffer_code: str
    served_process_codes: list[str]
    loop_code: str


@dataclass(frozen=True)
class BufferProcessResolution:
    workshop_code: str
    upstream_process_code: str
    downstream_process_code: str


class BufferProcessResolver:
    """Apply one workshop/process rule to Adapter conversion and validation."""

    def __init__(self, routes: Iterable[ProcessRouteView]):
        self._routes = list(routes)

    def resolve(self, buffer: BufferMasterView) -> BufferProcessResolution:
        if len(buffer.served_process_codes) != 2:
            raise BufferProcessResolutionError(
                f"Buffer {buffer.buffer_code} must serve exactly two processes"
            )

        upstream_code, downstream_code = buffer.served_process_codes
        upstream_candidates = [
            route
            for route in self._routes
            if route.loop_code == buffer.loop_code
            and route.process_code == upstream_code
        ]
        downstream_candidates = [
            route
            for route in self._routes
            if route.loop_code == buffer.loop_code
            and route.process_code == downstream_code
        ]
        if not upstream_candidates:
            raise BufferProcessResolutionError(
                f"Buffer {buffer.buffer_code} process {upstream_code} "
                f"has no route in loop {buffer.loop_code}"
            )
        if not downstream_candidates:
            raise BufferProcessResolutionError(
                f"Buffer {buffer.buffer_code} process {downstream_code} "
                f"has no route in loop {buffer.loop_code}"
            )

        pairs = [
            (upstream, downstream)
            for upstream in upstream_candidates
            for downstream in downstream_candidates
            if upstream.workshop_code == downstream.workshop_code
        ]
        if not pairs:
            raise BufferProcessResolutionError(
                f"Buffer {buffer.buffer_code} served processes must belong "
                "to the same workshop"
            )
        if len(pairs) > 1:
            raise BufferProcessResolutionError(
                f"Buffer {buffer.buffer_code} process routes match multiple "
                "workshops"
            )

        upstream, downstream = pairs[0]
        if upstream.sequence >= downstream.sequence:
            raise BufferProcessResolutionError(
                f"Buffer {buffer.buffer_code} upstream sequence must precede "
                "downstream sequence"
            )
        has_intermediate_process = any(
            route.loop_code == buffer.loop_code
            and route.workshop_code == upstream.workshop_code
            and upstream.sequence < route.sequence < downstream.sequence
            for route in self._routes
        )
        if has_intermediate_process:
            raise BufferProcessResolutionError(
                f"Buffer {buffer.buffer_code} served processes must be adjacent"
            )
        return BufferProcessResolution(
            workshop_code=upstream.workshop_code,
            upstream_process_code=upstream_code,
            downstream_process_code=downstream_code,
        )
