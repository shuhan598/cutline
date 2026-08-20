"""In-memory per-workshop cross-round state for formal V6 evaluations."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from uuid import uuid4
from typing import Any


@dataclass(frozen=True)
class EvaluationState:
    state_generation: str
    workshop_id: str
    state: dict[str, Any]
    state_reset: bool


class AlgorithmStateStore:
    def __init__(self, *, state_generation: str | None = None):
        self.state_generation = state_generation or uuid4().hex
        self._states: dict[str, dict[str, Any]] = {}
        self._in_flight: set[str] = set()
        self._lock = RLock()

    def begin(self, workshop_id: str) -> EvaluationState:
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
        with self._lock:
            if workshop_id not in self._in_flight:
                raise RuntimeError(f"workshop evaluation was not started: {workshop_id}")
            self._states[workshop_id] = deepcopy(state)
            self._in_flight.remove(workshop_id)

    def abort(self, workshop_id: str) -> None:
        with self._lock:
            self._in_flight.discard(workshop_id)

    def get(self, workshop_id: str) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._states.get(workshop_id, {}))

