from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.service.cutline_pipeline import CutlinePipeline


OVERFLOW_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_overflow_input.json"


def test_pipeline_produces_overflow_warning_and_plan():
    snapshot = MockAdapter().load(OVERFLOW_INPUT_PATH)
    result = CutlinePipeline().run(snapshot)

    triggered = [w for w in result.overflow_warnings if w.warning_triggered]
    assert [w.product_code for w in triggered] == ["HG182T"]

    overflow_plans = [p for p in result.plans if p.warning_type == "overflow"]
    assert len(overflow_plans) == 1
    assert overflow_plans[0].selected_machines[0].equipment_code == "zr_t1"
    assert result.manual_interventions == []
    assert result.return_results == []
