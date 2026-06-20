from datetime import datetime
from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.silk_screen.silk_screen_handler import SilkScreenHandler


SILK_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_silk_screen_input.json"


def load_snapshot():
    return MockAdapter().load(SILK_INPUT_PATH)


def test_identifies_terminal_exit_process_as_silk_screen():
    codes = SilkScreenHandler().identify_silk_screen_processes(load_snapshot())
    assert codes == {"SW"}


def test_order_trigger_emits_preparation_warning():
    results = SilkScreenHandler().evaluate_order_triggers(load_snapshot())
    assert len(results) == 1
    result = results[0]
    assert result.equipment_code == "sw01"
    assert result.process_code == "SW"
    assert result.remaining_quantity == 1000
    assert result.completion_time == datetime(2026, 6, 20, 10, 10, 0)
    assert result.preparation_time == datetime(2026, 6, 20, 9, 40, 0)
    assert result.triggered is True
