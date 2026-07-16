from app.core.warning.overflow_warning import OverflowWarningEvaluator
from app.core.warning.stockout_warning import StockoutWarningEvaluator


def test_stockout_warning_exposes_only_algorithm_api():
    assert not hasattr(StockoutWarningEvaluator, "evaluate")
    assert not hasattr(StockoutWarningEvaluator, "_for_segment")


def test_overflow_warning_exposes_only_algorithm_api():
    assert not hasattr(OverflowWarningEvaluator, "evaluate")
