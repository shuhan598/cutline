from datetime import datetime
from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.service.cutline_service import CutlineService


RETURN_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_return_input.json"


def evaluate():
    snapshot = MockAdapter().load(RETURN_INPUT_PATH)
    return CutlineService().evaluate(snapshot)


def test_triggered_return_surfaced_as_suggestion():
    response = evaluate()
    assert [s.equipment_code for s in response.return_suggestions] == ["zr03"]
    suggestion = response.return_suggestions[0]
    assert suggestion.product_code == "HG182T"
    assert suggestion.original_product_code == "HG182R"


def test_all_tracked_events_returned_with_updated_state():
    response = evaluate()
    by_equipment = {e.equipment_code: e for e in response.tracked_events}
    assert set(by_equipment) == {"zr03", "zr_r"}
    assert by_equipment["zr03"].negative_start_time == datetime(2026, 6, 20, 9, 35, 0)
    assert by_equipment["zr_r"].negative_start_time is None
