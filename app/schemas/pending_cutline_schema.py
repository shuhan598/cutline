"""定义跨轮持久化的 Pending 切线计划及其一致性约束。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class _PendingCutlineModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PendingCutlinePlanStatus(str, Enum):
    PENDING = "PENDING"
    PARTIALLY_CONFIRMED = "PARTIALLY_CONFIRMED"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"
    RETURN_SUGGESTED = "RETURN_SUGGESTED"


class BaselineMachineBinding(_PendingCutlineModel):
    machine_code: str
    order_code: str
    product_code: str
    product_name: str
    wafer_size: str
    wafer_spec: str
    source_grade: str
    process_code: str
    workshop_code: str
    machine_status: str | None = None
    observed_at: datetime = Field(
        validation_alias=AliasChoices("observed_at", "agv_record_time")
    )


class PendingCandidateMachine(_PendingCutlineModel):
    machine_code: str
    baseline_order_code: str
    baseline_product_code: str
    baseline_product_name: str
    baseline_wafer_size: str
    baseline_wafer_spec: str
    baseline_source_grade: str
    expected_target_order_code: str
    expected_target_product_code: str
    expected_target_product_name: str
    expected_target_wafer_size: str
    expected_target_wafer_spec: str
    expected_target_source_grade: str
    process_code: str
    workshop_code: str
    source_buffer_code: str | None = None
    target_buffer_code: str
    target_upstream_process_code: str
    target_downstream_process_code: str


class PendingCutlinePlan(_PendingCutlineModel):
    plan_id: str = Field(min_length=1)
    warning_id: str = Field(min_length=1)
    warning_type: Literal["stockout", "overflow"]
    warning_time: datetime
    created_at: datetime
    expire_at: datetime
    status: PendingCutlinePlanStatus
    workshop_code: str
    buffer_code: str
    upstream_process_code: str
    downstream_process_code: str
    monitored_order_code: str
    process_code: str | None = None
    source_order_code: str | None = None
    target_order_code: str | None = None
    source_product_code: str | None = None
    target_product_code: str | None = None
    before_machine_count: int = Field(ge=0, strict=True)
    before_machine_codes: list[str]
    expected_machine_count: int = Field(ge=0, strict=True)
    expected_delta_direction: Literal["increase", "decrease"]
    candidate_machines: list[PendingCandidateMachine] = Field(
        default_factory=list
    )
    candidate_machine_codes: list[str] = Field(default_factory=list)
    baseline_machine_bindings: list[BaselineMachineBinding] = Field(
        default_factory=list
    )
    confirmed_machine_codes: list[str] = Field(default_factory=list)

    @field_validator("plan_id", "warning_id")
    @classmethod
    def validate_nonblank_identifier(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("identifier must not be blank")
        return value

    @model_validator(mode="after")
    def validate_plan_consistency(self) -> PendingCutlinePlan:
        _require_matching_timezone_awareness(
            self.plan_id,
            "created_at",
            self.created_at,
            "expire_at",
            self.expire_at,
        )
        _require_matching_timezone_awareness(
            self.plan_id,
            "warning_time",
            self.warning_time,
            "created_at",
            self.created_at,
        )
        if self.created_at >= self.expire_at:
            raise ValueError(
                f"plan_id={self.plan_id}: created_at={self.created_at.isoformat()} "
                f"must be before expire_at={self.expire_at.isoformat()}"
            )
        if self.warning_time > self.created_at:
            raise ValueError(
                f"plan_id={self.plan_id}: warning_time="
                f"{self.warning_time.isoformat()} must not be after "
                f"created_at={self.created_at.isoformat()}"
            )

        before_code_count = len(self.before_machine_codes)
        if self.before_machine_count != before_code_count:
            raise ValueError(
                f"plan_id={self.plan_id}: before_machine_count="
                f"{self.before_machine_count} conflicts with "
                f"before_machine_codes count={before_code_count}"
            )

        collections = (
            ("before_machine_codes", self.before_machine_codes),
            ("candidate_machine_codes", self.candidate_machine_codes),
            (
                "candidate_machines",
                [item.machine_code for item in self.candidate_machines],
            ),
            (
                "baseline_machine_bindings",
                [
                    item.machine_code
                    for item in self.baseline_machine_bindings
                ],
            ),
            ("confirmed_machine_codes", self.confirmed_machine_codes),
        )
        for collection_name, machine_codes in collections:
            duplicate_code = _first_duplicate(machine_codes)
            if duplicate_code is not None:
                raise ValueError(
                    f"plan_id={self.plan_id}: {collection_name} contains "
                    f"duplicate machine_code={duplicate_code}; "
                    f"count={len(machine_codes)}"
                )

        if self.expected_machine_count == self.before_machine_count:
            raise ValueError(
                f"plan_id={self.plan_id}: expected_delta_direction="
                f"{self.expected_delta_direction} requires a nonzero "
                "machine-count delta"
            )
        if (
            self.expected_delta_direction == "increase"
            and self.expected_machine_count <= self.before_machine_count
        ) or (
            self.expected_delta_direction == "decrease"
            and self.expected_machine_count >= self.before_machine_count
        ):
            raise ValueError(
                f"plan_id={self.plan_id}: expected_delta_direction="
                f"{self.expected_delta_direction} conflicts with "
                f"before_machine_count={self.before_machine_count} and "
                f"expected_machine_count={self.expected_machine_count}"
            )

        candidate_codes = [item.machine_code for item in self.candidate_machines]
        if "candidate_machine_codes" not in self.model_fields_set:
            self.candidate_machine_codes = candidate_codes
        elif self.candidate_machine_codes != candidate_codes:
            raise ValueError(
                f"plan_id={self.plan_id}: candidate_machine_codes must "
                "match candidate_machines machine_code values"
            )

        baseline_codes = {
            item.machine_code for item in self.baseline_machine_bindings
        }
        baseline_memberships = (
            ("before_machine_codes", self.before_machine_codes),
            (
                "candidate_machines",
                [item.machine_code for item in self.candidate_machines],
            ),
            ("confirmed_machine_codes", self.confirmed_machine_codes),
        )
        for collection_name, machine_codes in baseline_memberships:
            for machine_code in machine_codes:
                if machine_code not in baseline_codes:
                    raise ValueError(
                        f"plan_id={self.plan_id}: {collection_name} "
                        f"machine_code={machine_code} is absent from "
                        "baseline_machine_bindings; "
                        f"baseline_count={len(baseline_codes)}"
                    )

        confirmed_count = len(self.confirmed_machine_codes)
        required_delta = abs(
            self.expected_machine_count - self.before_machine_count
        )
        if confirmed_count > required_delta:
            raise ValueError(
                f"plan_id={self.plan_id}: confirmed_count={confirmed_count} "
                f"exceeds required_delta={required_delta} calculated from "
                f"before_machine_count={self.before_machine_count} and "
                f"expected_machine_count={self.expected_machine_count}"
            )

        if self.status is PendingCutlinePlanStatus.PENDING:
            is_valid = confirmed_count == 0
        elif self.status is PendingCutlinePlanStatus.PARTIALLY_CONFIRMED:
            is_valid = 0 < confirmed_count < required_delta
        elif self.status in {
            PendingCutlinePlanStatus.CONFIRMED,
            PendingCutlinePlanStatus.RETURN_SUGGESTED,
        }:
            is_valid = confirmed_count == required_delta
        else:  # EXPIRED
            is_valid = confirmed_count < required_delta
        if not is_valid:
            raise ValueError(
                f"plan_id={self.plan_id}: status={self.status.value} "
                f"conflicts with confirmed_count={confirmed_count} and "
                f"required_delta={required_delta}"
            )

        baseline_by_machine = {
            item.machine_code: item for item in self.baseline_machine_bindings
        }
        for machine_code in self.confirmed_machine_codes:
            baseline_order_code = baseline_by_machine[machine_code].order_code
            if (
                self.warning_type == "stockout"
                and baseline_order_code == self.monitored_order_code
            ):
                raise ValueError(
                    f"plan_id={self.plan_id}: stockout confirmed "
                    f"machine_code={machine_code} baseline order="
                    f"{baseline_order_code!r} must differ from monitored "
                    f"order={self.monitored_order_code!r}"
                )
        return self


def _require_matching_timezone_awareness(
    plan_id: str,
    left_field: str,
    left_value: datetime,
    right_field: str,
    right_value: datetime,
) -> None:
    left_is_aware = left_value.utcoffset() is not None
    right_is_aware = right_value.utcoffset() is not None
    if left_is_aware != right_is_aware:
        left_kind = "aware" if left_is_aware else "naive"
        right_kind = "aware" if right_is_aware else "naive"
        raise ValueError(
            f"plan_id={plan_id}: timezone awareness conflict between "
            f"{left_field} ({left_kind}) and {right_field} ({right_kind})"
        )


def _first_duplicate(machine_codes: list[str]) -> str | None:
    seen: set[str] = set()
    for machine_code in machine_codes:
        if machine_code in seen:
            return machine_code
        seen.add(machine_code)
    return None
