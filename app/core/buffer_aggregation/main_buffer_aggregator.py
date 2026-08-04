"""Build the one authoritative main Buffer aggregation batch."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import replace
from math import isfinite
from typing import Any, Protocol

from app.core.buffer_aggregation.models import (
    CAPABILITY_NAMES,
    GroupKey,
    MainBufferAggregationBatch,
    MainBufferAggregationIssue,
    MainBufferGroup,
    PhysicalBufferKey,
)


class BufferRealtimeView(Protocol):
    main_id: str | None
    buffer_code: str
    bound_source_name: str
    current_quantity: float


class BufferMasterView(Protocol):
    buffer_code: str
    max_capacity: float | None
    served_process_codes: list[str]


class BufferRelationView(Protocol):
    buffer_code: str
    workshop_code: str
    upstream_process_code: str
    downstream_process_code: str


class OrderView(Protocol):
    order_code: str
    product_code: str
    product_name: str
    workshop_code: str


_ALL_CAPABILITIES = CAPABILITY_NAMES
_CAPACITY_CAPABILITIES = (
    "overflow_eligible",
    "overflow_warning_eligible",
    "auto_receive_eligible",
)


class MainBufferAggregator:
    """Aggregate realtime Buffer layers by main ID and isolate local issues."""

    def aggregate(
        self,
        *,
        realtime_buffers: Iterable[BufferRealtimeView],
        buffer_masters: Iterable[BufferMasterView],
        buffer_relations: Iterable[BufferRelationView],
        orders: Iterable[OrderView],
    ) -> MainBufferAggregationBatch:
        realtime_by_main: dict[str, list[BufferRealtimeView]] = defaultdict(list)
        for realtime in realtime_buffers:
            main_id = self._normalize(getattr(realtime, "main_id", None))
            realtime_by_main[main_id].append(realtime)

        masters_by_code = self._multi_index(buffer_masters, "buffer_code")
        relations_by_code = self._multi_index(buffer_relations, "buffer_code")
        orders_by_name = self._multi_index(orders, "product_name")

        groups: list[MainBufferGroup] = []
        issues: list[MainBufferAggregationIssue] = []
        for main_id in sorted(realtime_by_main):
            group, group_issues = self._aggregate_main(
                main_id=main_id,
                realtime_rows=realtime_by_main[main_id],
                masters_by_code=masters_by_code,
                relations_by_code=relations_by_code,
                orders_by_name=orders_by_name,
            )
            groups.append(group)
            issues.extend(group_issues)

        groups, cross_main_issues = self._validate_cross_main(groups)
        issues.extend(cross_main_issues)
        groups, index_issues = self._validate_index_conflicts(groups)
        issues.extend(index_issues)
        return self._build_batch(groups, self._deduplicate_issues(issues))

    def _aggregate_main(
        self,
        *,
        main_id: str,
        realtime_rows: list[BufferRealtimeView],
        masters_by_code: dict[str, list[BufferMasterView]],
        relations_by_code: dict[str, list[BufferRelationView]],
        orders_by_name: dict[str, list[OrderView]],
    ) -> tuple[MainBufferGroup, list[MainBufferAggregationIssue]]:
        issues: list[MainBufferAggregationIssue] = []
        fatal = not main_id
        if not main_id:
            issues.append(
                self._issue(
                    "main_id_unavailable",
                    main_id,
                    None,
                    "Realtime Buffer main_id is blank",
                    _ALL_CAPABILITIES,
                )
            )

        seen_codes: set[str] = set()
        duplicate_codes: set[str] = set()
        mapped_codes: set[str] = set()
        unresolved_codes: set[str] = set()
        inventories: list[float] = []
        capacities: dict[str, float] = {}
        workshops: set[str] = set()
        process_lists: set[tuple[str, ...]] = set()
        resolved_orders: dict[str, OrderView] = {}
        unresolved_order_sources: set[str] = set()

        for realtime in realtime_rows:
            buffer_code = self._normalize(realtime.buffer_code)
            is_duplicate = buffer_code in seen_codes
            if is_duplicate:
                duplicate_codes.add(buffer_code)
            else:
                seen_codes.add(buffer_code)

                quantity = self._number_or_none(realtime.current_quantity)
                if quantity is None or quantity < 0:
                    fatal = True
                    issues.append(
                        self._issue(
                            "inventory_unavailable",
                            main_id,
                            None,
                            f"Inventory is invalid for buffer_code {buffer_code!r}",
                            _ALL_CAPABILITIES,
                        )
                    )
                else:
                    inventories.append(quantity)

                master_matches = masters_by_code.get(buffer_code, [])
                relation_matches = relations_by_code.get(buffer_code, [])
                if len(master_matches) != 1 or len(relation_matches) != 1:
                    fatal = True
                    unresolved_codes.add(buffer_code)
                else:
                    master = master_matches[0]
                    relation = relation_matches[0]
                    mapped_codes.add(buffer_code)
                    workshops.add(self._normalize(relation.workshop_code))
                    process_lists.add(
                        tuple(
                            self._normalize(code)
                            for code in master.served_process_codes
                        )
                    )
                    capacity = self._number_or_none(master.max_capacity)
                    if capacity is not None and capacity > 0:
                        capacities[buffer_code] = capacity

            source_name = self._normalize(realtime.bound_source_name)
            order_matches = orders_by_name.get(source_name, [])
            if len(order_matches) != 1:
                fatal = True
                unresolved_order_sources.add(source_name)
            else:
                order = order_matches[0]
                resolved_orders[self._normalize(order.order_code)] = order

        representative = min(mapped_codes) if mapped_codes else None
        if duplicate_codes:
            fatal = True
            rendered = ", ".join(sorted(duplicate_codes))
            issues.append(
                self._issue(
                    "duplicate_buffer_id",
                    main_id,
                    representative,
                    f"Duplicate realtime buffer_code values: {rendered}",
                    _ALL_CAPABILITIES,
                )
            )
        if unresolved_codes:
            rendered = ", ".join(sorted(unresolved_codes))
            issues.append(
                self._issue(
                    "static_buffer_mapping_unresolved",
                    main_id,
                    representative,
                    f"Static Buffer mapping unresolved for: {rendered}",
                    _ALL_CAPABILITIES,
                )
            )
        if unresolved_order_sources:
            rendered = ", ".join(
                repr(value) for value in sorted(unresolved_order_sources)
            )
            issues.append(
                self._issue(
                    "order_mapping_unresolved",
                    main_id,
                    representative,
                    f"Order mapping unresolved for bound source names: {rendered}",
                    _ALL_CAPABILITIES,
                )
            )
        if len(resolved_orders) > 1:
            fatal = True
            rendered = ", ".join(sorted(resolved_orders))
            issues.append(
                self._issue(
                    "multiple_orders_in_main",
                    main_id,
                    representative,
                    f"main_id {main_id!r} resolves to multiple orders: {rendered}",
                    _ALL_CAPABILITIES,
                )
            )
        if len(workshops) > 1:
            fatal = True
            issues.append(
                self._issue(
                    "workshop_conflict",
                    main_id,
                    representative,
                    f"Conflicting workshops: {', '.join(sorted(workshops))}",
                    _ALL_CAPABILITIES,
                )
            )
        if len(process_lists) > 1:
            fatal = True
            rendered = ", ".join(
                " -> ".join(processes)
                for processes in sorted(process_lists)
            )
            issues.append(
                self._issue(
                    "service_process_conflict",
                    main_id,
                    representative,
                    f"Conflicting ordered service processes: {rendered}",
                    _ALL_CAPABILITIES,
                )
            )

        order = resolved_orders[sorted(resolved_orders)[0]] if resolved_orders else None
        workshop = sorted(workshops)[0] if workshops else ""
        processes = sorted(process_lists)[0] if process_lists else ()
        if order is not None and workshop and self._normalize(order.workshop_code) != workshop:
            fatal = True
            issues.append(
                self._issue(
                    "workshop_conflict",
                    main_id,
                    representative,
                    f"Order workshop {order.workshop_code!r} conflicts with Buffer workshop {workshop!r}",
                    _ALL_CAPABILITIES,
                )
            )

        total_inventory = sum(inventories)
        capacity_available = (
            bool(mapped_codes)
            and mapped_codes == set(capacities)
            and not unresolved_codes
        )
        total_capacity = sum(capacities.values()) if capacity_available else None
        remaining_capacity = (
            total_capacity - total_inventory
            if total_capacity is not None
            else None
        )
        physical_key = PhysicalBufferKey(workshop, processes)
        order_code = self._normalize(order.order_code) if order is not None else ""
        product_code = self._normalize(order.product_code) if order is not None else ""
        group_key = GroupKey(physical_key, main_id, order_code)

        capabilities = {name: not fatal for name in CAPABILITY_NAMES}
        if not fatal and total_capacity is None:
            capabilities.update(
                overflow_eligible=False,
                overflow_warning_eligible=False,
                auto_receive_eligible=False,
            )
            missing_capacity_codes = sorted(mapped_codes - set(capacities))
            issues.append(
                self._issue(
                    "capacity_unavailable",
                    main_id,
                    representative,
                    "Capacity unavailable for buffer_code values: "
                    + ", ".join(missing_capacity_codes),
                    _CAPACITY_CAPABILITIES,
                )
            )
        if not fatal and total_capacity is not None and total_inventory >= total_capacity:
            capabilities["auto_receive_eligible"] = False
            issues.append(
                self._issue(
                    "inventory_at_or_above_capacity",
                    main_id,
                    representative,
                    f"Inventory {total_inventory:g} is at or above capacity {total_capacity:g}",
                    ("auto_receive_eligible",),
                )
            )

        group = MainBufferGroup(
            group_key=group_key,
            main_id=main_id,
            workshop_code=workshop,
            ordered_service_process_codes=processes,
            physical_buffer_key=physical_key,
            order_code=order_code,
            product_code=product_code,
            buffer_codes=tuple(sorted(mapped_codes)),
            total_inventory=total_inventory,
            total_capacity=total_capacity,
            remaining_capacity=remaining_capacity,
            representative_buffer_code=representative,
            **capabilities,
        )
        return group, issues

    def _validate_cross_main(
        self, groups: list[MainBufferGroup]
    ) -> tuple[list[MainBufferGroup], list[MainBufferAggregationIssue]]:
        collision_index: dict[
            tuple[PhysicalBufferKey, str], list[MainBufferGroup]
        ] = defaultdict(list)
        for group in groups:
            if not group.no_capabilities_enabled and group.order_code:
                collision_index[(group.physical_buffer_key, group.order_code)].append(
                    group
                )

        conflicts: dict[GroupKey, tuple[str, ...]] = {}
        for matching_groups in collision_index.values():
            main_ids = tuple(sorted({group.main_id for group in matching_groups}))
            if len(main_ids) > 1:
                for group in matching_groups:
                    conflicts[group.group_key] = main_ids

        if not conflicts:
            return groups, []

        updated_groups: list[MainBufferGroup] = []
        issues: list[MainBufferAggregationIssue] = []
        disabled = {name: False for name in CAPABILITY_NAMES}
        for group in groups:
            main_ids = conflicts.get(group.group_key)
            if main_ids is None:
                updated_groups.append(group)
                continue
            updated_groups.append(replace(group, **disabled))
            issues.append(
                self._issue(
                    "duplicate_order_across_main_ids",
                    group.main_id,
                    group.representative_buffer_code,
                    f"Order {group.order_code!r} shares one physical Buffer across main_ids: {', '.join(main_ids)}",
                    _ALL_CAPABILITIES,
                )
            )
        return updated_groups, issues

    def _build_batch(
        self,
        groups: list[MainBufferGroup],
        issues: tuple[MainBufferAggregationIssue, ...],
    ) -> MainBufferAggregationBatch:
        groups_by_key: dict[GroupKey, MainBufferGroup] = {}
        keys_by_main: dict[str, list[GroupKey]] = defaultdict(list)
        key_by_buffer: dict[str, GroupKey] = {}
        key_by_representative: dict[str, GroupKey] = {}
        keys_by_physical: dict[PhysicalBufferKey, list[GroupKey]] = defaultdict(list)

        owners_by_buffer: dict[str, set[GroupKey]] = defaultdict(set)
        owners_by_representative: dict[str, set[GroupKey]] = defaultdict(set)
        for group in groups:
            for buffer_code in group.buffer_codes:
                owners_by_buffer[buffer_code].add(group.group_key)
            if group.representative_buffer_code is not None:
                owners_by_representative[group.representative_buffer_code].add(
                    group.group_key
                )

        for group in sorted(groups, key=lambda item: item.group_key):
            groups_by_key[group.group_key] = group
            keys_by_main[group.main_id].append(group.group_key)
            keys_by_physical[group.physical_buffer_key].append(group.group_key)
            for buffer_code in group.buffer_codes:
                if len(owners_by_buffer[buffer_code]) == 1:
                    key_by_buffer[buffer_code] = group.group_key
            representative = group.representative_buffer_code
            if (
                representative is not None
                and len(owners_by_representative[representative]) == 1
            ):
                key_by_representative[representative] = group.group_key

        ordered_groups = tuple(groups_by_key[key] for key in sorted(groups_by_key))
        return MainBufferAggregationBatch(
            groups=ordered_groups,
            issues=issues,
            groups_by_group_key=groups_by_key,
            group_keys_by_main_id={
                key: tuple(sorted(values)) for key, values in keys_by_main.items()
            },
            group_key_by_buffer_code=key_by_buffer,
            group_key_by_representative_buffer_code=key_by_representative,
            group_keys_by_physical_buffer_key={
                key: tuple(sorted(values))
                for key, values in keys_by_physical.items()
            },
        )

    def _validate_index_conflicts(
        self, groups: list[MainBufferGroup]
    ) -> tuple[list[MainBufferGroup], list[MainBufferAggregationIssue]]:
        owners_by_code: dict[str, list[MainBufferGroup]] = defaultdict(list)
        for group in groups:
            for buffer_code in group.buffer_codes:
                owners_by_code[buffer_code].append(group)

        conflicts_by_key: dict[GroupKey, set[str]] = defaultdict(set)
        for buffer_code, owners in owners_by_code.items():
            if len({owner.group_key for owner in owners}) <= 1:
                continue
            for owner in owners:
                conflicts_by_key[owner.group_key].add(buffer_code)

        if not conflicts_by_key:
            return groups, []

        disabled = {name: False for name in CAPABILITY_NAMES}
        updated_groups: list[MainBufferGroup] = []
        issues: list[MainBufferAggregationIssue] = []
        for group in groups:
            conflict_codes = conflicts_by_key.get(group.group_key)
            if not conflict_codes:
                updated_groups.append(group)
                continue
            updated_groups.append(replace(group, **disabled))
            rendered_codes = ", ".join(sorted(conflict_codes))
            owner_ids = sorted(
                {
                    owner.main_id
                    for code in conflict_codes
                    for owner in owners_by_code[code]
                }
            )
            issues.append(
                self._issue(
                    "buffer_code_index_conflict",
                    group.main_id,
                    group.representative_buffer_code,
                    f"buffer_code values {rendered_codes} map to multiple main_ids: {', '.join(owner_ids)}",
                    _ALL_CAPABILITIES,
                )
            )
        return updated_groups, issues

    @staticmethod
    def _deduplicate_issues(
        issues: list[MainBufferAggregationIssue],
    ) -> tuple[MainBufferAggregationIssue, ...]:
        by_key: dict[tuple[str, str], MainBufferAggregationIssue] = {}
        for issue in issues:
            key = (issue.code, issue.main_id)
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = issue
                continue
            messages = sorted({existing.message, issue.message})
            by_key[key] = replace(existing, message="; ".join(messages))
        return tuple(by_key[key] for key in sorted(by_key))

    @staticmethod
    def _multi_index(records: Iterable[Any], field_name: str) -> dict[str, list[Any]]:
        result: dict[str, list[Any]] = defaultdict(list)
        for record in records:
            key = MainBufferAggregator._normalize(getattr(record, field_name))
            result[key].append(record)
        return result

    @staticmethod
    def _number_or_none(value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if isfinite(number) else None

    @staticmethod
    def _normalize(value: Any) -> str:
        return "" if value is None else str(value).strip()

    @staticmethod
    def _issue(
        code: str,
        main_id: str,
        representative_buffer_code: str | None,
        message: str,
        affected_capabilities: tuple[str, ...],
    ) -> MainBufferAggregationIssue:
        return MainBufferAggregationIssue(
            code=code,
            main_id=main_id,
            representative_buffer_code=representative_buffer_code,
            message=message,
            affected_capabilities=affected_capabilities,
        )
