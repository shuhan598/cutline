"""Internal data structures for one shared main Buffer aggregation batch."""

from __future__ import annotations

from dataclasses import dataclass, field


CAPABILITY_NAMES = (
    "stockout_eligible",
    "overflow_eligible",
    "stockout_warning_eligible",
    "overflow_warning_eligible",
    "auto_receive_eligible",
    "auto_donate_eligible",
)


@dataclass(frozen=True, order=True)
class PhysicalBufferKey:
    workshop_code: str
    ordered_service_process_codes: tuple[str, ...]


@dataclass(frozen=True, order=True)
class GroupKey:
    physical_buffer_key: PhysicalBufferKey
    main_id: str
    order_code: str


@dataclass(frozen=True)
class MainBufferAggregationIssue:
    code: str
    main_id: str
    representative_buffer_code: str | None
    message: str
    affected_capabilities: tuple[str, ...]


@dataclass(frozen=True)
class MainBufferGroup:
    group_key: GroupKey
    main_id: str
    workshop_code: str
    ordered_service_process_codes: tuple[str, ...]
    physical_buffer_key: PhysicalBufferKey
    order_code: str
    product_code: str
    buffer_codes: tuple[str, ...]
    total_inventory: float
    total_capacity: float | None
    remaining_capacity: float | None
    representative_buffer_code: str | None
    stockout_eligible: bool
    overflow_eligible: bool
    stockout_warning_eligible: bool
    overflow_warning_eligible: bool
    auto_receive_eligible: bool
    auto_donate_eligible: bool

    @property
    def all_capabilities_enabled(self) -> bool:
        return all(getattr(self, name) for name in CAPABILITY_NAMES)

    @property
    def no_capabilities_enabled(self) -> bool:
        return not any(getattr(self, name) for name in CAPABILITY_NAMES)


@dataclass(frozen=True)
class MainBufferAggregationBatch:
    groups: tuple[MainBufferGroup, ...] = ()
    issues: tuple[MainBufferAggregationIssue, ...] = ()
    groups_by_group_key: dict[GroupKey, MainBufferGroup] = field(
        default_factory=dict
    )
    group_keys_by_main_id: dict[str, tuple[GroupKey, ...]] = field(
        default_factory=dict
    )
    group_key_by_buffer_code: dict[str, GroupKey] = field(default_factory=dict)
    group_key_by_representative_buffer_code: dict[str, GroupKey] = field(
        default_factory=dict
    )
    group_keys_by_physical_buffer_key: dict[
        PhysicalBufferKey, tuple[GroupKey, ...]
    ] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> MainBufferAggregationBatch:
        return cls()

    @property
    def groups_by_main_id(self) -> dict[str, tuple[MainBufferGroup, ...]]:
        return {
            main_id: tuple(
                self.groups_by_group_key[key]
                for key in keys
                if key in self.groups_by_group_key
            )
            for main_id, keys in self.group_keys_by_main_id.items()
        }

    @property
    def main_id_by_buffer_code(self) -> dict[str, str]:
        return {
            code: key.main_id
            for code, key in self.group_key_by_buffer_code.items()
        }

    @property
    def main_id_by_representative_buffer_code(self) -> dict[str, str]:
        return {
            code: key.main_id
            for code, key in self.group_key_by_representative_buffer_code.items()
        }

    @property
    def main_ids_by_physical_buffer_key(
        self,
    ) -> dict[PhysicalBufferKey, tuple[str, ...]]:
        return {
            physical_key: tuple(key.main_id for key in keys)
            for physical_key, keys in self.group_keys_by_physical_buffer_key.items()
        }
