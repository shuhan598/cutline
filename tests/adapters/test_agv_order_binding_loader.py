from copy import deepcopy
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.adapters.backend_request_loader import (
    BackendRequestLoadError,
    BackendRequestLoader,
)
from app.schemas.request_schema import AgvRelationRequest


def raw_agv_record() -> dict:
    return {
        "equipmentid": "EA003",
        "equipmentname": "EA003制绒机",
        "lastlinecode": "ORD-S2-001",
        "lastlinename": "至上",
        "waferspec": "N",
        "createtime": "2026-07-23 10:23:39",
    }


def standard_agv_record() -> dict:
    return {
        "machine_code": "EA003",
        "machine_name": "EA003制绒机",
        "order_code": "ORD-S2-001",
        "order_name": "至上",
        "wafer_spec": "N",
        "binding_time": "2026-07-23 10:23:39",
    }


def test_normalize_payload_maps_raw_agv_fields_without_mutating_input():
    payload = {"agv_relations": [raw_agv_record()]}
    original = deepcopy(payload)

    normalized = BackendRequestLoader().normalize_payload(payload)

    assert normalized == {"agv_relations": [standard_agv_record()]}
    assert payload == original
    assert normalized is not payload
    assert normalized["agv_relations"] is not payload["agv_relations"]
    assert normalized["agv_relations"][0] is not payload["agv_relations"][0]


def test_raw_agv_onsite_fields_are_filtered_including_process_fields():
    record = raw_agv_record()
    record.update(
        {
            "equipmentcode": "DO-NOT-USE",
            "processcode": "WRONG-PROCESS",
            "processname": "错误工序",
            "linecode": "ONSITE-LINE",
            "linename": "现场路线",
            "inputQuantity": 123,
            "unknownOnsiteField": "ignored",
        }
    )

    normalized = BackendRequestLoader().normalize_payload(
        {"agv_relations": [record]}
    )

    assert normalized["agv_relations"] == [standard_agv_record()]
    assert set(normalized["agv_relations"][0]) == {
        "machine_code",
        "machine_name",
        "order_code",
        "order_name",
        "wafer_spec",
        "binding_time",
    }


def test_equipmentcode_is_never_used_as_machine_code():
    record = raw_agv_record()
    del record["equipmentid"]
    record["equipmentcode"] = "EA-WRONG"

    normalized = BackendRequestLoader().normalize_payload(
        {"agv_relations": [record]}
    )

    assert "machine_code" not in normalized["agv_relations"][0]


def test_standard_agv_record_is_preserved_for_strict_schema_validation():
    record = standard_agv_record()
    record["machine_cod"] = "TYPO"

    normalized = BackendRequestLoader().normalize_payload(
        {"agv_relations": [record]}
    )

    assert normalized["agv_relations"][0] == record
    with pytest.raises(ValidationError) as error:
        AgvRelationRequest.model_validate(normalized["agv_relations"][0])
    assert error.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize(
    ("raw_field", "standard_field"),
    [
        ("equipmentid", "machine_code"),
        ("equipmentname", "machine_name"),
        ("lastlinecode", "order_code"),
        ("lastlinename", "order_name"),
        ("waferspec", "wafer_spec"),
        ("createtime", "binding_time"),
    ],
)
def test_matching_raw_and_standard_fields_collapse_to_standard(
    raw_field: str,
    standard_field: str,
):
    record = raw_agv_record()
    standard = standard_agv_record()
    record[standard_field] = standard[standard_field]

    normalized = BackendRequestLoader().normalize_payload(
        {"agv_relations": [record]}
    )

    assert normalized["agv_relations"][0] == standard_agv_record()
    assert raw_field not in normalized["agv_relations"][0]


def test_equivalent_raw_and_standard_binding_times_do_not_conflict():
    record = raw_agv_record()
    record["binding_time"] = datetime(
        2026,
        7,
        23,
        2,
        23,
        39,
        tzinfo=timezone.utc,
    )

    normalized = BackendRequestLoader().normalize_payload(
        {"agv_relations": [record]}
    )

    assert normalized["agv_relations"][0]["binding_time"] == record[
        "binding_time"
    ]


@pytest.mark.parametrize(
    ("raw_field", "standard_field", "standard_value"),
    [
        ("equipmentid", "machine_code", "EA004"),
        ("equipmentname", "machine_name", "另一台机"),
        ("lastlinecode", "order_code", "ORD-S2-002"),
        ("lastlinename", "order_name", "另一订单"),
        ("waferspec", "wafer_spec", "R"),
        ("createtime", "binding_time", "2026-07-23 10:24:00"),
    ],
)
def test_conflicting_raw_and_standard_fields_raise_explicit_load_error(
    raw_field: str,
    standard_field: str,
    standard_value: str,
):
    record = raw_agv_record()
    record[standard_field] = standard_value

    with pytest.raises(BackendRequestLoadError) as error:
        BackendRequestLoader().normalize_payload(
            {"agv_relations": [raw_agv_record(), record]}
        )

    message = str(error.value)
    assert "agv_relations[1]" in message
    assert raw_field in message
    assert standard_field in message
    assert repr(record[raw_field]) in message
    assert repr(standard_value) in message


def test_missing_createtime_is_not_defaulted_by_loader():
    record = raw_agv_record()
    del record["createtime"]

    normalized = BackendRequestLoader().normalize_payload(
        {"agv_relations": [record]}
    )

    assert "binding_time" not in normalized["agv_relations"][0]
    with pytest.raises(ValidationError) as error:
        AgvRelationRequest.model_validate(normalized["agv_relations"][0])
    assert error.value.errors()[0]["loc"] == ("binding_time",)
    assert error.value.errors()[0]["type"] == "missing"


def test_non_agv_payload_content_is_deep_copied_but_not_changed():
    payload = {
        "machine_realtime": [{"machine_code": "EA003"}],
        "orders": [{"order_code": "ORD-S2-001"}],
        "agv_relations": [],
    }

    normalized = BackendRequestLoader().normalize_payload(payload)

    assert normalized == payload
    assert normalized is not payload
    assert normalized["machine_realtime"] is not payload["machine_realtime"]
