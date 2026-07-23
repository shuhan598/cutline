from app.core.cutline_plan.machine_selection_evaluator import (
    MachineSelectionEvaluator,
)
from app.core.cutline_plan.plan_builder import CutlinePlanBuilder
from app.service.cutline_pipeline import CutlinePipeline
from app.schemas.result_schema import (
    AlgorithmBufferOverflowTimeResult,
    AlgorithmIntervalNetRateResult,
    AlgorithmOverflowCandidateMachine,
    AlgorithmOverflowCandidateResult,
    AlgorithmOverflowTargetOption,
)
from tests.fixtures.v3_full_route_factory import (
    TARGET_BUFFER_CODE,
    build_overflow_manual_payload,
    build_overflow_warning_payload,
)
from tests.integration.helpers import evaluate, response_buffer_codes, snapshot


def _internal_result(payload):
    return CutlinePipeline().evaluate_algorithm(snapshot(payload))


def test_v3_overflow_warning_aggregates_internally_but_exposes_only_buffer_risk():
    payload = build_overflow_warning_payload()
    response = evaluate(payload)
    internal_warning = _internal_result(payload).overflow_warnings[0]

    assert response.stockout_warnings == []
    assert len(response.overflow_warnings) == 1
    warning = response.overflow_warnings[0]
    assert warning.buffer_code == TARGET_BUFFER_CODE
    assert warning.total_inventory == 900
    assert warning.remaining_capacity == 100
    assert warning.buffer_growth_rate == 300
    assert warning.overflow_minutes == 20
    assert "order_growth_details" not in warning.model_dump()
    assert [item.order_code for item in internal_warning.order_growth_details] == [
        "ORD-S2-001",
        "ORD-S2-002",
    ]
    assert [item.growth_rate for item in internal_warning.order_growth_details] == [
        100,
        200,
    ]
    assert all(
        item.growth_rate == -item.net_consumption_rate
        for item in internal_warning.order_growth_details
    )


def test_v3_overflow_strict_route_returns_compact_manual_intervention():
    payload = build_overflow_manual_payload()
    response = evaluate(payload)

    warning = response.overflow_warnings[0]
    assert warning.total_inventory == 950
    assert warning.remaining_capacity == 50
    assert warning.buffer_growth_rate == 200
    assert warning.overflow_minutes == 15
    decision = response.cutline_decisions[0]
    assert "plan" not in decision.model_dump()
    manual = decision.manual_intervention
    assert manual is not None
    assert manual.reason == "no_valid_target_order"
    assert manual.model_dump() == {"reason": "no_valid_target_order"}

    internal_manual = _internal_result(
        payload
    ).cutline_decisions[0].manual_intervention
    assert internal_manual is not None
    assert internal_manual.evaluated_candidate_count == 1
    assert internal_manual.rejected_candidate_count == 1
    rejected = internal_manual.rejected_machines[0]
    assert rejected.machine_code == "EA004"
    assert rejected.reason == "target_in_same_overflow_buffer"
    assert rejected.source_buffer_code == TARGET_BUFFER_CODE
    assert rejected.target_buffer_code == TARGET_BUFFER_CODE
    assert response.new_active_cutline_events == []
    assert response.mixing_trace_records == []
    assert response.errors == []


def test_v3_overflow_selection_and_plan_support_distinct_target_buffer_context():
    payload = build_overflow_manual_payload()
    algorithm_snapshot = snapshot(payload)
    warning = CutlinePipeline().evaluate_algorithm(
        algorithm_snapshot
    ).overflow_warnings[0]
    source_detail = next(
        item
        for item in warning.order_growth_details
        if item.order_code == "ORD-S2-002"
    )
    target_buffer_code = "310110303"
    candidate_result = AlgorithmOverflowCandidateResult(
        workshop_code="S2",
        buffer_code=TARGET_BUFFER_CODE,
        upstream_process_code="制绒",
        downstream_process_code="碱抛",
        source_order_code="ORD-S2-002",
        source_product_code="PROD-S2-N-SUPPORT",
        source_wafer_size="182",
        source_wafer_spec="N",
        source_source_grade="A",
        source_growth_rate=source_detail.growth_rate,
        source_net_consumption_rate=source_detail.net_consumption_rate,
        candidates=[
            AlgorithmOverflowCandidateMachine(
                machine_code="EA004",
                machine_name="EA004制绒机",
                status="running",
                workshop_code="S2",
                process_code="制绒",
                process_name="制绒",
                current_order_code="ORD-S2-002",
                current_product_code="PROD-S2-N-SUPPORT",
                current_wafer_size="182",
                current_wafer_spec="N",
                current_source_grade="A",
                input_quantity_30m=300,
                output_quantity_30m=300,
                current_output_rate_per_hour=600,
                reduced_capacity=600,
                utilization_rate=1,
                idle_rate=0,
                target_options=[
                    AlgorithmOverflowTargetOption(
                        target_order_code="ORD-S2-001",
                        target_product_code="PROD-S2-N-TARGET",
                        target_wafer_size="182",
                        target_wafer_spec="N",
                        target_source_grade="A",
                        target_buffer_code=target_buffer_code,
                        target_workshop_code="S2",
                        target_upstream_process_code="碱抛",
                        target_downstream_process_code="背膜",
                        capacity_gap=200,
                        estimated_contribution_capacity=600,
                    )
                ],
            )
        ],
    )
    source_interval = AlgorithmIntervalNetRateResult(
        main_id=warning.main_id,
        buffer_code=TARGET_BUFFER_CODE,
        buffer_codes=list(warning.buffer_codes),
        order_code="ORD-S2-002",
        wafer_size="182",
        wafer_spec="N",
        workshop_code="S2",
        upstream_process_code="制绒",
        downstream_process_code="碱抛",
        current_quantity=750,
        upstream_output_rate=600,
        downstream_input_rate=200,
        net_consumption_rate=-400,
    )
    target_interval = AlgorithmIntervalNetRateResult(
        main_id=f"MAIN-{target_buffer_code}",
        buffer_code=target_buffer_code,
        buffer_codes=[target_buffer_code],
        order_code="ORD-S2-001",
        wafer_size="182",
        wafer_spec="N",
        workshop_code="S2",
        upstream_process_code="碱抛",
        downstream_process_code="背膜",
        current_quantity=1000,
        upstream_output_rate=0,
        downstream_input_rate=200,
        net_consumption_rate=200,
    )
    overflow_states = [
        AlgorithmBufferOverflowTimeResult(
            main_id=warning.main_id,
            buffer_code=TARGET_BUFFER_CODE,
            buffer_codes=list(warning.buffer_codes),
            workshop_code="S2",
            upstream_process_code="制绒",
            downstream_process_code="碱抛",
            max_capacity=1000,
            total_inventory=950,
            remaining_capacity=50,
            buffer_growth_rate=200,
            overflow_minutes=15,
            order_growth_details=warning.order_growth_details,
        ),
        AlgorithmBufferOverflowTimeResult(
            main_id=f"MAIN-{target_buffer_code}",
            buffer_code=target_buffer_code,
            buffer_codes=[target_buffer_code],
            workshop_code="S2",
            upstream_process_code="碱抛",
            downstream_process_code="背膜",
            max_capacity=100000,
            total_inventory=1000,
            remaining_capacity=99000,
            buffer_growth_rate=-200,
            overflow_minutes=None,
            order_growth_details=[],
        ),
    ]

    selection = MachineSelectionEvaluator().select_overflow_machines(
        snapshot=algorithm_snapshot,
        warning=warning,
        candidate_result=candidate_result,
        interval_results=[source_interval, target_interval],
        overflow_results=overflow_states,
    )
    decision = CutlinePlanBuilder().build_overflow_decision(
        algorithm_snapshot,
        warning,
        selection,
    )

    assert selection.risk_resolved is True
    assert selection.total_reduced_capacity == 600
    assert selection.remaining_growth_rate == -400
    assert decision.manual_intervention is None
    assert decision.plan is not None
    assert decision.plan.selected_machines[0].source_buffer_code == TARGET_BUFFER_CODE
    assert decision.plan.selected_machines[0].target_buffer_code == target_buffer_code


def test_v3_overflow_response_preserves_input_numeric_buffer_codes():
    payload = build_overflow_manual_payload()
    input_codes = {item["buffer_code"] for item in payload["buffer_master"]}

    output_codes = response_buffer_codes(evaluate(payload))

    assert output_codes
    assert all(code in input_codes and code.isdigit() for code in output_codes)
