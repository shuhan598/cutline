def calculate_runtime_load(
    *,
    input_quantity_30m: float,
    output_quantity_30m: float,
) -> tuple[float, float]:
    """仅根据实时上料和出料数量计算利用率与空闲度。"""

    if input_quantity_30m == 0:
        if output_quantity_30m == 0:
            return 0.0, 1.0
        return 1.0, 0.0

    utilization_rate = output_quantity_30m / input_quantity_30m
    return utilization_rate, 1.0 - utilization_rate


def calculate_hourly_output(output_quantity_30m: float) -> float:
    """将最近三十分钟出料数量换算为实时小时产出。"""

    return output_quantity_30m * 2

