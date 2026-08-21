"""按 main、订单和工艺区间计算快照中的唯一净消耗速率。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, TypeVar

from app.core.workshop.machine_workshop_resolver import (
    MachineWorkshopResolutionError,
    MachineWorkshopResolver,
)
from app.core.buffer_aggregation.models import MainBufferGroup
from app.schemas.common_schema import (
    AlgorithmAgvRelation,
    AlgorithmBufferOrderInventory,
    AlgorithmBufferProcessRelation,
    AlgorithmMachineMaster,
    AlgorithmMachineRuntime,
    AlgorithmOrder,
    AlgorithmProduct,
)
from app.schemas.request_schema import AlgorithmSnapshot
from app.schemas.result_schema import AlgorithmIntervalNetRateResult


class NetRateCalculationError(ValueError):
    """区间净消耗速率无法计算时抛出的异常。"""


ModelT = TypeVar("ModelT")


@dataclass(frozen=True)
class _AlgorithmNetRateContext:
    """类 【_AlgorithmNetRateContext】封装该领域的数据或服务能力，对外提供稳定的业务契约。"""
    machine_by_code: dict[str, AlgorithmMachineMaster]
    order_by_code: dict[str, AlgorithmOrder]
    product_by_code: dict[str, AlgorithmProduct]
    buffer_relation_by_code: dict[str, AlgorithmBufferProcessRelation]
    agv_by_machine_code: dict[str, AlgorithmAgvRelation]
    workshop_resolver: MachineWorkshopResolver


class NetRateCalculator:
    """计算算法快照中各订单工艺区间的净速率。"""

    def calculate(
        self,
        snapshot: AlgorithmSnapshot,
    ) -> list[AlgorithmIntervalNetRateResult]:
        """计算快照内每个可参与预警的订单库存区间的净消耗速率。

        当聚合批次存在时优先使用物理 main 的订单分组；旧数据路径才按单个
        Buffer 库存记录计算。两条路径最终返回相同语义的区间结果。
        """
        return self._calculate_algorithm_snapshot(snapshot)

    def _calculate_algorithm_snapshot(
        self,
        snapshot: AlgorithmSnapshot,
    ) -> list[AlgorithmIntervalNetRateResult]:
        """建立机台关联上下文，并根据聚合数据是否可用选择计算粒度。"""
        context = self._build_machine_context(snapshot)
        # 新路径直接消费聚合后的 (main_id, order_code) 子状态，避免多
        # buffer 层重复扫描同一批机台产能。
        if snapshot.main_buffer_batch.groups_by_group_key:
            return [
                self._calculate_group_net_rate(snapshot, group, context)
                for group in snapshot.main_buffer_batch.groups
                if group.stockout_eligible
            ]
        return [
            self._calculate_inventory_net_rate(
                snapshot,
                inventory,
                buffer_codes,
                context,
            )
            for inventory, buffer_codes in self._group_buffer_inventories(
                snapshot.buffer_order_inventories,
                context,
            )
        ]

    def _calculate_group_net_rate(
        self,
        snapshot: AlgorithmSnapshot,
        group: MainBufferGroup,
        context: _AlgorithmNetRateContext,
    ) -> AlgorithmIntervalNetRateResult:
        """计算一个物理 main 内单订单、单规格、单工艺区间的库存变化速率。

        净消耗速率等于匹配下游机台的小时投入减去上游机台的小时产出；正值说明
        该订单库存正在减少，负值说明库存正在积压。
        """
        order = context.order_by_code.get(group.order_code)
        if order is None:
            raise NetRateCalculationError(
                f"{group.order_code} order does not exist for main Buffer group"
            )
        product = context.product_by_code.get(order.product_code)
        if product is None:
            raise NetRateCalculationError(
                f"{order.product_code} product does not exist for order "
                f"{order.order_code}"
            )
        representative = group.representative_buffer_code
        if representative is None:
            raise NetRateCalculationError(
                f"{group.main_id} eligible main Buffer group has no representative layer"
            )
        if len(group.ordered_service_process_codes) != 2:
            raise NetRateCalculationError(
                f"{group.main_id} main Buffer group process interval is invalid"
            )
        upstream_process, downstream_process = (
            group.ordered_service_process_codes
        )
        relation = AlgorithmBufferProcessRelation(
            buffer_code=representative,
            workshop_code=group.workshop_code,
            upstream_process_code=upstream_process,
            downstream_process_code=downstream_process,
        )
        wafer_spec = self._resolve_order_wafer_spec(
            group.order_code,
            snapshot.agv_relations,
        )
        upstream_output_rate = self._calculate_upstream_output_rate(
            snapshot,
            group.order_code,
            wafer_spec,
            relation,
            context,
        )
        downstream_input_rate = self._calculate_downstream_input_rate(
            snapshot,
            group.order_code,
            wafer_spec,
            relation,
            context,
        )
        # 正值表示库存增长，负值表示库存消耗；公开净消耗率使用相反符号。
        inventory_change_rate = upstream_output_rate - downstream_input_rate
        return AlgorithmIntervalNetRateResult(
            main_id=group.main_id,
            buffer_code=representative,
            buffer_codes=list(group.buffer_codes),
            order_code=group.order_code,
            wafer_size=product.wafer_size,
            wafer_spec=wafer_spec,
            workshop_code=group.workshop_code,
            upstream_process_code=upstream_process,
            downstream_process_code=downstream_process,
            current_quantity=group.total_inventory,
            upstream_output_rate=upstream_output_rate,
            downstream_input_rate=downstream_input_rate,
            net_consumption_rate=-inventory_change_rate,
            inventory_change_rate=inventory_change_rate,
            group_key=group.group_key,
        )

    def _group_buffer_inventories(
        self,
        inventories: Iterable[AlgorithmBufferOrderInventory],
        context: _AlgorithmNetRateContext,
    ) -> list[tuple[AlgorithmBufferOrderInventory, list[str]]]:
        """在兼容路径将同一 main、订单和工艺区间的 Buffer 库存合并。

        同一物理 Buffer、订单组合出现重复记录会使库存翻倍，因此直接拒绝；同一
        main 关联不同工艺区间同样不可计算，必须由上游数据修正。
        """
        quantities_by_group: dict[
            tuple[str, str, str, str, str], float
        ] = {}
        buffer_codes_by_group: dict[
            tuple[str, str, str, str, str], set[str]
        ] = {}
        interval_by_main_id: dict[str, tuple[str, str, str]] = {}
        main_id_by_buffer: dict[str, str] = {}
        seen_physical_inventory: set[tuple[str, str, str]] = set()

        # 兼容路径将同一 main、订单和工艺区间的库存相加，同时拒绝重复明细。
        for inventory in inventories:
            if not inventory.main_id.strip():
                raise NetRateCalculationError(
                    f"{inventory.buffer_code} buffer inventory main_id is blank"
                )
            relation = context.buffer_relation_by_code.get(
                inventory.buffer_code
            )
            if relation is None:
                raise NetRateCalculationError(
                    f"{inventory.buffer_code} process relation does not exist "
                    "for buffer inventory"
                )

            existing_main_id = main_id_by_buffer.get(inventory.buffer_code)
            if (
                existing_main_id is not None
                and existing_main_id != inventory.main_id
            ):
                raise NetRateCalculationError(
                    f"{inventory.buffer_code} buffer inventory belongs to "
                    f"multiple main_id values: {existing_main_id!r}, "
                    f"{inventory.main_id!r}"
                )
            main_id_by_buffer[inventory.buffer_code] = inventory.main_id

            physical_key = (
                inventory.main_id,
                inventory.buffer_code,
                inventory.order_code,
            )
            if physical_key in seen_physical_inventory:
                raise NetRateCalculationError(
                    f"{inventory.main_id} {inventory.buffer_code} "
                    f"{inventory.order_code} duplicate buffer inventory"
                )
            seen_physical_inventory.add(physical_key)

            interval = (
                relation.workshop_code,
                relation.upstream_process_code,
                relation.downstream_process_code,
            )
            expected_interval = interval_by_main_id.get(inventory.main_id)
            if expected_interval is None:
                interval_by_main_id[inventory.main_id] = interval
            elif expected_interval != interval:
                raise NetRateCalculationError(
                    f"{inventory.main_id} buffer group has multiple process "
                    f"intervals: {expected_interval!r}, {interval!r}"
                )

            group_key = (
                inventory.main_id,
                relation.workshop_code,
                relation.upstream_process_code,
                relation.downstream_process_code,
                inventory.order_code,
            )
            quantities_by_group[group_key] = (
                quantities_by_group.get(group_key, 0.0)
                + inventory.current_quantity
            )
            buffer_codes_by_group.setdefault(group_key, set()).add(
                inventory.buffer_code
            )

        grouped: list[
            tuple[AlgorithmBufferOrderInventory, list[str]]
        ] = []
        for group_key in sorted(quantities_by_group):
            main_id, _, _, _, order_code = group_key
            buffer_codes = sorted(buffer_codes_by_group[group_key])
            grouped.append(
                (
                    AlgorithmBufferOrderInventory(
                        main_id=main_id,
                        buffer_code=buffer_codes[0],
                        order_code=order_code,
                        current_quantity=quantities_by_group[group_key],
                    ),
                    buffer_codes,
                )
            )
        return grouped

    def _build_machine_context(
        self,
        snapshot: AlgorithmSnapshot,
    ) -> _AlgorithmNetRateContext:
        """构造计算速率所需的唯一索引，并预校验机台主数据和车间归属。"""
        machine_by_code = self._unique_index(
            snapshot.machine_masters,
            "machine_code",
            "machine master",
        )
        order_by_code = self._unique_index(snapshot.orders, "order_code", "order")
        product_by_code = self._unique_index(
            snapshot.products,
            "product_code",
            "product",
        )
        agv_by_machine_code = self._unique_index(
            snapshot.agv_relations,
            "machine_code",
            "AGV relation",
        )
        workshop_resolver = MachineWorkshopResolver(
            snapshot.process_routes
        )

        buffer_relation_by_code: dict[str, AlgorithmBufferProcessRelation] = {}
        ambiguous_buffer_codes: set[str] = set()
        for relation in snapshot.buffer_process_relations:
            if relation.buffer_code in ambiguous_buffer_codes:
                continue
            if relation.buffer_code in buffer_relation_by_code:
                if snapshot.main_buffer_batch.groups_by_group_key:
                    buffer_relation_by_code.pop(relation.buffer_code)
                    ambiguous_buffer_codes.add(relation.buffer_code)
                    continue
                raise NetRateCalculationError(
                    f"{relation.buffer_code} has multiple process relations"
                )
            buffer_relation_by_code[relation.buffer_code] = relation

        for runtime in snapshot.machine_runtimes:
            if runtime.machine_code not in machine_by_code:
                raise NetRateCalculationError(
                    f"{runtime.machine_code} machine master does not exist for runtime"
                )
            try:
                workshop_resolver.resolve_machine_workshop(
                    machine_by_code[runtime.machine_code]
                )
            except MachineWorkshopResolutionError as exc:
                raise NetRateCalculationError(str(exc)) from exc
        return _AlgorithmNetRateContext(
            machine_by_code=machine_by_code,
            order_by_code=order_by_code,
            product_by_code=product_by_code,
            buffer_relation_by_code=buffer_relation_by_code,
            agv_by_machine_code=agv_by_machine_code,
            workshop_resolver=workshop_resolver,
        )

    def _resolve_order_wafer_spec(
        self,
        order_code: str,
        agv_relations: Iterable[AlgorithmAgvRelation],
    ) -> str:
        """从当前生效 AGV 绑定中取得订单的硅片规格。

        产品表只描述尺寸，规格以 AGV 实际绑定为准；缺失绑定时不能假定默认规格。
        """
        matching_relations = sorted(
            (
                relation
                for relation in agv_relations
                if relation.order_code == order_code
            ),
            key=lambda relation: relation.machine_code,
        )
        if not matching_relations:
            raise NetRateCalculationError(
                f"Order {order_code} wafer_spec cannot be determined from "
                "snapshot.agv_relations: no effective AGV relation matches "
                f"order {order_code}"
            )
        return matching_relations[0].wafer_spec

    def _calculate_inventory_net_rate(
        self,
        snapshot: AlgorithmSnapshot,
        inventory: AlgorithmBufferOrderInventory,
        buffer_codes: list[str],
        context: _AlgorithmNetRateContext,
    ) -> AlgorithmIntervalNetRateResult:
        """按兼容数据结构计算一个合并库存记录的上下游速率和库存变化。"""
        if inventory.order_code not in context.order_by_code:
            raise NetRateCalculationError(
                f"{inventory.order_code} order does not exist for buffer inventory"
            )
        order = context.order_by_code[inventory.order_code]
        product = context.product_by_code.get(order.product_code)
        if product is None:
            raise NetRateCalculationError(
                f"{order.product_code} product does not exist for order "
                f"{order.order_code}"
            )
        if (
            not isinstance(product.wafer_size, str)
            or not product.wafer_size.strip()
        ):
            raise NetRateCalculationError(
                f"{product.product_code} product wafer_size is missing"
            )
        relation = context.buffer_relation_by_code.get(inventory.buffer_code)
        if relation is None:
            raise NetRateCalculationError(
                f"{inventory.buffer_code} process relation does not exist "
                "for buffer inventory"
            )

        wafer_spec = self._resolve_order_wafer_spec(
            inventory.order_code,
            snapshot.agv_relations,
        )
        upstream_output_rate = self._calculate_upstream_output_rate(
            snapshot,
            inventory.order_code,
            wafer_spec,
            relation,
            context,
        )
        downstream_input_rate = self._calculate_downstream_input_rate(
            snapshot,
            inventory.order_code,
            wafer_spec,
            relation,
            context,
        )
        return AlgorithmIntervalNetRateResult(
            main_id=inventory.main_id,
            buffer_code=inventory.buffer_code,
            buffer_codes=list(buffer_codes),
            order_code=inventory.order_code,
            wafer_size=product.wafer_size,
            wafer_spec=wafer_spec,
            workshop_code=relation.workshop_code,
            upstream_process_code=relation.upstream_process_code,
            downstream_process_code=relation.downstream_process_code,
            current_quantity=inventory.current_quantity,
            upstream_output_rate=upstream_output_rate,
            downstream_input_rate=downstream_input_rate,
            net_consumption_rate=downstream_input_rate - upstream_output_rate,
            inventory_change_rate=upstream_output_rate - downstream_input_rate,
        )

    def _calculate_upstream_output_rate(
        self,
        snapshot: AlgorithmSnapshot,
        order_code: str,
        wafer_spec: str,
        relation: AlgorithmBufferProcessRelation,
        context: _AlgorithmNetRateContext,
    ) -> float:
        """汇总匹配库存区间的上游运行机台半小时产出，并换算为小时速率。"""
        return sum(
            runtime.output_quantity_30m
            for runtime in self._matching_runtimes(
                snapshot,
                order_code,
                wafer_spec,
                relation.workshop_code,
                relation.upstream_process_code,
                context,
            )
        ) * 2

    def _calculate_downstream_input_rate(
        self,
        snapshot: AlgorithmSnapshot,
        order_code: str,
        wafer_spec: str,
        relation: AlgorithmBufferProcessRelation,
        context: _AlgorithmNetRateContext,
    ) -> float:
        """汇总匹配库存区间的下游运行机台半小时投入，并换算为小时速率。"""
        return sum(
            runtime.input_quantity_30m
            for runtime in self._matching_runtimes(
                snapshot,
                order_code,
                wafer_spec,
                relation.workshop_code,
                relation.downstream_process_code,
                context,
            )
        ) * 2

    def _matching_runtimes(
        self,
        snapshot: AlgorithmSnapshot,
        order_code: str,
        wafer_spec: str,
        workshop_code: str,
        process_code: str,
        context: _AlgorithmNetRateContext,
    ) -> Iterable[AlgorithmMachineRuntime]:
        """产出与指定订单、规格、车间和工序完全一致的运行机台实时记录。"""
        for runtime in snapshot.machine_runtimes:
            if not self._is_running(runtime):
                continue
            agv_relation = context.agv_by_machine_code.get(
                runtime.machine_code
            )
            if agv_relation is None:
                continue
            if agv_relation.order_code != order_code:
                continue
            if agv_relation.wafer_spec != wafer_spec:
                continue
            machine = context.machine_by_code[runtime.machine_code]
            machine_workshop_code = (
                context.workshop_resolver.resolve_machine_workshop(machine)
            )
            if machine_workshop_code != workshop_code:
                continue
            if machine.process_code != process_code:
                continue
            yield runtime

    def _is_running(self, runtime: AlgorithmMachineRuntime) -> bool:
        """判断标准化后的机台状态是否允许计入实时产能。"""
        return runtime.status == "running"

    def _unique_index(
        self,
        items: Iterable[ModelT],
        field: str,
        label: str,
    ) -> dict[str, ModelT]:
        """按业务键构建唯一索引；重复键会使后续引用不可确定，因此立即失败。"""
        result: dict[str, ModelT] = {}
        for item in items:
            key = getattr(item, field)
            if key in result:
                raise NetRateCalculationError(f"Duplicate {label}: {key}")
            result[key] = item
        return result
