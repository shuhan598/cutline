from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable

from app.utils.time_utils import normalize_local_time


def select_latest_effective_bindings(
    relations: Iterable[Any],
    snapshot_time: datetime,
) -> dict[str, tuple[datetime, list[Any]]]:
    """Return every record tied at each machine's latest effective time."""
    comparable_snapshot_time = normalize_local_time(snapshot_time)
    candidates_by_machine: dict[str, list[tuple[datetime, Any]]] = defaultdict(
        list
    )
    for relation in relations:
        binding_time = normalize_local_time(relation.binding_time)
        if binding_time <= comparable_snapshot_time:
            machine_code = relation.machine_code.strip()
            candidates_by_machine[machine_code].append(
                (binding_time, relation)
            )

    selected: dict[str, tuple[datetime, list[Any]]] = {}
    for machine_code in sorted(candidates_by_machine):
        candidates = candidates_by_machine[machine_code]
        latest_time = max(binding_time for binding_time, _ in candidates)
        selected[machine_code] = (
            latest_time,
            [
                relation
                for binding_time, relation in candidates
                if binding_time == latest_time
            ],
        )
    return selected
