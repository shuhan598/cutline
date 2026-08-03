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

_PROCESS_DISPLAY_NAMES = {
    "POLY": "多晶硅沉积",
    "RCA": "RCA清洗",
}


def _machine_display_name(value: str) -> str:
    return value.replace("POLY机", "多晶硅沉积机").replace(
        "RCA机",
        "RCA清洗机",
    )


def localize_standard_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Translate human-facing example values without changing identifiers."""

    localized = deepcopy(payload)
    localized["snapshot_meta"]["trigger_type"] = "手动触发"

    for machine in localized["machine_master"]:
        machine["machine_name"] = _machine_display_name(
            machine["machine_name"]
        )
        machine["process_name"] = _PROCESS_DISPLAY_NAMES.get(
            machine["process_name"],
            machine["process_name"],
        )
    for capacity in localized["machine_process_times"]:
        capacity["machine_name"] = _machine_display_name(
            capacity["machine_name"]
        )
    for relation in localized["machine_lines"]:
        relation["machine_name"] = _machine_display_name(
            relation["machine_name"]
        )
    for relation in localized["agv_relations"]:
        name_field = (
            "equipmentname"
            if "equipmentname" in relation
            else "machine_name"
        )
        relation[name_field] = _machine_display_name(relation[name_field])

    for route in localized["process_routes"]:
        route["process_name"] = _PROCESS_DISPLAY_NAMES.get(
            route["process_name"],
            route["process_name"],
        )
        for field in (
            "upstream_process_name",
            "downstream_process_name",
        ):
            if route[field] is not None:
                route[field] = _PROCESS_DISPLAY_NAMES.get(
                    route[field],
                    route[field],
                )
        route["cache_type"] = "工序缓存"

    for buffer in localized["buffer_master"]:
        buffer["buffer_name"] = (
            buffer["buffer_name"]
            .replace("POLY", "多晶硅沉积")
            .replace("RCA", "RCA清洗")
            .replace("Buffer", "缓存区")
        )
        buffer["buffer_type"] = "工序"
        buffer["served_process_names"] = [
            _PROCESS_DISPLAY_NAMES.get(name, name)
            for name in buffer["served_process_names"]
        ]
    return localized


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
    payload = _scenario("v3_stockout_auto")
    payload["pending_cutline_plans"] = []
    payload["active_cutline_events"] = []
    payload["return_suggested_event_ids"] = []
    payload["mixed_cutline_event_ids"] = []
    return payload


def _next_round_input() -> dict[str, Any]:
    """Use the real second-round Pending confirmation request."""

    return _scenario("v3_return_round_2")


def generate() -> list[Path]:
    client = TestClient(create_app(), raise_server_exceptions=False)

    first_round = _first_round_input()
    stockout_output = _post(client, first_round, 200)
    confirmation_input = _next_round_input()
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
