"""根据订单库存和净消耗速率预测断料时间。"""

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
        """根据当前快照和业务规则执行【calculate_algorithm】计算，返回类型标注所声明的结果。"""
        return [
            self._for_algorithm_interval(net_rate)
            for net_rate in net_rate_results
        ]

    def _for_algorithm_interval(
        self,
        net_rate: AlgorithmIntervalNetRateResult,
    ) -> AlgorithmDepletionTimeResult:
        """内部辅助步骤【_for_algorithm_interval】，为上层业务流程提供数据处理或共用判断。"""
        depletion_minutes = None
        if net_rate.net_consumption_rate > 0:
            depletion_minutes = (
                net_rate.current_quantity
                / net_rate.net_consumption_rate
                * 60
            )

        return AlgorithmDepletionTimeResult(
            main_id=net_rate.main_id,
            buffer_code=net_rate.buffer_code,
            buffer_codes=list(net_rate.buffer_codes),
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
            group_key=net_rate.group_key,
        )
