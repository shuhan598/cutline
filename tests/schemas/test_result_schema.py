from app.schemas.common_schema import MachineRuntimeStatus
from app.schemas.result_schema import (
    CandidateMachine,
    CandidateResult,
    DepletionResult,
    NetRateResult,
    StockoutWarningResult,
)


def test_machine_runtime_status_has_equipment_name():
    machine = MachineRuntimeStatus(
        equipment_code="zr01",
        equipment_name="ZR 01",
        process_code="ZR",
        status="running",
    )
    assert machine.equipment_name == "ZR 01"


def test_net_rate_result_field_names_match_dict_contract():
    result = NetRateResult(
        buffer_code="BUF",
        product_code="P",
        process_from="ZR",
        process_to="PK",
        inventory_quantity=1.0,
        upstream_output_per_hour=1.0,
        downstream_input_per_hour=2.0,
        net_rate_per_hour=1.0,
        upstream_equipment_codes=["a"],
        downstream_equipment_codes=["b"],
    )
    assert set(result.model_dump()) == {
        "buffer_code",
        "cycle_code",
        "cycle_name",
        "workshop_code",
        "workshop_name",
        "product_code",
        "process_from",
        "process_to",
        "inventory_quantity",
        "upstream_output_per_hour",
        "downstream_input_per_hour",
        "net_rate_per_hour",
        "upstream_equipment_codes",
        "downstream_equipment_codes",
    }


def test_stockout_warning_result_has_twelve_contract_fields():
    result = StockoutWarningResult(
        buffer_code="BUF",
        product_code="P",
        process_from="ZR",
        process_to="PK",
        warning_type="stockout",
        warning_triggered=True,
        reason="depletion_time_within_lead_time",
        inventory_quantity=1.0,
        net_rate_per_hour=1.0,
        depletion_minutes=10.0,
        depletion_status="decreasing",
        cutline_lead_minutes=30.0,
    )
    assert set(result.model_dump()) == {
        "buffer_code",
        "cycle_code",
        "cycle_name",
        "workshop_code",
        "workshop_name",
        "product_code",
        "process_from",
        "process_to",
        "warning_type",
        "warning_triggered",
        "reason",
        "inventory_quantity",
        "net_rate_per_hour",
        "depletion_minutes",
        "depletion_status",
        "cutline_lead_minutes",
    }


def test_candidate_result_holds_candidate_machines():
    machine = CandidateMachine(
        equipment_code="zr03",
        equipment_name="ZR 03",
        process_code="ZR",
        current_product_code="HG182R",
        target_product_code="HG182T",
        wafer_size="182",
        shape_code="R",
        current_output_rate_per_hour=8000.0,
        contribution_capacity_per_hour=None,
        reason="same_process_size_shape_running_machine",
    )
    result = CandidateResult(
        buffer_code="BUF",
        product_code="HG182T",
        process_from="ZR",
        process_to="PK",
        candidate_found=True,
        candidate_status="candidate_found",
        reason=None,
        candidates=[machine],
    )
    assert result.candidates[0].equipment_code == "zr03"
    assert "priority_rank" not in result.model_dump()


def test_depletion_result_allows_none_minutes():
    result = DepletionResult(
        buffer_code="BUF",
        product_code="P",
        process_from="ZR",
        process_to="PK",
        inventory_quantity=0.0,
        net_rate_per_hour=0.0,
        depletion_minutes=None,
        depletion_status="stable",
    )
    assert result.depletion_minutes is None
