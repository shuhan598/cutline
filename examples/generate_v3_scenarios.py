"""Generate committed V3 request examples from the shared test factory."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tests.fixtures.v3_full_route_factory import (
    V3_SCENARIO_BUILDERS,
    build_base_request_payload,
    build_mixing_failure_payload,
    build_no_warning_payload,
    build_overflow_manual_payload,
    build_overflow_warning_payload,
    build_return_recommended_payload,
    build_return_round_2_payload,
    build_silk_not_ready_payload,
    build_silk_prepare_payload,
    build_stockout_auto_payload,
    build_stockout_manual_insufficient_payload,
    build_stockout_manual_payload,
)
from app.adapters.backend_request_loader import BackendRequestLoader
from app.service.cutline_service import CutlineService


EXAMPLES_DIR = ROOT_DIR / "examples"
SCENARIOS_DIR = EXAMPLES_DIR / "scenarios"
DEBUG_OUTPUTS_DIR = ROOT_DIR / "debug_outputs"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_service_response(path: Path, payload: dict) -> None:
    request = BackendRequestLoader().load_cutline_dict(payload)
    response = CutlineService().evaluate_algorithm(request)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        response.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def _backend_ingestion_payload() -> dict:
    payload = build_base_request_payload()
    payload.pop("active_cutline_events")
    first_runtime = payload["machine_realtime"][0]
    first_runtime["input_quantity"] = 12.0
    first_runtime["output_quantity"] = 10.5
    first_runtime["completed_quantity"] = 100.0
    first_capacity = payload["machine_process_times"][0]
    first_capacity["proc_seconds"] = 90.0
    first_capacity["actual_capacity"] = 120.5
    for runtime in payload["machine_realtime"]:
        runtime.pop("period_quantity")
        runtime.pop("out_time")
    for order in payload["orders"]:
        order.pop("order_name")
    return payload


def generate() -> list[Path]:
    generated: list[Path] = []
    official_examples = {
        EXAMPLES_DIR / "backend_request_sample.json": build_no_warning_payload,
        EXAMPLES_DIR
        / "backend_request_stockout_plan_sample.json": build_stockout_auto_payload,
        EXAMPLES_DIR
        / "backend_ingestion_request_sample.json": _backend_ingestion_payload,
    }
    for path, builder in official_examples.items():
        _write_json(path, builder())
        generated.append(path)

    response_sample_path = EXAMPLES_DIR / "cutline_algorithm_response_sample.json"
    _write_service_response(response_sample_path, build_no_warning_payload())
    generated.append(response_sample_path)

    debug_outputs = {
        DEBUG_OUTPUTS_DIR / "cutline_response_result.json": build_no_warning_payload,
        DEBUG_OUTPUTS_DIR
        / "stockout_plan_sample_response.json": build_stockout_auto_payload,
    }
    for path, builder in debug_outputs.items():
        _write_service_response(path, builder())
        generated.append(path)

    response_examples = {
        DEBUG_OUTPUTS_DIR / "v3_no_warning_response.json": build_no_warning_payload,
        DEBUG_OUTPUTS_DIR
        / "v3_stockout_auto_response.json": build_stockout_auto_payload,
        DEBUG_OUTPUTS_DIR
        / "v3_stockout_manual_no_candidate_response.json": (
            build_stockout_manual_payload
        ),
        DEBUG_OUTPUTS_DIR
        / "v3_stockout_manual_insufficient_response.json": (
            build_stockout_manual_insufficient_payload
        ),
        DEBUG_OUTPUTS_DIR
        / "v3_overflow_warning_response.json": build_overflow_warning_payload,
        DEBUG_OUTPUTS_DIR
        / "v3_overflow_manual_response.json": build_overflow_manual_payload,
        DEBUG_OUTPUTS_DIR
        / "v3_return_tracking_started_response.json": build_return_round_2_payload,
        DEBUG_OUTPUTS_DIR
        / "v3_return_recommended_response.json": build_return_recommended_payload,
        DEBUG_OUTPUTS_DIR
        / "v3_silk_not_ready_response.json": build_silk_not_ready_payload,
        DEBUG_OUTPUTS_DIR
        / "v3_silk_prepare_response.json": build_silk_prepare_payload,
        DEBUG_OUTPUTS_DIR
        / "v3_mixing_failure_response.json": build_mixing_failure_payload,
    }
    for path, builder in response_examples.items():
        _write_service_response(path, builder())
        generated.append(path)

    for scenario_name, builder in sorted(V3_SCENARIO_BUILDERS.items()):
        path = SCENARIOS_DIR / f"{scenario_name}.json"
        _write_json(path, builder())
        generated.append(path)
    return generated


def main() -> None:
    for path in generate():
        print(path.relative_to(ROOT_DIR))


if __name__ == "__main__":
    main()
