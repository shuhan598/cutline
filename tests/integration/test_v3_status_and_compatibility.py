import pytest

from app.core.candidate_machine.stockout_candidate_finder import (
    StockoutCandidateFinder,
)
from app.core.candidate_machine.product_compatibility import (
    is_source_grade_compatible,
    is_wafer_spec_compatible,
)
from app.core.net_rate.net_rate_calculator import (
    NetRateCalculationError,
    NetRateCalculator,
)
from app.schemas.result_schema import AlgorithmStockoutWarningResult
from app.service.cutline_pipeline import CutlinePipeline
from tests.fixtures.v3_full_route_factory import (
    TARGET_BUFFER_CODE,
    build_base_request_payload,
    build_stockout_manual_payload,
)
from tests.integration.helpers import evaluate, snapshot


def test_v3_backend_running_and_abnormal_statuses_map_and_filter_consistently():
    algorithm_snapshot = snapshot(build_base_request_payload())
    runtime_by_code = {
        item.machine_code: item for item in algorithm_snapshot.machine_runtimes
    }

    assert runtime_by_code["EA001"].status == "running"
    assert runtime_by_code["EA002"].status == "stopped"

    manual_payload = build_stockout_manual_payload()
    manual_response = evaluate(manual_payload)
    manual = manual_response.cutline_decisions[0].manual_intervention
    assert manual is not None
    assert manual.model_dump() == {"reason": "no_candidate_machine"}

    internal_manual = CutlinePipeline().evaluate_algorithm(
        snapshot(manual_payload)
    ).cutline_decisions[0].manual_intervention
    assert internal_manual is not None
    assert internal_manual.evaluated_candidate_count == 0


def test_v3_abnormal_machine_quantities_do_not_enter_net_rate_calculation():
    payload = build_base_request_payload()
    abnormal = next(
        item
        for item in payload["machine_realtime"]
        if item["machine_code"] == "EA002"
    )
    abnormal.update(
        {
            "status": "异常",
            "input_quantity": 10000,
            "output_quantity": 10000,
        }
    )

    rates = NetRateCalculator().calculate(snapshot(payload))
    first_buffer = next(
        item
        for item in rates
        if item.buffer_code == "310110301"
        and item.order_code == "ORD-S2-001"
    )

    assert first_buffer.upstream_output_rate == 200
    assert first_buffer.downstream_input_rate == 200
    assert first_buffer.net_consumption_rate == 0


def test_v3_abnormal_machine_cannot_determine_order_wafer_spec():
    payload = build_base_request_payload()
    next(item for item in payload["machine_realtime"] if item["machine_code"] == "EA023")[
        "status"
    ] = "异常"
    payload["buffer_realtime"].append(
        {
            "main_id": f"MAIN-{TARGET_BUFFER_CODE}",
            "buffer_code": TARGET_BUFFER_CODE,
            "bound_source_name": "华晟",
            "current_quantity": 100,
            "current_utilization_rate": 0.001,
        }
    )
    algorithm_snapshot = snapshot(payload)

    with pytest.raises(NetRateCalculationError, match="ORD-S2-003 wafer_spec"):
        NetRateCalculator().calculate(algorithm_snapshot)


def test_v3_r_and_p_specs_are_compatible_only_at_allowed_s2_non_silk_boundary():
    assert is_wafer_spec_compatible(
        current_wafer_spec="R",
        target_wafer_spec="P",
        workshop_code="S2",
        process_name="制绒",
    )
    assert is_wafer_spec_compatible(
        current_wafer_spec="P",
        target_wafer_spec="R",
        workshop_code="S2",
        process_name="制绒",
    )
    assert not is_wafer_spec_compatible(
        current_wafer_spec="R",
        target_wafer_spec="P",
        workshop_code="S2",
        process_name="丝网",
    )
    assert not is_wafer_spec_compatible(
        current_wafer_spec="R",
        target_wafer_spec="P",
        workshop_code="S1",
        process_name="制绒",
    )
    assert is_source_grade_compatible(
        current_source_grade="A",
        target_source_grade="A-",
    )
    assert not is_source_grade_compatible(
        current_source_grade="A-",
        target_source_grade="A",
    )


def test_v3_r_and_p_order_specs_are_inferred_independently_from_machine_lines():
    payload = build_base_request_payload()
    payload["buffer_realtime"].extend(
        [
            {
                "main_id": f"MAIN-{TARGET_BUFFER_CODE}",
                "buffer_code": TARGET_BUFFER_CODE,
                "bound_source_name": "华晟",
                "current_quantity": 100,
                "current_utilization_rate": 0.001,
            },
            {
                "main_id": f"MAIN-{TARGET_BUFFER_CODE}",
                "buffer_code": TARGET_BUFFER_CODE,
                "bound_source_name": "晶澳",
                "current_quantity": 100,
                "current_utilization_rate": 0.001,
            },
        ]
    )

    rates = NetRateCalculator().calculate(snapshot(payload))
    inferred = {
        item.order_code: item.wafer_spec
        for item in rates
        if item.order_code in {"ORD-S2-003", "ORD-S2-004"}
    }

    assert inferred == {"ORD-S2-003": "R", "ORD-S2-004": "P"}


def _r_target_warning(algorithm_snapshot):
    return AlgorithmStockoutWarningResult(
        warning_time=algorithm_snapshot.current_time,
        main_id=f"MAIN-{TARGET_BUFFER_CODE}",
        buffer_code=TARGET_BUFFER_CODE,
        buffer_codes=[TARGET_BUFFER_CODE],
        order_code="ORD-S2-003",
        wafer_size="210",
        wafer_spec="R",
        workshop_code="S2",
        upstream_process_code="制绒",
        downstream_process_code="碱抛",
        current_quantity=100,
        upstream_output_rate=0,
        downstream_input_rate=200,
        net_consumption_rate=200,
        depletion_minutes=30,
        stockout_warning_lead_minutes=30,
    )


def test_v3_r_p_candidate_compatibility_still_requires_size_and_source_grade():
    compatible_snapshot = snapshot(build_base_request_payload())
    candidates = StockoutCandidateFinder().find_algorithm(
        compatible_snapshot,
        [_r_target_warning(compatible_snapshot)],
    )[0].candidates
    assert [item.machine_code for item in candidates] == ["EA024"]

    size_mismatch_payload = build_base_request_payload()
    next(
        item
        for item in size_mismatch_payload["products"]
        if item["product_code"] == "PROD-S2-P"
    )["wafer_size"] = "182"
    size_snapshot = snapshot(size_mismatch_payload)
    assert StockoutCandidateFinder().find_algorithm(
        size_snapshot,
        [_r_target_warning(size_snapshot)],
    )[0].candidates == []

    grade_mismatch_payload = build_base_request_payload()
    next(
        item
        for item in grade_mismatch_payload["products"]
        if item["product_code"] == "PROD-S2-R"
    )["source_grade"] = "A"
    next(
        item
        for item in grade_mismatch_payload["products"]
        if item["product_code"] == "PROD-S2-P"
    )["source_grade"] = "A-"
    grade_snapshot = snapshot(grade_mismatch_payload)
    assert StockoutCandidateFinder().find_algorithm(
        grade_snapshot,
        [_r_target_warning(grade_snapshot)],
    )[0].candidates == []
