from typing import get_type_hints

from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.schemas.request_schema import AlgorithmSnapshot


def test_calculate_accepts_only_algorithm_snapshot():
    hints = get_type_hints(NetRateCalculator.calculate)

    assert hints["snapshot"] is AlgorithmSnapshot


def test_legacy_snapshot_calculator_is_not_exposed():
    assert not hasattr(NetRateCalculator, "_calculate_legacy_snapshot")
