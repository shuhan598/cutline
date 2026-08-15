"""构建权威的 main 物理 Buffer 状态及其订单子状态。"""

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
    OrderBufferState,
    PhysicalBufferKey,
    PhysicalMainBufferState,
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


def _is_current_order(order: OrderView) -> bool:
    status = getattr(order, "order_status", None)
    if status is None or not str(status).strip():
        return True
    normalized = str(status).strip()
    return normalized.casefold() in {"running", "open"} or normalized in {
        "生产中",
        "正在生产",
        "鐢熶骇涓?",
    }


class MainBufferAggregator:
    """按物理 ``main_id`` 聚合实时 Buffer 层。

    ``MainBufferGroup`` 保留为订单粒度兼容视图；权威物理汇总值只在
    ``PhysicalMainBufferState`` 中生成一次。
    """

    def aggregate(
        self,
        *,
        realtime_buffers: Iterable[BufferRealtimeView],
        buffer_masters: Iterable[BufferMasterView],
        buffer_relations: Iterable[BufferRelationView],
        orders: Iterable[OrderView],
    ) -> MainBufferAggregationBatch:
        # main_id 是物理 Buffer 的唯一身份，所有实时层先按 main 聚合。
        realtime_by_main: dict[str, list[BufferRealtimeView]] = defaultdict(list)
        for realtime in realtime_buffers:
            realtime_by_main[self._normalize(getattr(realtime, "main_id", None))].append(
                realtime
            )
        masters_by_code = self._multi_index(buffer_masters, "buffer_code")
        relations_by_code = self._multi_index(buffer_relations, "buffer_code")
        orders_by_name = self._multi_index(orders, "product_name")

        groups: list[MainBufferGroup] = []
        physical_states: dict[str, PhysicalMainBufferState] = {}
        issues: list[MainBufferAggregationIssue] = []
        for main_id in sorted(realtime_by_main):
            main_groups, physical, main_issues = self._aggregate_main(
                main_id=main_id,
                realtime_rows=realtime_by_main[main_id],
                masters_by_code=masters_by_code,
                relations_by_code=relations_by_code,
                orders_by_name=orders_by_name,
            )
            groups.extend(main_groups)
            physical_states[main_id] = physical
            issues.extend(main_issues)

        groups, index_issues = self._validate_index_conflicts(groups)
        issues.extend(index_issues)
        return self._build_batch(
            groups,
            physical_states,
            self._deduplicate_issues(issues),
        )

    def _aggregate_main(
        self,
        *,
        main_id: str,
        realtime_rows: list[BufferRealtimeView],
        masters_by_code: dict[str, list[BufferMasterView]],
        relations_by_code: dict[str, list[BufferRelationView]],
        orders_by_name: dict[str, list[OrderView]],
    ) -> tuple[list[MainBufferGroup], PhysicalMainBufferState, list[MainBufferAggregationIssue]]:
        issues: list[MainBufferAggregationIssue] = []
        fatal = not main_id
        if not main_id:
            issues.append(self._issue("main_id_unavailable", main_id, None, "Realtime Buffer main_id is blank", _ALL_CAPABILITIES))

        seen_codes: set[str] = set()
        duplicate_codes: set[str] = set()
        mapped_codes: set[str] = set()
        unresolved_codes: set[str] = set()
        capacities: dict[str, float] = {}
        workshops: set[str] = set()
        process_lists: set[tuple[str, ...]] = set()
        resolved_orders: dict[str, OrderView] = {}
        buffer_codes_by_order: dict[str, set[str]] = defaultdict(set)
        inventories_by_order: dict[str, float] = defaultdict(float)
        unresolved_sources: dict[tuple[str, str], str] = {}

        # 同一 buffer_code 只计一次物理容量；库存则归入其当前绑定订单。
        for realtime in realtime_rows:
            buffer_code = self._normalize(realtime.buffer_code)
            duplicate = buffer_code in seen_codes
            if duplicate:
                duplicate_codes.add(buffer_code)
            else:
                seen_codes.add(buffer_code)
                quantity = self._number_or_none(realtime.current_quantity)
                if quantity is None or quantity < 0:
                    fatal = True
                    issues.append(self._issue("inventory_unavailable", main_id, None, f"Inventory is invalid for buffer_code {buffer_code!r}", _ALL_CAPABILITIES))
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
                    process_lists.add((self._normalize(relation.upstream_process_code), self._normalize(relation.downstream_process_code)))
                    capacity = self._number_or_none(master.max_capacity)
                    if capacity is not None and capacity > 0:
                        capacities[buffer_code] = capacity

            source_name = self._normalize(realtime.bound_source_name)
            order_matches = [order for order in orders_by_name.get(source_name, []) if _is_current_order(order)]
            if len(order_matches) != 1:
                fatal = True
                unresolved_sources[(source_name, buffer_code)] = "order_mapping_not_found" if not order_matches else "order_mapping_ambiguous"
                continue
            order = order_matches[0]
            order_code = self._normalize(order.order_code)
            resolved_orders[order_code] = order
            if not duplicate and buffer_code in mapped_codes:
                buffer_codes_by_order[order_code].add(buffer_code)
                quantity = self._number_or_none(realtime.current_quantity)
                if quantity is not None and quantity >= 0:
                    inventories_by_order[order_code] += quantity

        representative = min(mapped_codes) if mapped_codes else None
        if duplicate_codes:
            fatal = True
            issues.append(self._issue("duplicate_buffer_id", main_id, representative, "Duplicate realtime buffer_code values: " + ", ".join(sorted(duplicate_codes)), _ALL_CAPABILITIES))
        if unresolved_codes:
            issues.append(self._issue("static_buffer_mapping_unresolved", main_id, representative, "Static Buffer mapping unresolved for: " + ", ".join(sorted(unresolved_codes)), _ALL_CAPABILITIES))
        for (source_name, buffer_code), code in sorted(unresolved_sources.items()):
            issues.append(self._issue(code, main_id, representative, f"buffer_code {buffer_code!r} bound_source_name {source_name!r} does not map to exactly one current order", _ALL_CAPABILITIES))
        if len(workshops) > 1:
            fatal = True
            issues.append(self._issue("workshop_conflict", main_id, representative, "Conflicting workshops: " + ", ".join(sorted(workshops)), _ALL_CAPABILITIES))
        if len(process_lists) > 1:
            fatal = True
            issues.append(self._issue("service_process_conflict", main_id, representative, "Conflicting ordered service processes: " + "; ".join(" -> ".join(item) for item in sorted(process_lists)), _ALL_CAPABILITIES))

        workshop = sorted(workshops)[0] if workshops else ""
        processes = sorted(process_lists)[0] if process_lists else ()
        for order in resolved_orders.values():
            if workshop and self._normalize(order.workshop_code) != workshop:
                fatal = True
                issues.append(self._issue("workshop_conflict", main_id, representative, f"Order workshop {order.workshop_code!r} conflicts with Buffer workshop {workshop!r}", _ALL_CAPABILITIES))

        # 物理总库存汇总所有订单，物理总容量按唯一 buffer_code 求和。
        total_inventory = sum(inventories_by_order.values())
        capacity_available = bool(mapped_codes) and mapped_codes == set(capacities)
        total_capacity = sum(capacities.values()) if capacity_available else None
        remaining_capacity = total_capacity - total_inventory if total_capacity is not None else None
        if not fatal and total_capacity is None:
            capabilities = {name: name not in _CAPACITY_CAPABILITIES for name in CAPABILITY_NAMES}
            issues.append(self._issue("capacity_unavailable", main_id, representative, "Capacity unavailable for one or more buffer_code values", _CAPACITY_CAPABILITIES))
        else:
            capabilities = {name: not fatal for name in CAPABILITY_NAMES}
        if not fatal and total_capacity is not None and total_inventory >= total_capacity:
            capabilities["auto_receive_eligible"] = False
            issues.append(self._issue("inventory_at_or_above_capacity", main_id, representative, f"Inventory {total_inventory:g} is at or above capacity {total_capacity:g}", ("auto_receive_eligible",)))

        physical_key = PhysicalBufferKey(workshop, processes)
        physical = PhysicalMainBufferState(
            main_id=main_id,
            workshop_code=workshop,
            ordered_service_process_codes=processes,
            physical_buffer_key=physical_key,
            buffer_codes=tuple(sorted(mapped_codes)),
            total_inventory=total_inventory,
            total_capacity=total_capacity,
            remaining_capacity=remaining_capacity,
            representative_buffer_code=representative,
            order_codes=tuple(sorted(resolved_orders)),
            **capabilities,
        )

        # 每个订单生成一个子状态，但共享同一份物理容量和 capability 结论。
        groups: list[MainBufferGroup] = []
        order_items = sorted(resolved_orders.items()) or [("", None)]
        for order_code, order in order_items:
            order_inventory = inventories_by_order.get(order_code, 0.0)
            order_buffer_codes = tuple(sorted(buffer_codes_by_order.get(order_code, set())))
            groups.append(MainBufferGroup(
                group_key=GroupKey(physical_key, main_id, order_code),
                main_id=main_id,
                workshop_code=workshop,
                ordered_service_process_codes=processes,
                physical_buffer_key=physical_key,
                order_code=order_code,
                product_code=self._normalize(order.product_code) if order is not None else "",
                product_name=self._normalize(order.product_name) if order is not None else "",
                buffer_codes=order_buffer_codes,
                total_inventory=order_inventory,
                total_capacity=total_capacity,
                remaining_capacity=total_capacity - order_inventory if total_capacity is not None else None,
                representative_buffer_code=(order_buffer_codes[0] if order_buffer_codes else representative),
                **capabilities,
            ))
        return groups, physical, issues

    def _build_batch(self, groups, physical_states, issues):
        # 同时建立物理 main、订单子状态和兼容查询所需的只读索引。
        groups_by_key: dict[GroupKey, MainBufferGroup] = {}
        keys_by_main: dict[str, list[GroupKey]] = defaultdict(list)
        keys_by_physical: dict[PhysicalBufferKey, list[GroupKey]] = defaultdict(list)
        owners_by_buffer: dict[str, set[GroupKey]] = defaultdict(set)
        owners_by_representative: dict[str, set[GroupKey]] = defaultdict(set)
        for group in groups:
            for code in group.buffer_codes:
                owners_by_buffer[code].add(group.group_key)
            if group.representative_buffer_code is not None:
                owners_by_representative[group.representative_buffer_code].add(group.group_key)
        key_by_buffer: dict[str, GroupKey] = {}
        key_by_representative: dict[str, GroupKey] = {}
        order_states: dict[tuple[str, str], OrderBufferState] = {}
        for group in sorted(groups, key=lambda item: item.group_key):
            groups_by_key[group.group_key] = group
            keys_by_main[group.main_id].append(group.group_key)
            keys_by_physical[group.physical_buffer_key].append(group.group_key)
            for code in group.buffer_codes:
                if len(owners_by_buffer[code]) == 1:
                    key_by_buffer[code] = group.group_key
            representative = group.representative_buffer_code
            if representative is not None and len(owners_by_representative[representative]) == 1:
                key_by_representative[representative] = group.group_key
            if group.order_code:
                order_states[(group.main_id, group.order_code)] = OrderBufferState(
                    main_id=group.main_id,
                    order_code=group.order_code,
                    product_code=group.product_code,
                    product_name=group.product_name,
                    buffer_codes=group.buffer_codes,
                    total_inventory=group.total_inventory,
                )
        return MainBufferAggregationBatch(
            groups=tuple(groups_by_key[key] for key in sorted(groups_by_key)),
            issues=issues,
            groups_by_group_key=groups_by_key,
            group_keys_by_main_id={key: tuple(sorted(value)) for key, value in keys_by_main.items()},
            group_key_by_buffer_code=key_by_buffer,
            group_key_by_representative_buffer_code=key_by_representative,
            group_keys_by_physical_buffer_key={key: tuple(sorted(value)) for key, value in keys_by_physical.items()},
            physical_main_buffers_by_main_id=physical_states,
            order_states_by_main_and_order=order_states,
        )

    def _validate_index_conflicts(self, groups):
        owners_by_code: dict[str, list[MainBufferGroup]] = defaultdict(list)
        for group in groups:
            for code in group.buffer_codes:
                owners_by_code[code].append(group)
        conflicts: dict[GroupKey, set[str]] = defaultdict(set)
        for code, owners in owners_by_code.items():
            if len({owner.group_key for owner in owners}) > 1:
                for owner in owners:
                    conflicts[owner.group_key].add(code)
        if not conflicts:
            return groups, []
        disabled = {name: False for name in CAPABILITY_NAMES}
        updated = []
        issues = []
        for group in groups:
            codes = conflicts.get(group.group_key)
            if not codes:
                updated.append(group)
                continue
            updated.append(replace(group, **disabled))
            owner_ids = sorted({owner.main_id for code in codes for owner in owners_by_code[code]})
            issues.append(self._issue("buffer_code_index_conflict", group.main_id, group.representative_buffer_code, f"buffer_code values {', '.join(sorted(codes))} map to multiple main_ids: {', '.join(owner_ids)}", _ALL_CAPABILITIES))
        return updated, issues

    @staticmethod
    def _deduplicate_issues(issues):
        by_key = {}
        for issue in issues:
            key = (issue.code, issue.main_id)
            if key not in by_key:
                by_key[key] = issue
            else:
                previous = by_key[key]
                by_key[key] = replace(previous, message="; ".join(sorted({previous.message, issue.message})))
        return tuple(by_key[key] for key in sorted(by_key))

    @staticmethod
    def _multi_index(records: Iterable[Any], field_name: str):
        result = defaultdict(list)
        for record in records:
            result[MainBufferAggregator._normalize(getattr(record, field_name))].append(record)
        return result

    @staticmethod
    def _number_or_none(value: Any):
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if isfinite(number) else None

    @staticmethod
    def _normalize(value: Any):
        return "" if value is None else str(value).strip()

    @staticmethod
    def _issue(code, main_id, representative_buffer_code, message, affected_capabilities):
        return MainBufferAggregationIssue(
            code=code,
            main_id=main_id,
            representative_buffer_code=representative_buffer_code,
            message=message,
            affected_capabilities=affected_capabilities,
        )
