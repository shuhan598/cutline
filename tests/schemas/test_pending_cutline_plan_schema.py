from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.schemas.pending_cutline_schema import (
    BaselineMachineBinding,
    PendingCandidateMachine,
    PendingCutlinePlan,
    PendingCutlinePlanStatus,
)
from app.schemas.response_schema import CutlineAlgorithmResponse
from app.schemas.result_schema import PendingCutlinePlanEvaluation


NOW = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)


def baseline_payload(machine_code: str = "MC-01") -> dict:
    return {
        "machine_code": machine_code,
        "order_code": "ORD-BASE",
        "product_code": "PROD-BASE",
        "product_name": "baseline-product",
        "wafer_size": "182",
        "wafer_spec": "N",
        "source_grade": "A",
        "process_code": "PROC-OUT",
        "workshop_code": "WS-01",
        "machine_status": "running",
        "observed_at": NOW - timedelta(minutes=1),
    }


def candidate_payload(machine_code: str = "MC-01") -> dict:
    return {
        "machine_code": machine_code,
        "baseline_order_code": "ORD-BASE",
        "baseline_product_code": "PROD-BASE",
        "baseline_product_name": "baseline-product",
        "baseline_wafer_size": "182",
        "baseline_wafer_spec": "N",
        "baseline_source_grade": "A",
        "expected_target_order_code": "ORD-TARGET",
        "expected_target_product_code": "PROD-TARGET",
        "expected_target_product_name": "target-product",
        "expected_target_wafer_size": "182",
        "expected_target_wafer_spec": "N",
        "expected_target_source_grade": "A",
        "process_code": "PROC-OUT",
        "workshop_code": "WS-01",
        "target_buffer_code": "BUF-TARGET",
        "target_upstream_process_code": "PROC-UP",
        "target_downstream_process_code": "PROC-DOWN",
    }


def pending_plan_payload(**updates) -> dict:
    payload = {
        "plan_id": "PLAN-01",
        "warning_id": "WARN-01",
        "warning_type": "stockout",
        "warning_time": NOW - timedelta(minutes=2),
        "created_at": NOW,
        "expire_at": NOW + timedelta(minutes=30),
        "status": "PENDING",
        "workshop_code": "WS-01",
        "buffer_code": "BUF-WARNING",
        "upstream_process_code": "PROC-UP",
        "downstream_process_code": "PROC-DOWN",
        "monitored_order_code": "ORD-TARGET",
        "before_machine_count": 1,
        "before_machine_codes": ["MC-01"],
        "expected_machine_count": 2,
        "expected_delta_direction": "increase",
        "candidate_machines": [candidate_payload()],
        "baseline_machine_bindings": [baseline_payload()],
    }
    payload.update(updates)
    return payload


def empty_pending_plan_payload(**updates) -> dict:
    payload = pending_plan_payload(
        before_machine_count=0,
        before_machine_codes=[],
        expected_machine_count=1,
        candidate_machines=[],
        baseline_machine_bindings=[],
    )
    payload.update(updates)
    return payload


def test_shared_pending_models_are_strict_and_parse_typed_nested_values():
    plan = PendingCutlinePlan.model_validate(pending_plan_payload())

    assert isinstance(plan.warning_time, datetime)
    assert isinstance(plan.candidate_machines[0], PendingCandidateMachine)
    assert isinstance(plan.baseline_machine_bindings[0], BaselineMachineBinding)
    assert isinstance(plan.baseline_machine_bindings[0].observed_at, datetime)
    assert plan.baseline_machine_bindings[0].model_dump()["observed_at"] == (
        NOW - timedelta(minutes=1)
    )
    assert "agv_record_time" not in plan.baseline_machine_bindings[0].model_dump()
    assert plan.candidate_machines[0].source_buffer_code is None
    assert plan.confirmed_machine_codes == []
    assert all(
        model.model_config["extra"] == "forbid"
        for model in (
            BaselineMachineBinding,
            PendingCandidateMachine,
            PendingCutlinePlan,
        )
    )


def test_legacy_agv_record_time_is_input_only_compatibility():
    payload = baseline_payload()
    observed_at = payload.pop("observed_at")
    payload["agv_record_time"] = observed_at

    baseline = BaselineMachineBinding.model_validate(payload)

    assert baseline.observed_at == observed_at
    assert "agv_record_time" not in baseline.model_dump()


def test_pending_evaluation_uses_shared_five_state_enum():
    evaluation = PendingCutlinePlanEvaluation(
        plan_id="PLAN-01",
        warning_id="WARN-01",
        status="CONFIRMED",
        before_machine_count=1,
        before_machine_codes=["MC-01"],
        current_machine_count=2,
        current_machine_codes=["MC-01", "MC-02"],
        expected_machine_count=2,
        expected_delta_direction="increase",
        confirmed_machine_codes=["MC-02"],
        new_confirmed_machine_codes=["MC-02"],
    )

    assert evaluation.status is PendingCutlinePlanStatus.CONFIRMED
    with pytest.raises(ValidationError):
        PendingCutlinePlanEvaluation(
            **evaluation.model_dump(exclude={"status"}),
            status="COMPLETED",
        )


@pytest.mark.parametrize("field", ("plan_id", "warning_id"))
def test_pending_plan_identifiers_reject_whitespace_only(field):
    payload = pending_plan_payload()
    payload[field] = "   "

    with pytest.raises(ValidationError) as error:
        PendingCutlinePlan.model_validate(payload)

    assert field in str(error.value)
    assert "blank" in str(error.value)


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (BaselineMachineBinding, baseline_payload()),
        (PendingCandidateMachine, candidate_payload()),
        (PendingCutlinePlan, pending_plan_payload()),
    ],
)
def test_shared_pending_models_reject_extra_fields(model, payload):
    payload["unexpected"] = True

    with pytest.raises(ValidationError) as error:
        model.model_validate(payload)

    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_pending_plan_accepts_valid_partially_confirmed_state():
    plan = PendingCutlinePlan.model_validate(
        pending_plan_payload(
            status="PARTIALLY_CONFIRMED",
            expected_machine_count=3,
            confirmed_machine_codes=["MC-01"],
        )
    )

    assert plan.status == "PARTIALLY_CONFIRMED"
    assert plan.confirmed_machine_codes == ["MC-01"]


@pytest.mark.parametrize(
    ("status", "expected_machine_count", "confirmed_machine_codes"),
    [
        ("PENDING", 2, []),
        ("PARTIALLY_CONFIRMED", 3, ["MC-01"]),
        ("CONFIRMED", 2, ["MC-01"]),
        ("RETURN_SUGGESTED", 2, ["MC-01"]),
        ("EXPIRED", 2, []),
    ],
)
def test_pending_plan_status_state_machine_accepts_consistent_states(
    status, expected_machine_count, confirmed_machine_codes
):
    plan = PendingCutlinePlan.model_validate(
        pending_plan_payload(
            status=status,
            expected_machine_count=expected_machine_count,
            confirmed_machine_codes=confirmed_machine_codes,
        )
    )

    assert isinstance(plan.status, PendingCutlinePlanStatus)
    assert plan.status.value == status


@pytest.mark.parametrize(
    ("status", "expected_machine_count", "confirmed_machine_codes"),
    [
        ("PARTIALLY_CONFIRMED", 2, ["MC-01"]),
        ("CONFIRMED", 3, ["MC-01"]),
        ("RETURN_SUGGESTED", 3, ["MC-01"]),
        ("EXPIRED", 2, ["MC-01"]),
    ],
)
def test_pending_plan_status_state_machine_rejects_inconsistent_counts(
    status, expected_machine_count, confirmed_machine_codes
):
    with pytest.raises(ValidationError):
        PendingCutlinePlan.model_validate(
            pending_plan_payload(
                status=status,
                expected_machine_count=expected_machine_count,
                confirmed_machine_codes=confirmed_machine_codes,
            )
        )


def test_pending_plan_derives_and_validates_candidate_machine_code_summary():
    plan = PendingCutlinePlan.model_validate(pending_plan_payload())

    assert plan.candidate_machine_codes == ["MC-01"]

    with pytest.raises(ValidationError, match="candidate_machine_codes"):
        PendingCutlinePlan.model_validate(
            pending_plan_payload(candidate_machine_codes=["MC-OTHER"])
        )


def test_confirmed_machine_count_cannot_exceed_required_delta():
    second_baseline = baseline_payload("MC-02")
    second_baseline.update(
        {
            "order_code": "ORD-OTHER",
            "product_code": "PROD-OTHER",
            "product_name": "other-product",
        }
    )

    with pytest.raises(ValidationError) as error:
        PendingCutlinePlan.model_validate(
            pending_plan_payload(
                status="PARTIALLY_CONFIRMED",
                confirmed_machine_codes=["MC-01", "MC-02"],
                baseline_machine_bindings=[
                    baseline_payload(),
                    second_baseline,
                ],
            )
        )

    message = str(error.value)
    assert "PLAN-01" in message
    assert "confirmed_count=2" in message
    assert "required_delta=1" in message


def test_stockout_confirmed_machine_baseline_must_differ_from_monitored_order():
    monitored_baseline = baseline_payload()
    monitored_baseline["order_code"] = "ORD-TARGET"

    with pytest.raises(ValidationError) as error:
        PendingCutlinePlan.model_validate(
                pending_plan_payload(
                    status="PARTIALLY_CONFIRMED",
                    expected_machine_count=3,
                    confirmed_machine_codes=["MC-01"],
                baseline_machine_bindings=[monitored_baseline],
            )
        )

    message = str(error.value)
    assert "PLAN-01" in message
    assert "stockout" in message
    assert "MC-01" in message
    assert "ORD-TARGET" in message


def test_overflow_confirmed_machine_baseline_must_equal_monitored_order():
    with pytest.raises(ValidationError) as error:
        PendingCutlinePlan.model_validate(
            pending_plan_payload(
                warning_type="overflow",
                expected_delta_direction="decrease",
                expected_machine_count=0,
                    status="CONFIRMED",
                confirmed_machine_codes=["MC-01"],
            )
        )

    message = str(error.value)
    assert "PLAN-01" in message
    assert "overflow" in message
    assert "MC-01" in message
    assert "ORD-BASE" in message
    assert "ORD-TARGET" in message


def test_valid_non_candidate_machine_may_be_partially_confirmed():
    non_candidate_baseline = baseline_payload("MC-02")
    non_candidate_baseline.update(
        {
            "order_code": "ORD-OTHER",
            "product_code": "PROD-OTHER",
            "product_name": "other-product",
        }
    )

    plan = PendingCutlinePlan.model_validate(
        pending_plan_payload(
                status="PARTIALLY_CONFIRMED",
                expected_machine_count=3,
                confirmed_machine_codes=["MC-02"],
            baseline_machine_bindings=[
                baseline_payload(),
                non_candidate_baseline,
            ],
        )
    )

    assert plan.confirmed_machine_codes == ["MC-02"]
    assert [item.machine_code for item in plan.candidate_machines] == [
        "MC-01"
    ]


def test_pending_plan_list_defaults_are_independent():
    first = PendingCutlinePlan.model_validate(empty_pending_plan_payload())
    second = PendingCutlinePlan.model_validate(empty_pending_plan_payload())

    for field_name in (
        "candidate_machines",
        "baseline_machine_bindings",
        "confirmed_machine_codes",
    ):
        assert getattr(first, field_name) == []
        assert getattr(first, field_name) is not getattr(second, field_name)
        assert PendingCutlinePlan.model_fields[field_name].default_factory is list


@pytest.mark.parametrize("field_name", ["plan_id", "warning_id"])
def test_pending_plan_rejects_empty_identifiers(field_name):
    with pytest.raises(ValidationError):
        PendingCutlinePlan.model_validate(
            pending_plan_payload(**{field_name: ""})
        )


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("warning_type", "shortage"),
        ("status", "COMPLETED"),
        ("expected_delta_direction", "unchanged"),
    ],
)
def test_pending_plan_rejects_values_outside_literal_contract(
    field_name,
    invalid_value,
):
    with pytest.raises(ValidationError):
        PendingCutlinePlan.model_validate(
            pending_plan_payload(**{field_name: invalid_value})
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"created_at": NOW + timedelta(minutes=30)},
        {"created_at": NOW + timedelta(minutes=31)},
    ],
)
def test_pending_plan_requires_created_at_before_expire_at(updates):
    with pytest.raises(ValidationError) as error:
        PendingCutlinePlan.model_validate(pending_plan_payload(**updates))

    assert "PLAN-01" in str(error.value)


def test_pending_plan_requires_warning_time_not_after_created_at():
    with pytest.raises(ValidationError) as error:
        PendingCutlinePlan.model_validate(
            pending_plan_payload(warning_time=NOW + timedelta(seconds=1))
        )

    assert "PLAN-01" in str(error.value)


@pytest.mark.parametrize(
    ("warning_time", "created_at", "expire_at"),
    [
        (
            (NOW - timedelta(minutes=2)).replace(tzinfo=None),
            NOW,
            NOW + timedelta(minutes=30),
        ),
        (
            NOW - timedelta(minutes=2),
            NOW.replace(tzinfo=None),
            (NOW + timedelta(minutes=30)).replace(tzinfo=None),
        ),
    ],
)
def test_pending_plan_rejects_mixed_timezone_awareness_between_warning_and_created(
    warning_time,
    created_at,
    expire_at,
):
    with pytest.raises(ValidationError) as error:
        PendingCutlinePlan.model_validate(
            pending_plan_payload(
                warning_time=warning_time,
                created_at=created_at,
                expire_at=expire_at,
            )
        )

    message = str(error.value)
    assert "PLAN-01" in message
    assert "warning_time" in message
    assert "created_at" in message
    assert "timezone awareness" in message


@pytest.mark.parametrize(
    ("warning_time", "created_at", "expire_at"),
    [
        (
            (NOW - timedelta(minutes=2)).replace(tzinfo=None),
            NOW.replace(tzinfo=None),
            NOW + timedelta(minutes=30),
        ),
        (
            NOW - timedelta(minutes=2),
            NOW,
            (NOW + timedelta(minutes=30)).replace(tzinfo=None),
        ),
    ],
)
def test_pending_plan_rejects_mixed_timezone_awareness_between_created_and_expire(
    warning_time,
    created_at,
    expire_at,
):
    with pytest.raises(ValidationError) as error:
        PendingCutlinePlan.model_validate(
            pending_plan_payload(
                warning_time=warning_time,
                created_at=created_at,
                expire_at=expire_at,
            )
        )

    message = str(error.value)
    assert "PLAN-01" in message
    assert "created_at" in message
    assert "expire_at" in message
    assert "timezone awareness" in message


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [("before_machine_count", -1), ("expected_machine_count", -1)],
)
def test_pending_plan_rejects_negative_machine_counts(field_name, invalid_value):
    with pytest.raises(ValidationError):
        PendingCutlinePlan.model_validate(
            pending_plan_payload(**{field_name: invalid_value})
        )


def test_pending_plan_requires_before_count_to_match_code_count():
    with pytest.raises(ValidationError) as error:
        PendingCutlinePlan.model_validate(
            pending_plan_payload(before_machine_count=2)
        )

    message = str(error.value)
    assert "PLAN-01" in message
    assert "2" in message
    assert "1" in message


@pytest.mark.parametrize(
    ("expected_machine_count", "expected_delta_direction"),
    [(2, "increase"), (0, "decrease")],
)
def test_pending_plan_requires_direction_to_match_a_nonzero_machine_delta(
    expected_machine_count, expected_delta_direction
):
    plan = PendingCutlinePlan.model_validate(
        pending_plan_payload(
            expected_machine_count=expected_machine_count,
            expected_delta_direction=expected_delta_direction,
        )
    )

    assert plan.expected_machine_count != plan.before_machine_count


@pytest.mark.parametrize(
    ("expected_machine_count", "expected_delta_direction"),
    [
        (2, "decrease"),
        (0, "increase"),
        (1, "increase"),
        (1, "decrease"),
    ],
)
def test_pending_plan_rejects_wrong_or_zero_expected_machine_direction(
    expected_machine_count, expected_delta_direction
):
    with pytest.raises(ValidationError, match="expected_delta_direction"):
        PendingCutlinePlan.model_validate(
            pending_plan_payload(
                expected_machine_count=expected_machine_count,
                expected_delta_direction=expected_delta_direction,
            )
        )


@pytest.mark.parametrize(
    "updates",
    [
        {
            "before_machine_count": 2,
            "before_machine_codes": ["MC-01", "MC-01"],
        },
        {
            "candidate_machines": [candidate_payload(), candidate_payload()],
        },
        {
            "baseline_machine_bindings": [
                baseline_payload(),
                baseline_payload(),
            ],
        },
        {
            "status": "PARTIALLY_CONFIRMED",
            "confirmed_machine_codes": ["MC-01", "MC-01"],
        },
    ],
)
def test_pending_plan_rejects_duplicate_machine_codes_in_each_list(updates):
    with pytest.raises(ValidationError) as error:
        PendingCutlinePlan.model_validate(pending_plan_payload(**updates))

    message = str(error.value)
    assert "PLAN-01" in message
    assert "MC-01" in message


@pytest.mark.parametrize(
    "updates",
    [
        {
            "before_machine_codes": ["MC-OUTSIDE"],
        },
        {
            "candidate_machines": [candidate_payload("MC-OUTSIDE")],
        },
        {
            "status": "PARTIALLY_CONFIRMED",
            "confirmed_machine_codes": ["MC-OUTSIDE"],
        },
    ],
)
def test_before_candidate_and_confirmed_machines_must_belong_to_baseline(
    updates,
):
    with pytest.raises(ValidationError) as error:
        PendingCutlinePlan.model_validate(pending_plan_payload(**updates))

    message = str(error.value)
    assert "PLAN-01" in message
    assert "MC-OUTSIDE" in message


def test_pending_status_rejects_confirmed_machines():
    with pytest.raises(ValidationError) as error:
        PendingCutlinePlan.model_validate(
            pending_plan_payload(confirmed_machine_codes=["MC-01"])
        )

    message = str(error.value)
    assert "PLAN-01" in message
    assert "MC-01" in message


def test_partially_confirmed_status_requires_a_confirmed_machine():
    with pytest.raises(ValidationError) as error:
        PendingCutlinePlan.model_validate(
            pending_plan_payload(status="PARTIALLY_CONFIRMED")
        )

    message = str(error.value)
    assert "PLAN-01" in message
    assert "0" in message


def test_public_response_top_level_contract_does_not_expose_pending_state():
    fields = set(CutlineAlgorithmResponse.model_fields)

    assert "pending_cutline_plans" not in fields
    assert "agv_binding_history" not in fields
