from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.backend_request_schema import (
    BackendAgvRelation,
    BackendMachineRealtime,
)
from app.schemas.common_schema import AlgorithmAgvRelation
from app.schemas.request_schema import AgvRelationRequest, MachineRealtimeRequest


RAW_AGV_FIELDS = {
    "equipmentid",
    "equipmentname",
    "lastlinecode",
    "lastlinename",
    "waferspec",
    "createtime",
}
STANDARD_AGV_FIELDS = {
    "machine_code",
    "machine_name",
    "order_code",
    "order_name",
    "wafer_spec",
    "binding_time",
}


def backend_runtime_payload() -> dict:
    return {
        "machine_code": "EA003",
        "status": "运行",
        "tangent_time": None,
        "input_quantity": 10.0,
        "output_quantity": 9.0,
        "completed_quantity": 100.0,
    }


def standard_runtime_payload() -> dict:
    return {
        **backend_runtime_payload(),
        "period_quantity": 8.0,
        "out_time": None,
    }


def test_external_machine_realtime_contracts_do_not_expose_order_code():
    assert "order_code" not in BackendMachineRealtime.model_fields
    assert "order_code" not in MachineRealtimeRequest.model_fields

    assert BackendMachineRealtime.model_validate(
        backend_runtime_payload()
    ).machine_code == "EA003"
    assert MachineRealtimeRequest.model_validate(
        standard_runtime_payload()
    ).machine_code == "EA003"


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (BackendMachineRealtime, backend_runtime_payload()),
        (MachineRealtimeRequest, standard_runtime_payload()),
    ],
)
def test_external_machine_realtime_rejects_legacy_order_code(model, payload):
    payload["order_code"] = "ORD-S2-001"

    with pytest.raises(ValidationError) as error:
        model.model_validate(payload)

    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_backend_agv_contract_exposes_only_raw_customer_fields():
    assert set(BackendAgvRelation.model_fields) == RAW_AGV_FIELDS

    relation = BackendAgvRelation.model_validate(
        {
            "equipmentid": "EA003",
            "equipmentname": "EA003制绒机",
            "lastlinecode": "ORD-S2-001",
            "lastlinename": "至上",
            "waferspec": "N",
            "createtime": "2026-07-23 10:23:39",
        }
    )

    assert relation.equipmentid == "EA003"
    assert isinstance(relation.createtime, datetime)


@pytest.mark.parametrize("model", [AgvRelationRequest, AlgorithmAgvRelation])
def test_algorithm_agv_contracts_expose_only_standard_fields(model):
    assert set(model.model_fields) == STANDARD_AGV_FIELDS

    relation = model.model_validate(
        {
            "machine_code": "EA003",
            "machine_name": "EA003制绒机",
            "order_code": "ORD-S2-001",
            "order_name": "至上",
            "wafer_spec": "N",
            "binding_time": "2026-07-23T10:23:39+08:00",
        }
    )

    assert relation.order_code == "ORD-S2-001"
    assert isinstance(relation.binding_time, datetime)


@pytest.mark.parametrize("model", [AgvRelationRequest, AlgorithmAgvRelation])
@pytest.mark.parametrize(
    "legacy_field",
    [
        "buffer_code",
        "line_code",
        "line_name",
        "last_line_code",
        "last_line_name",
        "process_code",
        "process_name",
    ],
)
def test_algorithm_agv_contracts_reject_legacy_fields(model, legacy_field):
    payload = {
        "machine_code": "EA003",
        "machine_name": "EA003制绒机",
        "order_code": "ORD-S2-001",
        "order_name": "至上",
        "wafer_spec": "N",
        "binding_time": "2026-07-23T10:23:39+08:00",
        legacy_field: "obsolete",
    }

    with pytest.raises(ValidationError) as error:
        model.model_validate(payload)

    assert error.value.errors()[0]["type"] == "extra_forbidden"
