# 净速率计算组件：吃 CutlineSnapshot，吐 list[NetRateResult]

from app.core.net_rate.rate_strategy import RateStrategy
from app.core.workshop.workshop_resolver import WorkshopResolver
from app.schemas.common_schema import BufferInventoryItem, CycleMaster
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import NetRateResult


class NetRateCalculator:
    """按 buffer 区间(段)聚合上游产出与下游吞入，得到净消耗速率。"""

    def __init__(self, rate_strategy: RateStrategy):
        self._rate_strategy = rate_strategy

    def calculate(self, snapshot: CutlineSnapshot) -> list[NetRateResult]:
        results = []
        seen_segments = set()
        workshop_resolver = WorkshopResolver(snapshot)

        for inventory in snapshot.buffer_inventories:
            segment_key = (
                inventory.cycle_code,
                inventory.buffer_code,
                inventory.product_code,
                inventory.process_from,
                inventory.process_to,
            )
            if segment_key in seen_segments:
                continue

            seen_segments.add(segment_key)
            results.append(
                self._calculate_segment(snapshot, inventory, workshop_resolver)
            )

        return results

    def _calculate_segment(
        self,
        snapshot: CutlineSnapshot,
        inventory: BufferInventoryItem,
        workshop_resolver: WorkshopResolver,
    ) -> NetRateResult:
        cycle_code, cycle_name, workshop_code, workshop_name = self._cycle_info(
            snapshot,
            inventory,
            workshop_resolver,
        )
        upstream_output_per_hour = 0.0
        downstream_input_per_hour = 0.0
        upstream_equipment_codes = []
        downstream_equipment_codes = []

        for machine in snapshot.machine_statuses:
            if machine.status != "running":
                continue
            if machine.product_code != inventory.product_code:
                continue
            machine_workshop_code, _ = workshop_resolver.resolve_machine_workshop(machine)
            if not workshop_resolver.is_same_workshop(
                machine_workshop_code,
                workshop_code,
            ):
                continue

            if machine.process_code == inventory.process_from:
                upstream_output_per_hour += self._rate_strategy.output_rate(machine)
                upstream_equipment_codes.append(machine.equipment_code)
            elif machine.process_code == inventory.process_to:
                downstream_input_per_hour += self._rate_strategy.input_rate(machine)
                downstream_equipment_codes.append(machine.equipment_code)

        return NetRateResult(
            buffer_code=inventory.buffer_code,
            cycle_code=cycle_code,
            cycle_name=cycle_name,
            workshop_code=workshop_code,
            workshop_name=workshop_name,
            product_code=inventory.product_code,
            process_from=inventory.process_from,
            process_to=inventory.process_to,
            inventory_quantity=inventory.inventory_quantity,
            upstream_output_per_hour=upstream_output_per_hour,
            downstream_input_per_hour=downstream_input_per_hour,
            net_rate_per_hour=downstream_input_per_hour - upstream_output_per_hour,
            upstream_equipment_codes=upstream_equipment_codes,
            downstream_equipment_codes=downstream_equipment_codes,
        )

    def _cycle_info(
        self,
        snapshot: CutlineSnapshot,
        inventory: BufferInventoryItem,
        workshop_resolver: WorkshopResolver,
    ) -> tuple[str | None, str | None, str | None, str | None]:
        cycle_master = self._find_cycle_master(snapshot, inventory.cycle_code)
        workshop_code, workshop_name = workshop_resolver.resolve_inventory_workshop(
            inventory
        )
        if cycle_master is None:
            return inventory.cycle_code, inventory.cycle_name, workshop_code, workshop_name
        return (
            inventory.cycle_code,
            cycle_master.cycle_name or inventory.cycle_name,
            workshop_code,
            workshop_name,
        )

    def _find_cycle_master(
        self,
        snapshot: CutlineSnapshot,
        cycle_code: str | None,
    ) -> CycleMaster | None:
        if not cycle_code:
            return None
        for cycle_master in snapshot.cycle_masters:
            if cycle_master.cycle_code == cycle_code:
                return cycle_master
        return None
