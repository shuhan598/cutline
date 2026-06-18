from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)
from app.core.warning.stockout_warning import StockoutWarningEvaluator


SAMPLE_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_sample_input.json"


def load_sample_snapshot():
    return MockAdapter().load(SAMPLE_INPUT_PATH)


def build_warnings(snapshot):
    net_rates = NetRateCalculator(RealtimeFirstRateStrategy()).calculate(snapshot)
    depletions = DepletionTimeCalculator().calculate(snapshot, net_rates)
    return StockoutWarningEvaluator().evaluate(snapshot, depletions)


def find(warnings, buffer_code, product_code, process_from, process_to):
    for warning in warnings:
        if (
            warning.buffer_code == buffer_code
            and warning.product_code == product_code
            and warning.process_from == process_from
            and warning.process_to == process_to
        ):
            return warning
    raise AssertionError("Expected warning result was not found")


def test_config_cutline_lead_minutes_is_thirty():
    assert load_sample_snapshot().config.cutline_lead_minutes == 30


def test_returns_one_result_per_depletion_result():
    snapshot = load_sample_snapshot()
    net_rates = NetRateCalculator(RealtimeFirstRateStrategy()).calculate(snapshot)
    depletions = DepletionTimeCalculator().calculate(snapshot, net_rates)

    warnings = StockoutWarningEvaluator().evaluate(snapshot, depletions)

    assert len(warnings) == len(depletions)


def test_hg182t_triggers_stockout_warning_within_lead_time():
    hg182t = find(build_warnings(load_sample_snapshot()), "BUF_ZR_PK", "HG182T", "ZR", "PK")

    assert hg182t.warning_triggered is True
    assert hg182t.reason == "depletion_time_within_lead_time"
    assert hg182t.depletion_minutes == 30
    assert hg182t.cutline_lead_minutes == 30


def test_hg182r_does_not_trigger_stockout_warning_beyond_lead_time():
    hg182r = find(build_warnings(load_sample_snapshot()), "BUF_ZR_PK", "HG182R", "ZR", "PK")

    assert hg182r.warning_triggered is False
    assert hg182r.reason == "depletion_time_beyond_lead_time"
    assert hg182r.depletion_minutes == 750
    assert hg182r.cutline_lead_minutes == 30


def test_warning_result_exposes_all_contract_fields():
    result = build_warnings(load_sample_snapshot())[0]

    assert set(result.model_dump()) == {
        "buffer_code",
        "product_code",
        "process_from",
        "process_to",
        "warning_type",
        "warning_triggered",
        "reason",
        "inventory_quantity",
        "net_rate_per_hour",
        "depletion_minutes",
        "depletion_status",
        "cutline_lead_minutes",
    }
    assert result.warning_type == "stockout"
