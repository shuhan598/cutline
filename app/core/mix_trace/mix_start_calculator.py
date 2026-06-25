# 混料起始时刻计算：残留消耗 + AGV 送料 + 工艺时长 推算 T_mix_start，产出混料通知

from datetime import timedelta
from typing import List, Optional

from app.schemas.common_schema import MachineCapacityRecord
from app.schemas.request_schema import MixTraceRequest
from app.schemas.response_schema import MixTraceNotification
from app.utils.numeric import safe_float


class MixStartCalculator:
    """对一次切线事件计算混料起始时刻与型号组成；缺产能数据返回 None。"""

    def calculate(self, request: MixTraceRequest) -> Optional[MixTraceNotification]:
        event = request.cutline_event
        config = request.config
        record = self._capacity_record(
            request.capacity_records, event.equipment_code, event.previous_product_code
        )
        if record is None:
            return None
        capacity = safe_float(record.actual_capacity_per_hour)
        if capacity <= 0:
            return None

        basket_capacity = safe_float(config.basket_capacity)
        residual_minutes = (
            safe_float(config.max_feed_basket_count) * basket_capacity / capacity * 60
        )
        mix_start_time = event.cut_time + timedelta(
            minutes=residual_minutes
            + safe_float(config.agv_delivery_minutes)
            + safe_float(record.process_time_minutes)
        )

        basket_count = config.mix_basket_count
        half_quantity = basket_count / 2 * basket_capacity
        product_compositions = [
            {
                "product_code": event.previous_product_code,
                "sequence_no": 1,
                "estimated_quantity": half_quantity,
            },
            {
                "product_code": event.next_product_code,
                "sequence_no": 2,
                "estimated_quantity": half_quantity,
            },
        ]
        status = "arrived" if request.current_time >= mix_start_time else "pending"

        return MixTraceNotification(
            source_equipment_code=event.equipment_code,
            workshop_code=event.workshop_code,
            workshop_name=event.workshop_name,
            cut_time=event.cut_time,
            previous_product_code=event.previous_product_code,
            next_product_code=event.next_product_code,
            mix_start_time=mix_start_time,
            mix_basket_count=basket_count,
            estimated_total_quantity=basket_count * basket_capacity,
            product_compositions=product_compositions,
            status=status,
        )

    def _capacity_record(
        self,
        records: List[MachineCapacityRecord],
        equipment_code: str,
        product_code: str,
    ) -> Optional[MachineCapacityRecord]:
        for record in records:
            if record.equipment_code == equipment_code and record.product_code == product_code:
                return record
        return None
