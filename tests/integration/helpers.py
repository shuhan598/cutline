from __future__ import annotations

from typing import Any

from app.adapters.backend_request_loader import BackendRequestLoader
from app.adapters.snapshot_adapter import SnapshotAdapter
from app.service.cutline_service import CutlineService


def evaluate(payload: dict[str, Any]):
    request = BackendRequestLoader().load_cutline_dict(payload)
    return CutlineService().evaluate_algorithm(request)


def snapshot(payload: dict[str, Any]):
    request = BackendRequestLoader().load_cutline_dict(payload)
    return SnapshotAdapter().to_algorithm_snapshot(request)


def runtime(payload: dict[str, Any], machine_code: str) -> dict[str, Any]:
    machine = next(
        item
        for item in payload["machine_master"]
        if item["machine_code"] == machine_code
    )
    return next(
        item
        for item in payload["machine_realtime"]
        if item["machine_code"] == machine["p166_jt_group"]
    )


def inventory(
    payload: dict[str, Any],
    buffer_code: str,
    bound_source_name: str,
) -> dict[str, Any]:
    return next(
        item
        for item in payload["buffer_realtime"]
        if item["buffer_code"] == buffer_code
        and item["bound_source_name"] == bound_source_name
    )


def response_buffer_codes(value: Any) -> list[str]:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    result: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key.endswith("buffer_code") and item is not None:
                result.append(item)
            result.extend(response_buffer_codes(item))
    elif isinstance(value, list):
        for item in value:
            result.extend(response_buffer_codes(item))
    return result
