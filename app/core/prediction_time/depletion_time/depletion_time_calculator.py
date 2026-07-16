# 断料时间组件：输入 AlgorithmIntervalNetRateResult 列表，输出 AlgorithmDepletionTimeResult 列表

from app.schemas.result_schema import (
    AlgorithmDepletionTimeResult,
    AlgorithmIntervalNetRateResult,
)


class DepletionTimeCalculator:
    """按净速率与区间库存推算耗尽时间（分钟）。"""

    def calculate_algorithm(
        self,
        net_rate_results: list[AlgorithmIntervalNetRateResult],
    ) -> list[AlgorithmDepletionTimeResult]:
        return [
            self._for_algorithm_interval(net_rate)
            for net_rate in net_rate_results
        ]

    def _for_algorithm_interval(
        self,
        net_rate: AlgorithmIntervalNetRateResult,
    ) -> AlgorithmDepletionTimeResult:
        depletion_minutes = None
        if net_rate.net_consumption_rate > 0:
            depletion_minutes = (
                net_rate.current_quantity
                / net_rate.net_consumption_rate
                * 60
            )

        return AlgorithmDepletionTimeResult(
            buffer_code=net_rate.buffer_code,
            order_code=net_rate.order_code,
            wafer_size=net_rate.wafer_size,
            wafer_spec=net_rate.wafer_spec,
            workshop_code=net_rate.workshop_code,
            upstream_process_code=net_rate.upstream_process_code,
            downstream_process_code=net_rate.downstream_process_code,
            current_quantity=net_rate.current_quantity,
            upstream_output_rate=net_rate.upstream_output_rate,
            downstream_input_rate=net_rate.downstream_input_rate,
            net_consumption_rate=net_rate.net_consumption_rate,
            depletion_minutes=depletion_minutes,
        )
