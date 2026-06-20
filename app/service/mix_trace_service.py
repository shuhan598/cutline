# 混料追溯门面：调用 MixStartCalculator，把通知包装为 MixTraceResponse

from typing import Optional

from app.core.mix_trace.mix_start_calculator import MixStartCalculator
from app.schemas.request_schema import MixTraceRequest
from app.schemas.response_schema import MixTraceResponse


class MixTraceService:
    """对外统一入口：trace(request) -> MixTraceResponse。"""

    def __init__(self, calculator: Optional[MixStartCalculator] = None):
        self._calculator = calculator or MixStartCalculator()

    def trace(self, request: MixTraceRequest) -> MixTraceResponse:
        notification = self._calculator.calculate(request)
        if notification is None:
            event = request.cutline_event
            return MixTraceResponse(
                success=False,
                message=(
                    f"缺少机台 {event.equipment_code} / 型号 "
                    f"{event.previous_product_code} 的静态产能或工艺时长"
                ),
                notifications=[],
            )
        return MixTraceResponse(
            success=True,
            message="",
            notifications=[notification],
        )
