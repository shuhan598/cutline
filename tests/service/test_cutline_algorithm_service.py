from copy import deepcopy
from datetime import datetime

import pytest

import app.service.cutline_pipeline as pipeline_module
from app.adapters.snapshot_adapter import SnapshotConversionError
from app.core.candidate_machine.errors import CandidateMachineCalculationError
from app.schemas.request_schema import AlgorithmSnapshot
from app.schemas.request_schema import CutlineAlgorithmRequest
from app.schemas.response_schema import (
    CutlineAlgorithmResponse,
    CutlineEvaluateResponse,
)
from app.schemas import result_schema as result
from app.service.cutline_pipeline import CutlinePipeline
from app.service.cutline_service import CutlineService
from app.utils.time_utils import normalize_local_time
from tests.adapters import test_snapshot_adapter as adapter_helpers


NOW = datetime(2026, 7, 16, 12, 0)
REAL_NOW = datetime(2026, 7, 16, 8, 30)


def test_cutline_service_does_not_expose_legacy_evaluate_entrypoint():
    assert not hasattr(CutlineService, "evaluate")


def test_cutline_pipeline_does_not_expose_legacy_run_entrypoint():
    assert not hasattr(CutlinePipeline, "run")


def test_cutline_pipeline_module_does_not_expose_legacy_result_type():
    assert not hasattr(pipeline_module, "PipelineResult")


def empty_request() -> CutlineAlgorithmRequest:
    return CutlineAlgorithmRequest.model_validate(
        {
            "snapshot_meta": {
                "run_id": "run-1",
                "trigger_type": "manual",
                "workshop_id": "S1",
                "snapshot_time": NOW,
                "params_version": 1,
                "catalog_version": "catalog-1",
                "catalog_loaded_at": NOW,
                "degraded_flags": [],
            },
            "machine_realtime": [],
            "machine_master": [],
            "machine_process_times": [],
            "workshops": [],
            "lines": [],
            "machine_lines": [],
            "orders": [],
            "products": [],
            "process_routes": [],
            "buffer_realtime": [],
            "buffer_master": [],
            "agv_relations": [],
            "active_cutline_events": [],
        }
    )


def empty_snapshot(*, active_cutline_events=None) -> AlgorithmSnapshot:
    return AlgorithmSnapshot(
        current_time=NOW,
        workshops=[],
        lines=[],
        machine_lines=[],
        machine_runtimes=[],
        machine_masters=[],
        machine_product_capacities=[],
        orders=[],
        products=[],
        process_routes=[],
        buffer_masters=[],
        buffer_process_relations=[],
        buffer_order_inventories=[],
        agv_relations=[],
        active_cutline_events=active_cutline_events or [],
    )


class StaticAdapter:
    def __init__(self, snapshot=None):
        self.snapshot = snapshot if snapshot is not None else empty_snapshot()
        self.requests = []

    def to_algorithm_snapshot(self, request):
        self.requests.append(request)
        return self.snapshot


class ResultPipeline:
    def __init__(self, value):
        self.value = value
        self.snapshots = []

    def evaluate_algorithm(self, snapshot):
        self.snapshots.append(snapshot)
        return self.value

    def run(self, snapshot):
        raise AssertionError("legacy run must not be called")


def _machine_runtime(code, input_quantity, output_quantity):
    return {
        "machine_code": f"P166-{code}",
        "status": "running",
        "tangent_time": None,
        "input_quantity": float(input_quantity),
        "output_quantity": float(output_quantity),
        "out_time": None,
    }


def _agv_relation(machine_code, product_name, wafer_spec="N"):
    return {
        "machine_code": machine_code,
        "machine_name": machine_code,
        "product_name": product_name,
        "previous_product_name": None,
        "wafer_spec": wafer_spec,
        "binding_time": REAL_NOW,
    }


def _machine_master(code, process_code, process_name=None):
    return {
        "machine_code": code,
        "p166_jt_group": f"P166-{code}",
        "machine_name": code,
        "process_code": process_code,
        "process_name": process_name or process_code,
    }


def _machine_line(code):
    return {
        "machine_code": code,
        "machine_name": code,
        "line_code": "L1",
        "line_name": "L1",
        "wafer_spec": "N",
    }


def _order(code, product_code, *, total=200000, produced=0):
    return {
        "order_code": code,
        "order_status": "RUNNING",
        "total_quantity": total,
        "piece_source": "A",
        "estimated_yield": "99%",
        "product_code": product_code,
        "product_name": product_code,
        "workshop_code": "S1",
        "workshop_name": "Workshop",
        "produced_quantity": produced,
        "remaining_quantity": total - produced,
    }


def _product(code):
    return {
        "product_code": code,
        "product_name": code,
        "wafer_size": "182",
        "source_grade": "A",
        "material_code": f"MAT-{code}",
        "material_name": f"MAT-{code}",
    }


def _process_route(code, sequence, upstream, downstream):
    process_names = {"P01": "制绒", "P02": "氧化", "SW": "丝网"}
    return {
        "process_code": code,
        "process_name": process_names[code],
        "sequence": sequence,
        "cache_type": "BUFFER",
        "workshop_code": "S1",
        "workshop_name": "Workshop",
        "loop_code": "LOOP1",
        "loop_name": "Loop",
        "upstream_process_code": upstream,
        "upstream_process_name": (
            process_names[upstream] if upstream is not None else None
        ),
        "downstream_process_code": downstream,
        "downstream_process_name": (
            process_names[downstream] if downstream is not None else None
        ),
    }


def _buffer_master(code):
    return {
        "buffer_code": code,
        "buffer_name": code,
        "buffer_type": "LINE",
        "buffer_type_title": "Line",
        "max_capacity": 200000,
        "safety_low": 50,
        "served_process_codes": ["P01", "P02"],
        "served_process_names": ["P01", "P02"],
        "loop_code": "LOOP1",
        "loop_name": "Loop",
    }


def _snapshot_meta():
    return {
        "run_id": "real-service-scenario",
        "trigger_type": "manual",
        "workshop_id": "S1",
        "snapshot_time": REAL_NOW,
        "params_version": 1,
        "catalog_version": "catalog-1",
        "catalog_loaded_at": REAL_NOW,
        "degraded_flags": [],
    }


def _real_flow_payload():
    machine_codes = ["M-CAND", "M-SRC-DOWN", "M-TGT-UP", "M-TGT-DOWN"]
    return {
        "snapshot_meta": _snapshot_meta(),
        "machine_realtime": [
            _machine_runtime("M-CAND", 200, 200),
            _machine_runtime("M-SRC-DOWN", 200, 0),
            _machine_runtime("M-TGT-UP", 0, 0),
            _machine_runtime("M-TGT-DOWN", 200, 0),
        ],
        "machine_master": [
            _machine_master("M-CAND", "P01"),
            _machine_master("M-SRC-DOWN", "P02"),
            _machine_master("M-TGT-UP", "P01"),
            _machine_master("M-TGT-DOWN", "P02"),
        ],
        "machine_process_times": [
            {
                "machine_code": "M-CAND",
                "machine_name": "M-CAND",
                "product_code": "PROD-SOURCE",
                "product_name": "210N源产品",
                "proc_seconds": 3600.0,
                "actual_capacity": 400,
            }
        ],
        "workshops": [
            {"workshop_code": "S1", "workshop_name": "Workshop"}
        ],
        "lines": [
            {
                "line_code": "L1",
                "line_name": "L1",
                "wafer_spec": "N",
                "workshop_code": "S1",
                "workshop_name": "Workshop",
            }
        ],
        "machine_lines": [_machine_line(code) for code in machine_codes],
        "orders": [
            {
                **_order("ORD-SOURCE", "PROD-SOURCE"),
                "product_name": "210N源产品",
            },
            {
                **_order("ORD-TARGET", "PROD-TARGET"),
                "product_name": "210N目标产品",
            },
        ],
        "products": [
            {
                **_product("PROD-SOURCE"),
                "product_name": "210N源产品",
            },
            {
                **_product("PROD-TARGET"),
                "product_name": "210N目标产品",
            },
        ],
        "process_routes": [
            _process_route("P01", 1, None, "P02"),
            _process_route("P02", 2, "P01", None),
        ],
        "buffer_realtime": [
            {
                "main_id": "source-inventory",
                "buffer_code": "BUF-SOURCE",
                "bound_source_name": "210N源产品-背膜下-AUTO",
                "current_quantity": 100000,
                "current_utilization_rate": 0.5,
            },
            {
                "main_id": "target-inventory",
                "buffer_code": "BUF-TARGET",
                "bound_source_name": "210N目标产品-背膜下-AUTO",
                "current_quantity": 100,
                "current_utilization_rate": 0.1,
            },
        ],
        "buffer_master": [
            _buffer_master("BUF-SOURCE"),
            _buffer_master("BUF-TARGET"),
        ],
        "agv_relations": [
            _agv_relation("M-CAND", "210N源产品"),
            _agv_relation("M-SRC-DOWN", "210N源产品"),
            _agv_relation("M-TGT-UP", "210N目标产品"),
            _agv_relation("M-TGT-DOWN", "210N目标产品"),
        ],
        "active_cutline_events": [],
    }


def _silk_payload():
    return {
        "snapshot_meta": _snapshot_meta(),
        "machine_realtime": [
            _machine_runtime("M-SILK", 0, 5000)
        ],
        "machine_master": [
            _machine_master("M-SILK", "SW", process_name="丝网")
        ],
        "machine_process_times": [],
        "workshops": [
            {"workshop_code": "S1", "workshop_name": "Workshop"}
        ],
        "lines": [
            {
                "line_code": "L1",
                "line_name": "L1",
                "wafer_spec": "N",
                "workshop_code": "S1",
                "workshop_name": "Workshop",
            }
        ],
        "machine_lines": [_machine_line("M-SILK")],
        "orders": [
            _order(
                "ORD-SILK",
                "PROD-SILK",
                total=100000,
                produced=80000,
            )
        ],
        "products": [_product("PROD-SILK")],
        "process_routes": [
            _process_route("SW", 1, None, None)
        ],
        "buffer_realtime": [],
        "buffer_master": [],
        "agv_relations": [
            _agv_relation("M-SILK", "PROD-SILK")
        ],
        "active_cutline_events": [],
    }


def _evaluate_real_payload(payload, *, pipeline=None):
    request = CutlineAlgorithmRequest.model_validate(payload)
    service = CutlineService(pipeline) if pipeline is not None else CutlineService()
    return service.evaluate_algorithm(request)


def test_evaluate_algorithm_calls_adapter_pipeline_and_mapper_in_order():
    request = empty_request()
    snapshot = object()
    result_value = result.AlgorithmEvaluateResult(calculation_time=NOW)
    response = CutlineEvaluateResponse(calculation_time=NOW)
    calls = []

    class Adapter:
        def to_algorithm_snapshot(self, received):
            calls.append(("adapter", received))
            return snapshot

    class Pipeline:
        def evaluate_algorithm(self, received):
            calls.append(("pipeline", received))
            return result_value

    class Mapper:
        def to_evaluate_response(self, received):
            calls.append(("mapper", received))
            return response

    service = CutlineService(
        pipeline=Pipeline(),
        adapter=Adapter(),
        mapper=Mapper(),
    )

    actual = service.evaluate_algorithm(request)

    assert actual is response
    assert calls == [
        ("adapter", request),
        ("pipeline", snapshot),
        ("mapper", result_value),
    ]


def test_real_empty_request_runs_the_real_adapter_pipeline_mapper_chain():
    request = empty_request()
    original = request.model_dump()

    response = CutlineService().evaluate_algorithm(request)

    assert isinstance(response, CutlineEvaluateResponse)
    assert response.persistence_state.pending_cutline_plans == []
    assert response.calculation_time == normalize_local_time(NOW)
    assert request.model_dump() == original
    assert "config" not in request.__class__.model_fields


def test_evaluate_algorithm_does_not_use_legacy_pipeline_run():
    value = result.AlgorithmEvaluateResult(calculation_time=NOW)
    pipeline = ResultPipeline(value)

    response = CutlineService(
        pipeline,
        adapter=StaticAdapter(),
    ).evaluate_algorithm(empty_request())

    assert isinstance(response, CutlineAlgorithmResponse)
    assert len(pipeline.snapshots) == 1


def test_historical_active_event_from_request_reaches_pipeline_snapshot():
    payload = deepcopy(adapter_helpers._payload())
    payload["active_cutline_events"] = [
        {
            "event_id": "CUT-HISTORY-MC-001",
            "machine_code": "MC-001",
            "source_order_code": "ORD-001",
            "target_order_code": "ORD-002",
            "workshop_code": "S1",
            "target_buffer_code": "BUF-002",
            "upstream_process_code": "PROC-01",
            "downstream_process_code": "PROC-02",
            "target_wafer_size": "182",
            "target_wafer_spec": "N",
            "cutline_start_time": "2026-07-15T08:00:00Z",
            "negative_start_time": None,
        }
    ]
    request = CutlineAlgorithmRequest.model_validate(payload)
    pipeline = ResultPipeline(
        result.AlgorithmEvaluateResult(
            calculation_time=request.snapshot_meta.snapshot_time
        )
    )

    CutlineService(pipeline).evaluate_algorithm(request)

    assert pipeline.snapshots[0].active_cutline_events[0].event_id == (
        "CUT-HISTORY-MC-001"
    )
    assert pipeline.snapshots[0].active_cutline_events[0].status == "active"
    assert pipeline.snapshots[0].active_cutline_events[0].plan_id is None


def test_snapshot_conversion_error_propagates_unchanged():
    expected = SnapshotConversionError("bad backend snapshot")

    class FailingAdapter:
        def to_algorithm_snapshot(self, request):
            raise expected

    with pytest.raises(SnapshotConversionError) as captured:
        CutlineService(
            pipeline=ResultPipeline(
                result.AlgorithmEvaluateResult(calculation_time=NOW)
            ),
            adapter=FailingAdapter(),
        ).evaluate_algorithm(empty_request())

    assert captured.value is expected


@pytest.mark.parametrize(
    "expected",
    [RuntimeError("core failed"), ValueError("map failed")],
)
def test_pipeline_and_mapper_exceptions_propagate_unchanged(expected):
    value = result.AlgorithmEvaluateResult(calculation_time=NOW)

    class FailingPipeline(ResultPipeline):
        def evaluate_algorithm(self, snapshot):
            if isinstance(expected, RuntimeError):
                raise expected
            return value

    class FailingMapper:
        def to_evaluate_response(self, received):
            raise expected

    mapper = None if isinstance(expected, RuntimeError) else FailingMapper()
    with pytest.raises(type(expected)) as captured:
        CutlineService(
            pipeline=FailingPipeline(value),
            adapter=StaticAdapter(),
            mapper=mapper,
        ).evaluate_algorithm(empty_request())

    assert captured.value is expected


def test_automatic_plan_response_has_no_future_mixing_record():
    response = _evaluate_real_payload(_real_flow_payload())

    assert isinstance(response, CutlineAlgorithmResponse)
    assert len(response.cutline_decisions) == 1
    assert response.mixing_trace_records == []
    assert response.new_active_cutline_events == []


def test_automatic_plan_without_line_collections_still_waits_for_active_event():
    payload = _real_flow_payload()
    payload.pop("lines")
    payload.pop("machine_lines")

    response = _evaluate_real_payload(payload)

    assert len(response.cutline_decisions) == 1
    assert response.mixing_trace_records == []


def test_manual_intervention_response_has_no_mixing_or_new_events():
    payload = _real_flow_payload()
    payload["machine_realtime"][0]["status"] = "idle"

    response = _evaluate_real_payload(payload)

    assert len(response.cutline_decisions) == 1
    assert response.cutline_decisions[0].manual_intervention is not None
    assert response.mixing_trace_records == []
    assert "mixing_trace_failures" not in response.__class__.model_fields
    assert response.new_active_cutline_events == []


def test_historical_event_recommendation_closes_without_returning_update():
    payload = _real_flow_payload()
    payload["machine_realtime"][2]["output_quantity"] = 200.0
    payload["machine_realtime"][3]["input_quantity"] = 0.0
    payload["buffer_realtime"][1]["current_quantity"] = 1000
    payload["active_cutline_events"] = [
        {
            "event_id": "CUT-HISTORICAL-M-CAND",
            "machine_code": "M-CAND",
            "source_order_code": "ORD-SOURCE",
            "target_order_code": "ORD-TARGET",
            "workshop_code": "S1",
            "target_buffer_code": "BUF-TARGET",
            "upstream_process_code": "P01",
            "downstream_process_code": "P02",
            "target_wafer_size": "182",
            "target_wafer_spec": "N",
            "cutline_start_time": datetime(2026, 7, 16, 7, 0),
            "negative_start_time": datetime(2026, 7, 16, 7, 59),
        }
    ]

    response = _evaluate_real_payload(payload)

    assert len(response.return_recommendations) == 1
    assert response.return_recommendations[0].event_id == (
        "CUT-HISTORICAL-M-CAND"
    )
    assert response.closed_active_cutline_event_ids == [
        "CUT-HISTORICAL-M-CAND"
    ]
    assert response.updated_active_cutline_events == []
    assert "return_results" not in response.__class__.model_fields
    assert response.new_active_cutline_events == []


def test_return_recommendation_runs_when_line_collections_are_empty():
    payload = _real_flow_payload()
    payload["lines"] = []
    payload["machine_lines"] = []
    payload["machine_realtime"][2]["output_quantity"] = 200.0
    payload["machine_realtime"][3]["input_quantity"] = 0.0
    payload["buffer_realtime"][1]["current_quantity"] = 1000
    payload["active_cutline_events"] = [
        {
            "event_id": "CUT-HISTORICAL-M-CAND",
            "machine_code": "M-CAND",
            "source_order_code": "ORD-SOURCE",
            "target_order_code": "ORD-TARGET",
            "workshop_code": "S1",
            "target_buffer_code": "BUF-TARGET",
            "upstream_process_code": "P01",
            "downstream_process_code": "P02",
            "target_wafer_size": "182",
            "target_wafer_spec": "N",
            "cutline_start_time": datetime(2026, 7, 16, 7, 0),
            "negative_start_time": datetime(2026, 7, 16, 7, 59),
        }
    ]

    response = _evaluate_real_payload(payload)

    assert [item.event_id for item in response.return_recommendations] == [
        "CUT-HISTORICAL-M-CAND"
    ]


def test_silk_result_is_returned_without_any_buffer_warning():
    payload = _silk_payload()
    payload["lines"] = []
    payload["machine_lines"] = []

    response = _evaluate_real_payload(payload)

    assert response.stockout_warnings == []
    assert response.overflow_warnings == []
    assert len(response.silk_screen_results) == 1
    assert response.silk_screen_results[0].current_order_code == "ORD-SILK"
    assert response.silk_screen_results[0].machine_codes == ["M-SILK"]


def test_unconfirmed_plan_does_not_emit_mixing_failure():
    payload = _real_flow_payload()
    payload["machine_process_times"] = []

    response = _evaluate_real_payload(payload)

    assert response.cutline_decisions[0].plan is not None
    assert response.new_active_cutline_events == []
    assert response.mixing_trace_records == []
    assert "mixing_trace_failures" not in response.__class__.model_fields
    mixing_errors = [
        error for error in response.errors if error.stage == "mixing_trace"
    ]
    assert mixing_errors == []
    assert response.errors == []
    assert len(response.persistence_state.pending_cutline_plans) == 1
    assert (
        response.persistence_state.pending_cutline_plans[0].plan_id
        == response.cutline_decisions[0].plan.plan_id
    )


def test_partial_pipeline_error_is_returned_alongside_other_results(monkeypatch):
    pipeline = CutlinePipeline()
    monkeypatch.setattr(
        pipeline._candidate,
        "find_algorithm",
        lambda snapshot, warnings: (_ for _ in ()).throw(
            CandidateMachineCalculationError("candidate boundary failed")
        ),
    )

    response = _evaluate_real_payload(_real_flow_payload(), pipeline=pipeline)

    assert len(response.stockout_warnings) == 1
    assert response.stockout_warnings[0].buffer_code == "BUF-TARGET"
    assert len(response.errors) == 1
    assert response.errors[0].stage == "stockout_candidate"
    assert response.errors[0].reason == "candidate_machine_calculation_error"
    assert response.errors[0].message.startswith("排产/定线-")
    assert response.errors[0].message.endswith("候选机台的关联数据或产能无法计算")
