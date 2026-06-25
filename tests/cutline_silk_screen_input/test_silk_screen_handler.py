from datetime import datetime
from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.silk_screen.silk_screen_handler import SilkScreenHandler
from app.schemas.common_schema import (
    AlgorithmConfig,
    BufferSegment,
    LineMaster,
    MachineMaster,
    MachineRuntimeStatus,
    OrderInfo,
)
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import SilkScreenOrderResult
from app.service.cutline_service import CutlineService
from app.service.cutline_pipeline import PipelineResult


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


def test_order_trigger_resolves_machine_workshop():
    snapshot = CutlineSnapshot(
        current_time=datetime(2026, 6, 20, 10, 0, 0),
        machine_statuses=[
            MachineRuntimeStatus(
                equipment_code="sw01",
                process_code="SW",
                status="running",
                order_code="O1",
                product_code="HG182T",
                output_rate_per_hour=6000,
            )
        ],
        machine_masters=[
            MachineMaster(
                equipment_code="sw01",
                process_code="SW",
                line_code="LINE_S2",
            )
        ],
        line_masters=[
            LineMaster(
                line_code="LINE_S2",
                workshop_code="S2",
                workshop_name="S2车间",
            )
        ],
        buffer_segments=[
            BufferSegment(
                buffer_code="BUF",
                service_process_codes=["PK", "SW"],
                max_capacity=10000,
            )
        ],
        orders=[
            OrderInfo(
                order_code="O1",
                product_code="HG182T",
                total_quantity=1000,
                completed_quantity=0,
            )
        ],
        config=AlgorithmConfig(silk_screen_clear_minutes=30),
    )

    result = SilkScreenHandler().evaluate_order_triggers(snapshot)[0]

    assert result.workshop_code == "S2"
    assert result.workshop_name == "S2车间"


class SilkWorkshopPipeline:
    def run(self, snapshot):
        return PipelineResult(
            net_rates=[],
            depletions=[],
            warnings=[],
            candidates=[],
            silk_orders=[
                SilkScreenOrderResult(
                    equipment_code="sw01",
                    process_code="SW",
                    product_code="HG182T",
                    order_code="O1",
                    remaining_quantity=1000,
                    completion_time=datetime(2026, 6, 20, 10, 10, 0),
                    preparation_time=datetime(2026, 6, 20, 9, 40, 0),
                    silk_screen_clear_minutes=30,
                    workshop_code="S2",
                    workshop_name="S2车间",
                    triggered=True,
                )
            ],
        )


def test_silk_warning_response_surfaces_workshop_info():
    response = CutlineService(SilkWorkshopPipeline()).evaluate(load_snapshot())

    warning = response.warnings[0]
    assert warning.workshop_code == "S2"
    assert warning.workshop_name == "S2车间"
