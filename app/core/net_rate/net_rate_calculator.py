# 净速率计算组件：吃 CutlineSnapshot，吐 list[NetRateResult]

from app.core.net_rate.rate_strategy import RateStrategy
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import NetRateResult


class NetRateCalculator:
    """按 buffer 区间(段)聚合上游产出与下游吞入，得到净消耗速率。"""

    def __init__(self, rate_strategy: RateStrategy):
        self._rate_strategy = rate_strategy

    def calculate(self, snapshot: CutlineSnapshot) -> list[NetRateResult]:
        results = []
        seen_segments = set()

        for inventory in snapshot.buffer_inventories:
            segment_key = (
                inventory.buffer_code,
                inventory.product_code,
                inventory.process_from,
                inventory.process_to,
            )
            if segment_key in seen_segments:
                continue

            seen_segments.add(segment_key)
            results.append(self._calculate_segment(snapshot, *segment_key))

        return results

    def _calculate_segment(
        self,
        snapshot: CutlineSnapshot,
        buffer_code,
        product_code,
        process_from,
        process_to,
    ) -> NetRateResult:
        upstream_output_per_hour = 0.0
        downstream_input_per_hour = 0.0
        upstream_equipment_codes = []
        downstream_equipment_codes = []

        for machine in snapshot.machine_statuses:
            if machine.status != "running":
                continue
            if machine.product_code != product_code:
                continue

            if machine.process_code == process_from:
                upstream_output_per_hour += self._rate_strategy.output_rate(machine)
                upstream_equipment_codes.append(machine.equipment_code)
            elif machine.process_code == process_to:
                downstream_input_per_hour += self._rate_strategy.input_rate(machine)
                downstream_equipment_codes.append(machine.equipment_code)

        return NetRateResult(
            buffer_code=buffer_code,
            product_code=product_code,
            process_from=process_from,
            process_to=process_to,
            upstream_output_per_hour=upstream_output_per_hour,
            downstream_input_per_hour=downstream_input_per_hour,
            net_rate_per_hour=downstream_input_per_hour - upstream_output_per_hour,
            upstream_equipment_codes=upstream_equipment_codes,
            downstream_equipment_codes=downstream_equipment_codes,
        )
