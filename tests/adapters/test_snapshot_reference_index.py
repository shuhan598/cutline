from __future__ import annotations

import pytest

from app.adapters.snapshot_reference_index import (
    CurrentOrderIndex,
    ProductCatalogIndex,
    SnapshotReferenceIndexError,
)
from app.schemas.common_schema import AlgorithmOrder, AlgorithmProduct


def _product() -> AlgorithmProduct:
    return AlgorithmProduct(
        product_code="P1",
        product_name="Product One",
        wafer_size="210",
        source_grade="A",
        material_code="MAT-P1",
        material_name="Material P1",
    )


def _order(order_code: str, status: str) -> AlgorithmOrder:
    return AlgorithmOrder(
        order_code=order_code,
        order_status=status,
        product_code="P1",
        product_name="Product One",
        workshop_code="W1",
        workshop_name="Workshop One",
        total_quantity=1000.0,
        produced_quantity=100.0,
        piece_source="A",
        estimated_yield="99%",
    )


@pytest.mark.parametrize("active_status", [" running ", "OpEn", "生产中"])
def test_current_order_index_maps_only_the_unique_active_order(
    active_status: str,
) -> None:
    index = CurrentOrderIndex(
        [_order("O-ACTIVE", active_status), _order("O-INACTIVE", "WAITING")],
        ProductCatalogIndex([_product()]),
    )

    resolved = index.resolve_product_name("Product One", source="AGV M1")

    assert resolved.order_code == "O-ACTIVE"
    assert set(index.by_code) == {"O-ACTIVE", "O-INACTIVE"}
    assert index.by_code["O-INACTIVE"].order_status == "WAITING"


def test_current_order_index_keeps_multiple_active_candidates_but_strict_resolution_rejects(
) -> None:
    index = CurrentOrderIndex(
        [_order("O-ACTIVE-1", "RUNNING"), _order("O-ACTIVE-2", "OPEN")],
        ProductCatalogIndex([_product()]),
    )

    assert [item.order_code for item in index.resolve_product_name_candidates("Product One")] == [
        "O-ACTIVE-1",
        "O-ACTIVE-2",
    ]
    with pytest.raises(
        SnapshotReferenceIndexError,
        match=r"Product One.*O-ACTIVE-1.*O-ACTIVE-2",
    ):
        index.resolve_product_name("Product One", source="AGV M1")


def test_current_order_index_reports_when_only_inactive_orders_exist() -> None:
    index = CurrentOrderIndex(
        [_order("O-WAITING", "WAITING"), _order("O-PENDING", "待生产")],
        ProductCatalogIndex([_product()]),
    )

    with pytest.raises(
        SnapshotReferenceIndexError,
        match=r"Product One.*current active order",
    ):
        index.resolve_product_name("Product One", source="AGV M1")

    assert set(index.by_code) == {"O-WAITING", "O-PENDING"}


def test_inactive_order_still_requires_a_valid_product_identity() -> None:
    invalid = _order("O-WAITING", "WAITING").model_copy(
        update={"product_name": "Wrong Product"}
    )

    with pytest.raises(
        SnapshotReferenceIndexError,
        match=r"O-WAITING.*Product One.*Wrong Product",
    ):
        CurrentOrderIndex([invalid], ProductCatalogIndex([_product()]))
