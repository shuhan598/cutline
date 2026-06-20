from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.service.cutline_service import CutlineService


OVERFLOW_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_overflow_input.json"


def evaluate():
    snapshot = MockAdapter().load(OVERFLOW_INPUT_PATH)
    return CutlineService().evaluate(snapshot)


def test_overflow_warning_surfaced_with_overflow_type():
    response = evaluate()
    overflow = [w for w in response.warnings if w.warning_type == "overflow"]
    assert len(overflow) == 1
    assert overflow[0].product_code == "HG182T"
    assert overflow[0].prediction_minutes == 30


def test_overflow_plan_surfaced():
    response = evaluate()
    overflow_plans = [p for p in response.plans if p.warning.warning_type == "overflow"]
    assert len(overflow_plans) == 1
    selected = overflow_plans[0].selected_machines
    assert selected[0].equipment_code == "zr_t1"
    assert selected[0].target_product_code == "HG182R"
