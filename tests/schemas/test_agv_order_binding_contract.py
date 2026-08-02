from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.backend_request_schema import (
    BackendAgvRelation,
    BackendMachineMaster,
    BackendMachineRealtime,
)
from app.schemas.common_schema import AlgorithmAgvRelation
from app.schemas.request_schema import (
    AgvRelationRequest,
    MachineMasterRequest,
    MachineRealtimeRequest,
)


RAW_AGV_FIELDS = {
    "equipmentid",
    "equipmentname",
    "linename",
    "lastlinename",
    "waferspec",
    "createtime",
}
STANDARD_REQUEST_AGV_FIELDS = {
    "machine_code",
    "machine_name",
    "product_name",
    "previous_product_name",
    "wafer_spec",
    "binding_time",
}
INTERNAL_AGV_FIELDS = {
    "machine_code",
    "machine_name",
    "order_code",
    "product_code",
    "product_name",
    "previous_product_code",
    "previous_product_name",
    "wafer_spec",
    "binding_time",
}


def backend_runtime_payload() -> dict:
    return {
        "machine_code": "P166-EA003",
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
    ).machine_code == "P166-EA003"
    assert MachineRealtimeRequest.model_validate(
        standard_runtime_payload()
    ).machine_code == "P166-EA003"


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


@pytest.mark.parametrize("model", [BackendMachineMaster, MachineMasterRequest])
def test_machine_master_contract_requires_realtime_identifier(model):
    payload = {
        "machine_code": "EA003",
        "p166_jt_group": "P166-EA003",
        "machine_name": "EA003制绒机",
        "process_code": "P-ZR",
        "process_name": "制绒",
    }

    assert model.model_validate(payload).p166_jt_group == "P166-EA003"

    del payload["p166_jt_group"]
    with pytest.raises(ValidationError) as error:
        model.model_validate(payload)
    assert error.value.errors()[0]["loc"] == ("p166_jt_group",)
    assert error.value.errors()[0]["type"] == "missing"


def test_backend_agv_contract_exposes_current_and_previous_product_names():
    assert set(BackendAgvRelation.model_fields) == RAW_AGV_FIELDS

    relation = BackendAgvRelation.model_validate(
        {
            "equipmentid": "EA003",
            "equipmentname": "EA003制绒机",
            "linename": "182N至上产品",
            "lastlinename": None,
            "waferspec": "N",
            "createtime": "2026-07-23 10:23:39",
        }
    )

    assert relation.linename == "182N至上产品"
    assert relation.lastlinename is None
    assert isinstance(relation.createtime, datetime)


def test_backend_agv_contract_rejects_removed_lastlinecode():
    payload = {
        "equipmentid": "EA003",
        "equipmentname": "EA003制绒机",
        "linename": "182N至上产品",
        "lastlinename": "210R上一产品",
        "waferspec": "N",
        "createtime": "2026-07-23 10:23:39",
        "lastlinecode": "ORD-LEGACY",
    }

    with pytest.raises(ValidationError) as error:
        BackendAgvRelation.model_validate(payload)

    assert error.value.errors()[0]["loc"] == ("lastlinecode",)
    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_standard_agv_request_contains_product_names_without_order_identity():
    assert set(AgvRelationRequest.model_fields) == STANDARD_REQUEST_AGV_FIELDS

    relation = AgvRelationRequest.model_validate(
        {
            "machine_code": "EA003",
            "machine_name": "EA003制绒机",
            "product_name": "182N至上产品",
            "previous_product_name": None,
            "wafer_spec": "N",
            "binding_time": "2026-07-23T10:23:39+08:00",
        }
    )

    assert relation.product_name == "182N至上产品"
    assert relation.previous_product_name is None
    assert isinstance(relation.binding_time, datetime)


def test_internal_agv_contract_keeps_current_and_previous_product_identity():
    assert set(AlgorithmAgvRelation.model_fields) == INTERNAL_AGV_FIELDS

    relation = AlgorithmAgvRelation.model_validate(
        {
            "machine_code": "EA003",
            "machine_name": "EA003制绒机",
            "order_code": "ORD-S2-001",
            "product_code": "PROD-S2-001",
            "product_name": "182N至上产品",
            "previous_product_code": "PROD-S2-OLD",
            "previous_product_name": "182N上一产品",
            "wafer_spec": "N",
            "binding_time": "2026-07-23T10:23:39+08:00",
        }
    )

    assert relation.order_code == "ORD-S2-001"
    assert relation.product_code == "PROD-S2-001"
    assert relation.product_name == "182N至上产品"
    assert relation.previous_product_code == "PROD-S2-OLD"
    assert relation.previous_product_name == "182N上一产品"


def test_internal_agv_previous_product_identity_defaults_to_none():
    relation = AlgorithmAgvRelation.model_validate(
        {
            "machine_code": "EA003",
            "machine_name": "EA003制绒机",
            "order_code": "ORD-S2-001",
            "product_code": "PROD-S2-001",
            "product_name": "182N至上产品",
            "wafer_spec": "N",
            "binding_time": "2026-07-23T10:23:39+08:00",
        }
    )

    assert relation.previous_product_code is None
    assert relation.previous_product_name is None


@pytest.mark.parametrize(
    ("model", "payload", "legacy_field"),
    [
        (
            AgvRelationRequest,
            {
                "machine_code": "EA003",
                "machine_name": "EA003制绒机",
                "product_name": "182N至上产品",
                "previous_product_name": None,
                "wafer_spec": "N",
                "binding_time": "2026-07-23T10:23:39+08:00",
            },
            "order_code",
        ),
        (
            AgvRelationRequest,
            {
                "machine_code": "EA003",
                "machine_name": "EA003制绒机",
                "product_name": "182N至上产品",
                "previous_product_name": None,
                "wafer_spec": "N",
                "binding_time": "2026-07-23T10:23:39+08:00",
            },
            "order_name",
        ),
        (
            AlgorithmAgvRelation,
            {
                "machine_code": "EA003",
                "machine_name": "EA003制绒机",
                "order_code": "ORD-S2-001",
                "product_code": "PROD-S2-001",
                "product_name": "182N至上产品",
                "wafer_spec": "N",
                "binding_time": "2026-07-23T10:23:39+08:00",
            },
            "order_name",
        ),
    ],
)
def test_algorithm_agv_contracts_reject_removed_order_fields(
    model,
    payload,
    legacy_field,
):
    payload[legacy_field] = "obsolete"

    with pytest.raises(ValidationError) as error:
        model.model_validate(payload)

    assert error.value.errors()[0]["type"] == "extra_forbidden"
