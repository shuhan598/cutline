# 丝网处理：自动识别 buffer 链终端出口工序；按订单进度触发清台准备预警

from datetime import timedelta
from typing import List, Set

from app.core.workshop.workshop_resolver import WorkshopResolver
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import SilkScreenOrderResult
from app.utils.numeric import safe_float


class SilkScreenHandler:
    """识别丝网工序并产出订单进度触发的清台准备预警。"""

    def identify_silk_screen_processes(self, snapshot: CutlineSnapshot) -> Set[str]:
        exits = set()
        upstreams = set()
        for segment in snapshot.buffer_segments:
            codes = segment.service_process_codes
            if not codes:
                continue
            exits.add(codes[-1])
            upstreams.update(codes[:-1])
        return {code for code in exits if code not in upstreams}

    def evaluate_order_triggers(self, snapshot: CutlineSnapshot) -> List[SilkScreenOrderResult]:
        silk_codes = self.identify_silk_screen_processes(snapshot)
        clear_minutes = safe_float(snapshot.config.silk_screen_clear_minutes)
        order_map = {order.order_code: order for order in snapshot.orders}
        current = snapshot.current_time
        workshop_resolver = WorkshopResolver(snapshot)

        results = []
        for machine in snapshot.machine_statuses:
            if machine.process_code not in silk_codes:
                continue
            if machine.status != "running":
                continue
            order = order_map.get(machine.order_code)
            if order is None:
                continue
            capacity = safe_float(machine.output_rate_per_hour)
            if capacity <= 0:
                continue
            remaining = safe_float(order.total_quantity) - safe_float(order.completed_quantity)
            if remaining <= 0:
                continue
            machine_workshop_code, machine_workshop_name = (
                workshop_resolver.resolve_machine_workshop(machine)
            )
            completion_time = current + timedelta(minutes=remaining / capacity * 60)
            preparation_time = completion_time - timedelta(minutes=clear_minutes)
            results.append(
                SilkScreenOrderResult(
                    equipment_code=machine.equipment_code,
                    workshop_code=machine_workshop_code,
                    workshop_name=machine_workshop_name,
                    process_code=machine.process_code,
                    product_code=machine.product_code,
                    order_code=machine.order_code,
                    remaining_quantity=remaining,
                    completion_time=completion_time,
                    preparation_time=preparation_time,
                    silk_screen_clear_minutes=clear_minutes,
                    triggered=current >= preparation_time,
                )
            )
        return results
