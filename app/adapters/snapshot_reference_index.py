"""构建算法快照时使用的、经过完整性校验的引用索引。"""

from __future__ import annotations

from collections.abc import Iterable

from app.schemas.common_schema import (
    AlgorithmMachineMaster,
    AlgorithmOrder,
    AlgorithmProduct,
)
from app.schemas.request_schema import MachineMasterRequest


class SnapshotReferenceIndexError(ValueError):
    """快照引用数据为空、重复或互相不一致。"""


class MachineMasterIndex:
    """把两种外部机台标识映射到同一台标准机台。"""

    def __init__(self, records: Iterable[MachineMasterRequest]):
        """初始化【__init__】对象的状态、索引和依赖。"""
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
        """执行【machine_masters】业务操作；参数、返回值和异常语义以类型标注及调用方契约为准。"""
        return list(self._machine_masters)

    @property
    def by_standard_code(self) -> dict[str, AlgorithmMachineMaster]:
        """执行【by_standard_code】业务操作；参数、返回值和异常语义以类型标注及调用方契约为准。"""
        return dict(self._by_standard_code)

    def resolve_agv_code(self, equipment_id: str) -> AlgorithmMachineMaster:
        """根据当前快照和业务规则执行【resolve_agv_code】计算，返回类型标注所声明的结果。"""
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
        """根据当前快照和业务规则执行【resolve_realtime_code】计算，返回类型标注所声明的结果。"""
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
    """校验产品目录，并按编码和精确名称建立索引。"""

    def __init__(self, products: Iterable[AlgorithmProduct]):
        """初始化【__init__】对象的状态、索引和依赖。"""
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
        """执行【products】业务操作；参数、返回值和异常语义以类型标注及调用方契约为准。"""
        return list(self._products)

    @property
    def by_code(self) -> dict[str, AlgorithmProduct]:
        """执行【by_code】业务操作；参数、返回值和异常语义以类型标注及调用方契约为准。"""
        return dict(self._by_code)

    def resolve_code(self, product_code: str, *, source: str) -> AlgorithmProduct:
        """根据当前快照和业务规则执行【resolve_code】计算，返回类型标注所声明的结果。"""
        normalized = product_code.strip()
        product = self._by_code.get(normalized)
        if product is None:
            raise SnapshotReferenceIndexError(
                f"{source} product_code {product_code!r} did not match "
                "products.product_code"
            )
        return product

    def resolve_name(self, product_name: str, *, source: str) -> AlgorithmProduct:
        """根据当前快照和业务规则执行【resolve_name】计算，返回类型标注所声明的结果。"""
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
    """执行【is_current_order_status】业务操作；参数、返回值和异常语义以类型标注及调用方契约为准。"""
    normalized = status.strip()
    return (
        normalized.casefold() in _ACTIVE_ASCII_ORDER_STATUSES
        or normalized == "生产中"
    )


class CurrentOrderIndex:
    """校验全部订单，并按产品精确名称索引当前有效订单。"""

    def __init__(
        self,
        orders: Iterable[AlgorithmOrder],
        product_catalog: ProductCatalogIndex,
    ):
        """初始化【__init__】对象的状态、索引和依赖。"""
        self._orders: list[AlgorithmOrder] = []
        self._by_code: dict[str, AlgorithmOrder] = {}
        self._by_product_name: dict[str, AlgorithmOrder] = {}
        self._by_product_name_candidates: dict[str, list[AlgorithmOrder]] = {}

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
                self._by_product_name_candidates.setdefault(product_name, []).append(
                    normalized_order
                )
                if len(self._by_product_name_candidates[product_name]) == 1:
                    self._by_product_name[product_name] = normalized_order
                else:
                    self._by_product_name.pop(product_name, None)

    @property
    def orders(self) -> list[AlgorithmOrder]:
        """执行【orders】业务操作；参数、返回值和异常语义以类型标注及调用方契约为准。"""
        return list(self._orders)

    @property
    def by_code(self) -> dict[str, AlgorithmOrder]:
        """执行【by_code】业务操作；参数、返回值和异常语义以类型标注及调用方契约为准。"""
        return dict(self._by_code)

    def resolve_product_name(
        self,
        product_name: str,
        *,
        source: str,
    ) -> AlgorithmOrder:
        """根据当前快照和业务规则执行【resolve_product_name】计算，返回类型标注所声明的结果。"""
        normalized = product_name.strip()
        if not normalized:
            raise SnapshotReferenceIndexError(
                f"{source} product_name must not be blank"
            )
        candidates = self._by_product_name_candidates.get(normalized, [])
        if not candidates:
            raise SnapshotReferenceIndexError(
                f"{source} product_name {product_name!r} did not match a "
                "current order; no current active order exists"
            )
        if len(candidates) > 1:
            raise SnapshotReferenceIndexError(
                f"{source} product_name {product_name!r} maps to multiple "
                "current orders: "
                + ", ".join(order.order_code for order in candidates)
            )
        return candidates[0]

    def resolve_product_name_candidates(
        self,
        product_name: str,
    ) -> list[AlgorithmOrder]:
        """根据当前快照和业务规则执行【resolve_product_name_candidates】计算，返回类型标注所声明的结果。"""
        return list(self._by_product_name_candidates.get(product_name.strip(), ()))
