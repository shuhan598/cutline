from datetime import datetime
from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.schemas.result_schema import ReturnResult
from app.service.cutline_service import CutlineService
from app.service.cutline_pipeline import PipelineResult


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


class ReturnWorkshopPipeline:
    def run(self, snapshot):
        return PipelineResult(
            net_rates=[],
            depletions=[],
            warnings=[],
            candidates=[],
            return_results=[
                ReturnResult(
                    equipment_code="zr03",
                    product_code="HG182T",
                    original_product_code="HG182R",
                    buffer_code="BUF_S2",
                    process_from="ZR",
                    process_to="PK",
                    net_rate_per_hour=-6400,
                    inventory_quantity=5000,
                    negative_start_time=datetime(2026, 6, 20, 9, 35, 0),
                    negative_duration_minutes=25,
                    safety_inventory_quantity=3200,
                    workshop_code="S2",
                    workshop_name="S2车间",
                    triggered=True,
                )
            ],
        )


def test_return_suggestion_surfaces_workshop_info():
    snapshot = MockAdapter().load(RETURN_INPUT_PATH)
    response = CutlineService(ReturnWorkshopPipeline()).evaluate(snapshot)

    suggestion = response.return_suggestions[0]
    assert suggestion.workshop_code == "S2"
    assert suggestion.workshop_name == "S2车间"
