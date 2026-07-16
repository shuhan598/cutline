from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)
from app.core.prediction_time.overflow_time.overflow_time_calculator import (
    OverflowTimeCalculator,
)


def test_depletion_calculator_exposes_only_algorithm_api():
    assert not hasattr(DepletionTimeCalculator, "calculate")
    assert not hasattr(DepletionTimeCalculator, "_for_segment")
    assert not hasattr(DepletionTimeCalculator, "_inventory_quantity")


def test_overflow_calculator_exposes_only_algorithm_api():
    assert not hasattr(OverflowTimeCalculator, "calculate")
    assert not hasattr(OverflowTimeCalculator, "_segment_inventory")
