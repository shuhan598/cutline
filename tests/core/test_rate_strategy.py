from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.schemas.common_schema import MachineRuntimeStatus


def machine(**overrides):
    base = {"equipment_code": "m1", "process_code": "ZR", "status": "running"}
    base.update(overrides)
    return MachineRuntimeStatus(**base)


def test_prefers_realtime_rate():
    strategy = RealtimeFirstRateStrategy()
    m = machine(
        input_rate_per_hour=100,
        output_rate_per_hour=120,
        input_quantity_30min=999,
        out_quantity_30min=999,
        actual_capacity_per_hour=999,
    )
    assert strategy.input_rate(m) == 100
    assert strategy.output_rate(m) == 120


def test_falls_back_to_30min_quantity_times_two():
    strategy = RealtimeFirstRateStrategy()
    m = machine(
        input_quantity_30min=50,
        out_quantity_30min=60,
        actual_capacity_per_hour=999,
    )
    assert strategy.input_rate(m) == 100
    assert strategy.output_rate(m) == 120


def test_falls_back_to_static_capacity():
    strategy = RealtimeFirstRateStrategy()
    m = machine(actual_capacity_per_hour=80)
    assert strategy.input_rate(m) == 80
    assert strategy.output_rate(m) == 80


def test_returns_zero_when_no_source():
    strategy = RealtimeFirstRateStrategy()
    m = machine()
    assert strategy.input_rate(m) == 0.0
    assert strategy.output_rate(m) == 0.0
