"""Validated reference indexes used while building an algorithm snapshot."""

from __future__ import annotations

from collections.abc import Iterable

from app.schemas.common_schema import (
    AlgorithmMachineMaster,
    AlgorithmOrder,
    AlgorithmProduct,
)
from app.schemas.request_schema import MachineMasterRequest


class SnapshotReferenceIndexError(ValueError):
    """Snapshot reference data is blank, duplicated, or inconsistent."""


class MachineMasterIndex:
    """Map both external machine identifiers to one standard machine."""

    def __init__(self, records: Iterable[MachineMasterRequest]):
        self._machine_masters: list[AlgorithmMachineMaster] = []
        self._by_standard_code: dict[str, AlgorithmMachineMaster] = {}
        self._by_realtime_code: dict[str, AlgorithmMachineMaster] = {}

        for index, record in enumerate(records):
            standard_code = record.machine_code.strip()
            realtime_code = record.p166_jt_group.strip()
            if not standard_code:
                raise SnapshotReferenceIndexError(
                    "machine_master.machine_code must not be blank "
                    f"at index {index}"
                )
            if not realtime_code:
                raise SnapshotReferenceIndexError(
                    "machine_master.p166_jt_group must not be blank for "
                    f"machine_code {standard_code!r}"
                )
            if standard_code in self._by_standard_code:
                raise SnapshotReferenceIndexError(
                    "machine_master.machine_code duplicate: "
                    f"{standard_code!r}"
                )
            if realtime_code in self._by_realtime_code:
                existing = self._by_realtime_code[realtime_code]
                raise SnapshotReferenceIndexError(
                    "machine_master.p166_jt_group duplicate: "
                    f"{realtime_code!r} maps to both "
                    f"{existing.machine_code!r} and {standard_code!r}"
                )

            machine = AlgorithmMachineMaster(
                machine_code=standard_code,
                machine_name=record.machine_name,
                process_code=record.process_code,
                process_name=record.process_name,
            )
            self._machine_masters.append(machine)
            self._by_standard_code[standard_code] = machine
            self._by_realtime_code[realtime_code] = machine

    @property
    def machine_masters(self) -> list[AlgorithmMachineMaster]:
        return list(self._machine_masters)

    @property
    def by_standard_code(self) -> dict[str, AlgorithmMachineMaster]:
        return dict(self._by_standard_code)

    def resolve_agv_code(self, equipment_id: str) -> AlgorithmMachineMaster:
        normalized = equipment_id.strip()
        if not normalized:
            raise SnapshotReferenceIndexError(
                "agv_relations.equipmentid must not be blank"
            )
        machine = self._by_standard_code.get(normalized)
        if machine is None:
            raise SnapshotReferenceIndexError(
                "AGV equipmentid "
                f"{equipment_id!r} did not match machine_master.machine_code"
            )
        return machine

    def resolve_realtime_code(
        self,
        realtime_code: str,
    ) -> AlgorithmMachineMaster:
        normalized = realtime_code.strip()
        if not normalized:
            raise SnapshotReferenceIndexError(
                "machine_realtime.machine_code must not be blank"
            )
        machine = self._by_realtime_code.get(normalized)
        if machine is None:
            raise SnapshotReferenceIndexError(
                "machine_realtime.machine_code "
                f"{realtime_code!r} did not match "
                "machine_master.p166_jt_group"
            )
        return machine


class ProductCatalogIndex:
    """Validate and index the product catalog by code and exact name."""

    def __init__(self, products: Iterable[AlgorithmProduct]):
        self._products: list[AlgorithmProduct] = []
        self._by_code: dict[str, AlgorithmProduct] = {}
        self._by_name: dict[str, AlgorithmProduct] = {}

        for index, product in enumerate(products):
            product_code = product.product_code.strip()
            product_name = product.product_name.strip()
            if not product_code:
                raise SnapshotReferenceIndexError(
                    f"products.product_code must not be blank at index {index}"
                )
            if not product_name:
                raise SnapshotReferenceIndexError(
                    "products.product_name must not be blank for "
                    f"product_code {product_code!r}"
                )
            if product_code in self._by_code:
                raise SnapshotReferenceIndexError(
                    f"products.product_code duplicate: {product_code!r}"
                )
            if product_name in self._by_name:
                existing = self._by_name[product_name]
                raise SnapshotReferenceIndexError(
                    "products.product_name duplicate: "
                    f"{product_name!r} belongs to both "
                    f"{existing.product_code!r} and {product_code!r}"
                )

            normalized_product = product.model_copy(
                update={
                    "product_code": product_code,
                    "product_name": product_name,
                }
            )
            self._products.append(normalized_product)
            self._by_code[product_code] = normalized_product
            self._by_name[product_name] = normalized_product

    @property
    def products(self) -> list[AlgorithmProduct]:
        return list(self._products)

    @property
    def by_code(self) -> dict[str, AlgorithmProduct]:
        return dict(self._by_code)

    def resolve_code(self, product_code: str, *, source: str) -> AlgorithmProduct:
        normalized = product_code.strip()
        product = self._by_code.get(normalized)
        if product is None:
            raise SnapshotReferenceIndexError(
                f"{source} product_code {product_code!r} did not match "
                "products.product_code"
            )
        return product

    def resolve_name(self, product_name: str, *, source: str) -> AlgorithmProduct:
        normalized = product_name.strip()
        if not normalized:
            raise SnapshotReferenceIndexError(
                f"{source} product_name must not be blank"
            )
        product = self._by_name.get(normalized)
        if product is None:
            raise SnapshotReferenceIndexError(
                f"{source} product_name {product_name!r} did not match "
                "products.product_name"
            )
        return product


_ACTIVE_ASCII_ORDER_STATUSES = frozenset({"running", "open"})


def is_current_order_status(status: str) -> bool:
    normalized = status.strip()
    return (
        normalized.casefold() in _ACTIVE_ASCII_ORDER_STATUSES
        or normalized == "生产中"
    )


class CurrentOrderIndex:
    """Validate all orders and index active orders by exact product name."""

    def __init__(
        self,
        orders: Iterable[AlgorithmOrder],
        product_catalog: ProductCatalogIndex,
    ):
        self._orders: list[AlgorithmOrder] = []
        self._by_code: dict[str, AlgorithmOrder] = {}
        self._by_product_name: dict[str, AlgorithmOrder] = {}

        for index, order in enumerate(orders):
            order_code = order.order_code.strip()
            product_code = order.product_code.strip()
            product_name = order.product_name.strip()
            if not order_code:
                raise SnapshotReferenceIndexError(
                    f"orders.order_code must not be blank at index {index}"
                )
            if order_code in self._by_code:
                raise SnapshotReferenceIndexError(
                    f"orders.order_code duplicate: {order_code!r}"
                )

            product = product_catalog.resolve_code(
                product_code,
                source=f"Order {order_code}",
            )
            if product_name != product.product_name:
                raise SnapshotReferenceIndexError(
                    f"Order {order_code} product_code {product_code!r} "
                    f"maps to product_name {product.product_name!r}, not "
                    f"{order.product_name!r}"
                )
            normalized_order = order.model_copy(
                update={
                    "order_code": order_code,
                    "product_code": product_code,
                    "product_name": product_name,
                }
            )
            self._orders.append(normalized_order)
            self._by_code[order_code] = normalized_order
            if is_current_order_status(order.order_status):
                existing = self._by_product_name.get(product_name)
                if existing is not None:
                    raise SnapshotReferenceIndexError(
                        f"product_name {product_name!r} maps to multiple "
                        "current orders among active statuses: "
                        f"{existing.order_code!r}, {order_code!r}"
                    )
                self._by_product_name[product_name] = normalized_order

    @property
    def orders(self) -> list[AlgorithmOrder]:
        return list(self._orders)

    @property
    def by_code(self) -> dict[str, AlgorithmOrder]:
        return dict(self._by_code)

    def resolve_product_name(
        self,
        product_name: str,
        *,
        source: str,
    ) -> AlgorithmOrder:
        normalized = product_name.strip()
        if not normalized:
            raise SnapshotReferenceIndexError(
                f"{source} product_name must not be blank"
            )
        order = self._by_product_name.get(normalized)
        if order is None:
            raise SnapshotReferenceIndexError(
                f"{source} product_name {product_name!r} did not match a "
                "current order; no current active order exists"
            )
        return order
