from copy import deepcopy

import pytest

from app.adapters.snapshot_adapter import SnapshotAdapter
from app.mappers.algorithm_response_mapper import AlgorithmResponseMapper
from app.schemas.request_schema import CutlineAlgorithmRequest
from app.schemas.response_schema import CutlineAlgorithmResponse
from app.service.cutline_pipeline import CutlinePipeline
from app.service.cutline_service import CutlineService
from tests.fixtures.v3_full_route_factory import (
    V3_SCENARIO_BUILDERS,
    build_no_warning_payload,
)


def test_v3_no_warning_runs_the_real_public_chain_without_mutating_inputs():
    payload = build_no_warning_payload()
    payload_before = deepcopy(payload)
    request = CutlineAlgorithmRequest.model_validate(payload)
    request_before = request.model_dump()
    snapshot = SnapshotAdapter().to_algorithm_snapshot(request)
    snapshot_before = snapshot.model_dump()

    result = CutlinePipeline().evaluate_algorithm(snapshot)
    response = AlgorithmResponseMapper().to_response(result)

    assert isinstance(response, CutlineAlgorithmResponse)
    assert response.stockout_warnings == []
    assert response.overflow_warnings == []
    assert response.cutline_decisions == []
    assert response.new_active_cutline_events == []
    assert response.mixing_trace_records == []
    assert response.errors == []
    assert payload == payload_before
    assert request.model_dump() == request_before
    assert snapshot.model_dump() == snapshot_before


def test_v3_identical_inputs_produce_stable_complete_results():
    payload = build_no_warning_payload()
    request = CutlineAlgorithmRequest.model_validate(payload)
    service_pipeline = CutlinePipeline()
    adapter = SnapshotAdapter()
    mapper = AlgorithmResponseMapper()

    first = mapper.to_response(
        service_pipeline.evaluate_algorithm(adapter.to_algorithm_snapshot(request))
    )
    second = mapper.to_response(
        service_pipeline.evaluate_algorithm(adapter.to_algorithm_snapshot(request))
    )

    assert first.model_dump() == second.model_dump()


@pytest.mark.parametrize("scenario_name", sorted(V3_SCENARIO_BUILDERS))
def test_v3_scenario_service_results_are_deterministic_and_request_is_immutable(
    scenario_name,
):
    payload = V3_SCENARIO_BUILDERS[scenario_name]()
    request = CutlineAlgorithmRequest.model_validate(payload)
    before = request.model_dump()
    service = CutlineService()

    first = service.evaluate_algorithm(request)
    second = service.evaluate_algorithm(request)

    assert first.model_dump() == second.model_dump()
    assert len(first.stockout_warnings) + len(first.overflow_warnings) <= 1
    assert request.model_dump() == before
