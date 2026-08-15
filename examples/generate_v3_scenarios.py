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


def _unique_string(items: list[dict], field_name: str) -> str | None:
    values = {
        item[field_name]
        for item in items
        if isinstance(item.get(field_name), str)
        and item[field_name].strip()
    }
    if len(values) != 1:
        return None
    return next(iter(values))


def _standard_status_by_machine(payload: dict) -> dict[str, str]:
    standard_by_realtime = {
        item["p166_jt_group"]: item["machine_code"]
        for item in payload["machine_master"]
    }
    return {
        standard_by_realtime[item["machine_code"]]: (
            "running"
            if item["status"].strip() == "运行"
            or item["status"].strip().casefold() == "running"
            else "stopped"
        )
        for item in payload["machine_realtime"]
    }


def _upgrade_pending_contract(payload: dict, plan: dict) -> None:
    candidates = plan.get("candidate_machines", [])
    plan.setdefault(
        "candidate_machine_codes",
        [item["machine_code"] for item in candidates],
    )
    plan.setdefault("process_code", _unique_string(candidates, "process_code"))
    plan.setdefault(
        "source_order_code",
        _unique_string(candidates, "baseline_order_code"),
    )
    plan.setdefault(
        "target_order_code",
        _unique_string(candidates, "expected_target_order_code"),
    )
    plan.setdefault(
        "source_product_code",
        _unique_string(candidates, "baseline_product_code"),
    )
    plan.setdefault(
        "target_product_code",
        _unique_string(candidates, "expected_target_product_code"),
    )

    status_by_machine = _standard_status_by_machine(payload)
    for binding in plan.get("baseline_machine_bindings", []):
        if "observed_at" not in binding and "agv_record_time" in binding:
            binding["observed_at"] = binding.pop("agv_record_time")
        binding.setdefault(
            "machine_status",
            status_by_machine.get(binding["machine_code"]),
        )


def _upgrade_active_contract(event: dict) -> None:
    event.setdefault("status", "active")


def _algorithm_request_payload(payload: dict) -> dict:
    payload.setdefault("pending_cutline_plans", [])
    payload.setdefault("active_cutline_events", [])
    payload.setdefault("return_suggested_event_ids", [])
    payload.setdefault("mixed_cutline_event_ids", [])
    for plan in payload["pending_cutline_plans"]:
        _upgrade_pending_contract(payload, plan)
    for event in payload["active_cutline_events"]:
        _upgrade_active_contract(event)
    if payload["active_cutline_events"] and not payload["mixed_cutline_event_ids"]:
        payload["mixed_cutline_event_ids"] = [
            event["event_id"] for event in payload["active_cutline_events"]
        ]
    return payload


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_service_response(
    path: Path,
    payload: dict,
    *,
    include_persistence_state: bool = True,
) -> None:
    request = BackendRequestLoader().load_cutline_dict(
        _algorithm_request_payload(payload)
    )
    response = CutlineService().evaluate_algorithm(request)
    response_payload = response.model_dump(
        mode="json",
        exclude=(None if include_persistence_state else {"persistence_state"}),
    )
    _write_json(path, response_payload)


def _with_empty_line_compatibility(payload: dict) -> dict:
    payload["lines"] = []
    payload["machine_lines"] = []
    return payload


def _without_line_compatibility(payload: dict) -> dict:
    payload.pop("lines", None)
    payload.pop("machine_lines", None)
    return payload


def _without_route_loop_compatibility(payload: dict) -> dict:
    for route in payload["process_routes"]:
        route.pop("loop_code", None)
        route.pop("loop_name", None)
    return payload


def _standard_request_payload() -> dict:
    return _without_route_loop_compatibility(
        _algorithm_request_payload(
            _without_line_compatibility(build_no_warning_payload())
        )
    )


def _sample_request_payload() -> dict:
    return _algorithm_request_payload(
        _with_empty_line_compatibility(build_no_warning_payload())
    )


def _stockout_request_payload() -> dict:
    return _algorithm_request_payload(
        _with_empty_line_compatibility(build_stockout_auto_payload())
    )


def _mixing_failure_confirmation_payload() -> dict:
    payload = build_return_round_2_payload()
    payload["snapshot_meta"]["run_id"] = "RUN-V3-MIXING-FAILURE"
    payload["machine_process_times"] = [
        item
        for item in payload["machine_process_times"]
        if not (
            item["machine_code"] == "EA004"
            and item["product_code"] == "PROD-S2-N-SUPPORT"
        )
    ]
    return payload


def _return_recommended_request_payload() -> dict:
    """Build a later-cycle request from the real confirmation response state."""

    confirmation_payload = _algorithm_request_payload(
        build_return_round_2_payload()
    )
    confirmation_request = BackendRequestLoader().load_cutline_dict(
        confirmation_payload
    )
    confirmation_response = CutlineService().evaluate_algorithm(
        confirmation_request
    )
    active_events = confirmation_response.persistence_state.active_cutline_events
    if len(active_events) != 1:
        raise ValueError(
            "confirmation example must create exactly one active event"
        )

    payload = build_return_recommended_payload()
    payload["active_cutline_events"] = [
        active_events[0].model_dump(mode="json")
    ]
    payload["mixed_cutline_event_ids"] = [active_events[0].event_id]
    payload["return_suggested_event_ids"] = []
    return _algorithm_request_payload(payload)


def _backend_ingestion_payload() -> dict:
    payload = build_base_request_payload()
    payload.pop("active_cutline_events")
    payload.pop("pending_cutline_plans")
    first_runtime = payload["machine_realtime"][0]
    first_runtime["input_quantity"] = 12.0
    first_runtime["output_quantity"] = 10.5
    first_capacity = payload["machine_process_times"][0]
    first_capacity["proc_seconds"] = 90.0
    first_capacity["actual_capacity"] = 120.5
    for runtime in payload["machine_realtime"]:
        runtime.pop("out_time")
    return _without_line_compatibility(payload)


def generate_request_examples() -> list[Path]:
    """Generate the four official requests and thirteen V3 scenario inputs."""

    generated: list[Path] = []
    official_examples = {
        EXAMPLES_DIR / "backend_request_standard.json": (
            _standard_request_payload
        ),
        EXAMPLES_DIR / "backend_request_sample.json": _sample_request_payload,
        EXAMPLES_DIR
        / "backend_request_stockout_plan_sample.json": (
            _stockout_request_payload
        ),
        EXAMPLES_DIR
        / "backend_ingestion_request_sample.json": _backend_ingestion_payload,
    }
    for path, builder in official_examples.items():
        _write_json(path, builder())
        generated.append(path)

    for scenario_name, builder in sorted(V3_SCENARIO_BUILDERS.items()):
        path = SCENARIOS_DIR / f"{scenario_name}.json"
        payload = (
            _mixing_failure_confirmation_payload()
            if scenario_name == "v3_mixing_failure"
            else (
                _return_recommended_request_payload()
                if scenario_name == "v3_return_recommended"
                else builder()
            )
        )
        _write_json(
            path,
            _algorithm_request_payload(
                _with_empty_line_compatibility(payload)
            ),
        )
        generated.append(path)
    return generated


def generate_example_files() -> list[Path]:
    generated = generate_request_examples()

    base_response_path = EXAMPLES_DIR / "cutline_algorithm_response_sample.json"
    _write_service_response(
        base_response_path,
        _sample_request_payload(),
        include_persistence_state=False,
    )
    generated.append(base_response_path)

    response_examples = {
        EXAMPLES_DIR
        / "cutline_evaluate_stockout_round_1_response.json": (
            _stockout_request_payload
        ),
        EXAMPLES_DIR
        / "cutline_evaluate_confirmation_round_response.json": (
            build_return_round_2_payload
        ),
        EXAMPLES_DIR
        / "cutline_evaluate_return_response.json": (
            _return_recommended_request_payload
        ),
    }
    for path, builder in response_examples.items():
        _write_service_response(path, builder())
        generated.append(path)
    return generated


def generate() -> list[Path]:
    generated = generate_example_files()

    debug_outputs = {
        DEBUG_OUTPUTS_DIR
        / "cutline_response_result.json": _sample_request_payload,
        DEBUG_OUTPUTS_DIR
        / "stockout_plan_sample_response.json": _stockout_request_payload,
    }
    for path, builder in debug_outputs.items():
        _write_service_response(
            path,
            builder(),
            include_persistence_state=False,
        )
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
        / "v3_return_recommended_response.json": (
            _return_recommended_request_payload
        ),
        DEBUG_OUTPUTS_DIR
        / "v3_silk_not_ready_response.json": build_silk_not_ready_payload,
        DEBUG_OUTPUTS_DIR
        / "v3_silk_prepare_response.json": build_silk_prepare_payload,
        DEBUG_OUTPUTS_DIR
        / "v3_mixing_failure_response.json": (
            _mixing_failure_confirmation_payload
        ),
    }
    for path, builder in response_examples.items():
        _write_service_response(
            path,
            _with_empty_line_compatibility(builder()),
            include_persistence_state=False,
        )
        generated.append(path)

    return generated


def main() -> None:
    for path in generate():
        print(path.relative_to(ROOT_DIR))


if __name__ == "__main__":
    main()
