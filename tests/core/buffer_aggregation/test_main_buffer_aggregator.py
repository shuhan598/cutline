from dataclasses import dataclass

import pytest

from app.core.buffer_aggregation.main_buffer_aggregator import (
    MainBufferAggregator,
)


@dataclass(frozen=True)
class RealtimeBuffer:
    main_id: str | None
    buffer_code: str
    bound_source_name: str
    current_quantity: float


@dataclass(frozen=True)
class BufferMaster:
    buffer_code: str
    max_capacity: float | None
    served_process_codes: list[str]


@dataclass(frozen=True)
class BufferRelation:
    buffer_code: str
    workshop_code: str
    upstream_process_code: str
    downstream_process_code: str


@dataclass(frozen=True)
class Order:
    order_code: str
    product_code: str
    product_name: str
    workshop_code: str


def realtime(
    buffer_code: str,
    quantity: float,
    *,
    main_id: str = "MAIN-1",
    product_name: str = "Product A",
) -> RealtimeBuffer:
    return RealtimeBuffer(
        main_id=main_id,
        buffer_code=buffer_code,
        bound_source_name=product_name,
        current_quantity=quantity,
    )


def master(
    buffer_code: str,
    capacity: float | None,
    *,
    processes: list[str] | None = None,
) -> BufferMaster:
    return BufferMaster(
        buffer_code=buffer_code,
        max_capacity=capacity,
        served_process_codes=processes or ["P1", "P2"],
    )


def relation(
    buffer_code: str,
    *,
    workshop: str = "S1",
    upstream: str = "P1",
    downstream: str = "P2",
) -> BufferRelation:
    return BufferRelation(
        buffer_code=buffer_code,
        workshop_code=workshop,
        upstream_process_code=upstream,
        downstream_process_code=downstream,
    )


ORDERS = [
    Order(
        order_code="ORDER-A",
        product_code="PRODUCT-A",
        product_name="Product A",
        workshop_code="S1",
    ),
    Order(
        order_code="ORDER-B",
        product_code="PRODUCT-B",
        product_name="Product B",
        workshop_code="S1",
    ),
]


def aggregate(
    realtime_buffers: list[RealtimeBuffer],
    buffer_masters: list[BufferMaster],
    buffer_relations: list[BufferRelation],
):
    return MainBufferAggregator().aggregate(
        realtime_buffers=realtime_buffers,
        buffer_masters=buffer_masters,
        buffer_relations=buffer_relations,
        orders=ORDERS,
    )


def only_group(batch):
    assert len(batch.groups_by_group_key) == 1
    return next(iter(batch.groups_by_group_key.values()))


def test_one_main_sums_unique_layer_inventory_and_capacity():
    batch = aggregate(
        [realtime("BUF-2", 7200), realtime("BUF-1", 3600)],
        [master("BUF-1", 10000), master("BUF-2", 20000)],
        [relation("BUF-1"), relation("BUF-2")],
    )

    group = only_group(batch)
    assert group.total_inventory == 10800
    assert group.total_capacity == 30000
    assert group.remaining_capacity == 19200
    assert group.buffer_codes == ("BUF-1", "BUF-2")
    assert group.representative_buffer_code == "BUF-1"
    assert group.group_key.main_id == "MAIN-1"
    assert group.group_key.order_code == "ORDER-A"
    assert group.physical_buffer_key.workshop_code == "S1"
    assert group.physical_buffer_key.ordered_service_process_codes == (
        "P1",
        "P2",
    )
    assert group.all_capabilities_enabled
    assert batch.group_key_by_buffer_code == {
        "BUF-1": group.group_key,
        "BUF-2": group.group_key,
    }


def test_same_main_uses_relation_direction_when_master_order_is_reversed():
    batch = aggregate(
        [realtime("BUF-1", 10), realtime("BUF-2", 20)],
        [
            master("BUF-1", 100, processes=["P1", "P2"]),
            master("BUF-2", 200, processes=["P2", "P1"]),
        ],
        [relation("BUF-1"), relation("BUF-2")],
    )

    group = only_group(batch)
    assert len(batch.groups) == 1
    assert group.physical_buffer_key.ordered_service_process_codes == (
        "P1",
        "P2",
    )
    assert group.buffer_codes == ("BUF-1", "BUF-2")
    assert group.total_inventory == 30
    assert group.total_capacity == 300
    assert group.remaining_capacity == 270
    assert not any(
        issue.code == "service_process_conflict" for issue in batch.issues
    )


def test_representative_code_is_stable_sorted_real_layer():
    first = aggregate(
        [realtime("BUF-2", 20), realtime("BUF-1", 10)],
        [master("BUF-2", 200), master("BUF-1", 100)],
        [relation("BUF-2"), relation("BUF-1")],
    )
    second = aggregate(
        [realtime("BUF-1", 10), realtime("BUF-2", 20)],
        [master("BUF-1", 100), master("BUF-2", 200)],
        [relation("BUF-1"), relation("BUF-2")],
    )

    assert only_group(first).representative_buffer_code == "BUF-1"
    assert only_group(second).representative_buffer_code == "BUF-1"


def test_zero_inventory_is_valid():
    batch = aggregate(
        [realtime("BUF-1", 0)],
        [master("BUF-1", 100)],
        [relation("BUF-1")],
    )

    group = only_group(batch)
    assert group.total_inventory == 0
    assert group.stockout_eligible is True
    assert batch.issues == ()


def test_duplicate_realtime_buffer_invalidates_group_without_double_counting():
    batch = aggregate(
        [realtime("BUF-1", 10), realtime("BUF-1", 10)],
        [master("BUF-1", 100)],
        [relation("BUF-1")],
    )

    group = only_group(batch)
    assert group.total_inventory == 10
    assert group.no_capabilities_enabled
    issue = next(issue for issue in batch.issues if issue.code == "duplicate_buffer_id")
    assert issue.main_id == "MAIN-1"
    assert "BUF-1" in issue.message


def test_static_mapping_unresolved_disables_all_six_capabilities():
    batch = aggregate(
        [realtime("UNKNOWN", 10)],
        [],
        [],
    )

    group = only_group(batch)
    assert group.representative_buffer_code is None
    assert group.no_capabilities_enabled
    issue = batch.issues[0]
    assert issue.code == "static_buffer_mapping_unresolved"
    assert issue.main_id == "MAIN-1"
    assert "UNKNOWN" in issue.message
    assert set(issue.affected_capabilities) == {
        "stockout_eligible",
        "overflow_eligible",
        "stockout_warning_eligible",
        "overflow_warning_eligible",
        "auto_receive_eligible",
        "auto_donate_eligible",
    }


def test_capacity_unavailable_keeps_stockout_and_donor_capabilities_only():
    batch = aggregate(
        [realtime("BUF-1", 10)],
        [master("BUF-1", None)],
        [relation("BUF-1")],
    )

    group = only_group(batch)
    assert group.total_capacity is None
    assert group.remaining_capacity is None
    assert group.stockout_eligible is True
    assert group.overflow_eligible is False
    assert group.stockout_warning_eligible is True
    assert group.overflow_warning_eligible is False
    assert group.auto_receive_eligible is False
    assert group.auto_donate_eligible is True
    assert [issue.code for issue in batch.issues] == ["capacity_unavailable"]


def test_same_main_with_multiple_orders_builds_children_and_one_physical_state():
    batch = aggregate(
        [
            realtime("BUF-1", 10, product_name="Product A"),
            realtime("BUF-2", 20, product_name="Product B"),
        ],
        [master("BUF-1", 100), master("BUF-2", 100)],
        [relation("BUF-1"), relation("BUF-2")],
    )

    assert set(batch.order_states_by_main_and_order) == {
        ("MAIN-1", "ORDER-A"),
        ("MAIN-1", "ORDER-B"),
    }
    assert batch.order_states_by_main_and_order[("MAIN-1", "ORDER-A")].total_inventory == 10
    assert batch.order_states_by_main_and_order[("MAIN-1", "ORDER-B")].total_inventory == 20
    physical = batch.main_buffers_by_main_id["MAIN-1"]
    assert physical.total_inventory == 30
    assert physical.total_capacity == 200
    assert physical.order_codes == ("ORDER-A", "ORDER-B")
    assert not any(issue.code == "multiple_orders_in_main" for issue in batch.issues)


@pytest.mark.parametrize(
    ("relations", "masters", "issue_code"),
    [
        (
            [relation("BUF-1", workshop="S1"), relation("BUF-2", workshop="S2")],
            [master("BUF-1", 100), master("BUF-2", 100)],
            "workshop_conflict",
        ),
        (
            [
                relation("BUF-1"),
                relation("BUF-2", upstream="P2", downstream="P1"),
            ],
            [
                master("BUF-1", 100),
                master("BUF-2", 100),
            ],
            "service_process_conflict",
        ),
    ],
)
def test_same_main_workshop_and_ordered_process_conflicts_are_isolated(
    relations,
    masters,
    issue_code,
):
    batch = aggregate(
        [realtime("BUF-1", 10), realtime("BUF-2", 20)],
        masters,
        relations,
    )

    assert only_group(batch).no_capabilities_enabled
    assert any(issue.code == issue_code for issue in batch.issues)


def test_issue_deduplication_lists_all_related_buffer_codes():
    batch = aggregate(
        [realtime("UNKNOWN-2", 10), realtime("UNKNOWN-1", 20)],
        [],
        [],
    )

    issues = [
        issue
        for issue in batch.issues
        if issue.code == "static_buffer_mapping_unresolved"
    ]
    assert len(issues) == 1
    assert issues[0].main_id == "MAIN-1"
    assert "UNKNOWN-1" in issues[0].message
    assert "UNKNOWN-2" in issues[0].message


def test_index_conflict_never_leaves_an_ambiguous_buffer_mapping():
    batch = aggregate(
        [
            realtime("BUF-1", 10, main_id="MAIN-1"),
            realtime("BUF-1", 20, main_id="MAIN-2", product_name="Product B"),
        ],
        [master("BUF-1", 100)],
        [relation("BUF-1")],
    )

    assert "BUF-1" not in batch.group_key_by_buffer_code
    assert "BUF-1" not in batch.group_key_by_representative_buffer_code
    issues = [issue for issue in batch.issues if issue.code == "buffer_code_index_conflict"]
    assert {issue.main_id for issue in issues} == {"MAIN-1", "MAIN-2"}
    assert all(
        batch.groups_by_group_key[
            batch.group_keys_by_main_id[main_id][0]
        ].no_capabilities_enabled
        for main_id in ("MAIN-1", "MAIN-2")
    )


def test_same_physical_key_on_multiple_mains_keeps_each_main_independent():
    batch = aggregate(
        [
            realtime("BUF-1", 10, main_id="MAIN-1"),
            realtime("BUF-2", 20, main_id="MAIN-2"),
        ],
        [master("BUF-1", 100), master("BUF-2", 100)],
        [relation("BUF-1"), relation("BUF-2")],
    )

    groups = list(batch.groups_by_group_key.values())
    assert {group.main_id for group in groups} == {"MAIN-1", "MAIN-2"}
    assert all(group.all_capabilities_enabled for group in groups)
    assert not any(
        issue.code == "duplicate_order_across_main_ids" for issue in batch.issues
    )


def test_inventory_at_capacity_is_overflow_source_but_not_receiver():
    batch = aggregate(
        [realtime("BUF-1", 100)],
        [master("BUF-1", 100)],
        [relation("BUF-1")],
    )

    group = only_group(batch)
    assert group.overflow_eligible is True
    assert group.overflow_warning_eligible is True
    assert group.auto_donate_eligible is True
    assert group.auto_receive_eligible is False
    assert [issue.code for issue in batch.issues] == [
        "inventory_at_or_above_capacity"
    ]


def test_inventory_over_capacity_keeps_warning_and_donor_capabilities():
    batch = aggregate(
        [realtime("BUF-1", 120)],
        [master("BUF-1", 100)],
        [relation("BUF-1")],
    )

    group = only_group(batch)
    assert group.remaining_capacity == -20
    assert group.overflow_eligible is True
    assert group.overflow_warning_eligible is True
    assert group.auto_donate_eligible is True
    assert group.auto_receive_eligible is False
    assert [issue.code for issue in batch.issues] == [
        "inventory_at_or_above_capacity"
    ]


def test_process_order_is_part_of_physical_buffer_key():
    batch = aggregate(
        [
            realtime("BUF-1", 10, main_id="MAIN-1"),
            realtime("BUF-2", 20, main_id="MAIN-2"),
        ],
        [
            master("BUF-1", 100),
            master("BUF-2", 100),
        ],
        [
            relation("BUF-1"),
            relation("BUF-2", upstream="P2", downstream="P1"),
        ],
    )

    groups = list(batch.groups_by_group_key.values())
    assert len({group.physical_buffer_key for group in groups}) == 2
    assert all(group.all_capabilities_enabled for group in groups)
    assert not any(
        issue.code == "duplicate_order_across_main_ids"
        for issue in batch.issues
    )


def test_same_main_supports_multiple_order_children_and_one_physical_state():
    batch = aggregate(
        [
            realtime("BUF-1", 3000, product_name="Product A"),
            realtime("BUF-2", 2000, product_name="Product A"),
            realtime("BUF-3", 4000, product_name="Product B"),
        ],
        [master("BUF-1", 10000), master("BUF-2", 15000), master("BUF-3", 20000)],
        [relation("BUF-1"), relation("BUF-2"), relation("BUF-3")],
    )

    assert set(batch.order_states_by_main_and_order) == {
        ("MAIN-1", "ORDER-A"),
        ("MAIN-1", "ORDER-B"),
    }
    assert batch.order_states_by_main_and_order[("MAIN-1", "ORDER-A")].total_inventory == 5000
    assert batch.order_states_by_main_and_order[("MAIN-1", "ORDER-B")].total_inventory == 4000
    physical = batch.main_buffers_by_main_id["MAIN-1"]
    assert physical.total_inventory == 9000
    assert physical.total_capacity == 45000
    assert not any(issue.code == "multiple_orders_in_main" for issue in batch.issues)


def test_same_physical_buffer_key_does_not_merge_distinct_main_ids():
    batch = aggregate(
        [realtime("BUF-1", 10, main_id="MAIN-1"), realtime("BUF-2", 20, main_id="MAIN-2")],
        [master("BUF-1", 100), master("BUF-2", 100)],
        [relation("BUF-1"), relation("BUF-2")],
    )

    assert set(batch.main_buffers_by_main_id) == {"MAIN-1", "MAIN-2"}
    assert not any(issue.code == "duplicate_order_across_main_ids" for issue in batch.issues)


def test_ambiguous_product_mapping_isolated_to_its_main():
    @dataclass(frozen=True)
    class ActiveOrder(Order):
        order_status: str = "running"

    orders = [
        ActiveOrder("ORDER-A1", "PRODUCT-A", "Product A", "S1"),
        ActiveOrder("ORDER-A2", "PRODUCT-A", "Product A", "S1"),
        ActiveOrder("ORDER-B", "PRODUCT-B", "Product B", "S1"),
    ]
    batch = MainBufferAggregator().aggregate(
        realtime_buffers=[
            realtime("BUF-1", 10, main_id="BAD", product_name="Product A"),
            realtime("BUF-2", 20, main_id="GOOD", product_name="Product B"),
        ],
        buffer_masters=[master("BUF-1", 100), master("BUF-2", 100)],
        buffer_relations=[relation("BUF-1"), relation("BUF-2")],
        orders=orders,
    )

    assert any(issue.code == "order_mapping_ambiguous" and issue.main_id == "BAD" for issue in batch.issues)
    assert batch.main_buffers_by_main_id["GOOD"].overflow_eligible is True
