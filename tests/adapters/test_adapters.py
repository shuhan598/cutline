from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.adapters.snapshot_adapter import SnapshotAdapter
from app.schemas.request_schema import CutlineSnapshot


EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
COMPLEX_INPUT_PATH = EXAMPLES / "cutline_complex_input.json"
SAMPLE_INPUT_PATH = EXAMPLES / "cutline_sample_input.json"


def test_mock_adapter_loads_complex_example_into_snapshot():
    snapshot = MockAdapter().load(COMPLEX_INPUT_PATH)

    assert isinstance(snapshot, CutlineSnapshot)
    assert len(snapshot.machine_statuses) == 14
    assert len(snapshot.buffer_inventories) == 4
    assert snapshot.config.cutline_lead_minutes == 30


def test_mock_adapter_preserves_equipment_name():
    snapshot = MockAdapter().load(COMPLEX_INPUT_PATH)

    target = next(
        machine
        for machine in snapshot.machine_statuses
        if machine.equipment_code == "zr_hg182t_target"
    )
    assert target.equipment_name == "ZR HG182T Target"


def test_mock_adapter_ignores_extra_top_level_keys():
    snapshot = MockAdapter().load(SAMPLE_INPUT_PATH)

    assert isinstance(snapshot, CutlineSnapshot)
    assert len(snapshot.capacity_records) == 7


def test_snapshot_adapter_injects_default_current_time_when_missing():
    snapshot = SnapshotAdapter().to_snapshot({"machine_statuses": []})

    assert snapshot.current_time is not None
