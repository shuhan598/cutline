"""Generate the deliverable input/output examples through the formal API."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import create_app


EXAMPLES = ROOT / "examples"
SCENARIOS = EXAMPLES / "scenarios"

def localize_standard_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Translate approved human-facing values without renaming processes."""

    localized = deepcopy(payload)
    localized["snapshot_meta"]["trigger_type"] = "手动触发"

    for route in localized["process_routes"]:
        route["cache_type"] = "工序缓存"

    for buffer in localized["buffer_master"]:
        buffer["buffer_name"] = buffer["buffer_name"].replace(
            "Buffer", "缓存区"
        )
        buffer["buffer_type"] = "工序"
    return localized


def _without_route_loop_compatibility(
    payload: dict[str, Any],
) -> dict[str, Any]:
    result = deepcopy(payload)
    for route in result["process_routes"]:
        route.pop("loop_code", None)
        route.pop("loop_name", None)
    return result


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _scenario(name: str) -> dict[str, Any]:
    return localize_standard_payload(
        _read_json(SCENARIOS / f"{name}.json")
    )


def _post(client: TestClient, payload: dict[str, Any], status: int) -> dict:
    response = client.post("/cutline/evaluate", json=payload)
    if response.status_code != status:
        raise RuntimeError(
            f"/cutline/evaluate returned {response.status_code}, "
            f"expected {status}: {response.text}"
        )
    return response.json()


def _first_round_input() -> dict[str, Any]:
    payload = _without_route_loop_compatibility(
        _scenario("v3_stockout_auto")
    )
    payload["pending_cutline_plans"] = []
    payload["active_cutline_events"] = []
    payload["return_suggested_event_ids"] = []
    payload["mixed_cutline_event_ids"] = []
    return payload


def _next_round_input(persistence_state: dict[str, Any]) -> dict[str, Any]:
    """Replay the first-round persistence state into a confirmation request."""

    payload = _scenario("v3_return_round_2")
    for field in (
        "pending_cutline_plans",
        "active_cutline_events",
        "return_suggested_event_ids",
        "mixed_cutline_event_ids",
    ):
        payload[field] = deepcopy(persistence_state[field])
    return payload


def generate() -> list[Path]:
    client = TestClient(create_app(), raise_server_exceptions=False)

    first_round = _first_round_input()
    stockout_output = _post(client, first_round, 200)
    confirmation_input = _next_round_input(
        stockout_output["persistence_state"]
    )
    confirmation_output = _post(client, confirmation_input, 200)
    next_round = deepcopy(confirmation_input)
    _post(client, next_round, 200)

    no_warning_output = _post(client, _scenario("v3_no_warning"), 200)
    return_input = _scenario("v3_return_recommended")
    return_input["mixed_cutline_event_ids"] = []
    return_output = _post(client, return_input, 200)
    manual_output = _post(client, _scenario("v3_stockout_manual"), 200)

    invalid_backend = deepcopy(first_round)
    invalid_backend["orders"][0]["total_quantity"] = "not-a-number"
    backend_error = _post(client, invalid_backend, 422)

    invalid_snapshot = deepcopy(first_round)
    machine = invalid_snapshot["machine_master"][0]
    invalid_snapshot["machine_lines"] = [
        {
            "machine_code": machine["machine_code"],
            "machine_name": machine["machine_name"],
            "line_code": "S2-STANDARD-LINE",
            "line_name": "S2标准示例产线",
            "wafer_spec": "N",
        }
    ]
    invalid_snapshot["lines"] = []
    snapshot_error = _post(client, invalid_snapshot, 422)

    artifacts = {
        "cutline_standard_input_first_round.json": first_round,
        "cutline_standard_input_next_round.json": next_round,
        "cutline_standard_output_no_warning.json": no_warning_output,
        "cutline_standard_output_stockout_plan.json": stockout_output,
        "cutline_standard_output_pending_confirmed.json": (
            confirmation_output
        ),
        "cutline_standard_output_return_recommendation.json": return_output,
        "cutline_standard_output_manual_intervention.json": manual_output,
        "cutline_standard_error_backend_data_invalid.json": backend_error,
        "cutline_standard_error_snapshot_conversion.json": snapshot_error,
    }
    paths: list[Path] = []
    for name, value in artifacts.items():
        path = EXAMPLES / name
        _write_json(path, value)
        paths.append(path)
    return paths


def main() -> None:
    for path in generate():
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
