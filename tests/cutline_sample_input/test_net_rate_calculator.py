from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.schemas.common_schema import MachineMaster, MachineRuntimeStatus


SAMPLE_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_sample_input.json"


def load_sample_snapshot():
    return MockAdapter().load(SAMPLE_INPUT_PATH)


def calculate(snapshot):
    return NetRateCalculator(RealtimeFirstRateStrategy()).calculate(snapshot)


def by_segment(results):
    return {
        (r.buffer_code, r.product_code, r.process_from, r.process_to): r
        for r in results
    }


def test_calculates_hg182t_stockout_net_rate():
    result = by_segment(calculate(load_sample_snapshot()))[
        ("BUF_ZR_PK", "HG182T", "ZR", "PK")
    ]

    assert result.upstream_output_per_hour == 16000
    assert result.downstream_input_per_hour == 19200
    assert result.net_rate_per_hour == 3200
    assert set(result.upstream_equipment_codes) == {"zr01", "zr02"}
    assert set(result.downstream_equipment_codes) == {"pk01", "pk02"}


def test_calculates_hg182r_net_rate_without_excluding_zr03():
    result = by_segment(calculate(load_sample_snapshot()))[
        ("BUF_ZR_PK", "HG182R", "ZR", "PK")
    ]

    assert result.upstream_output_per_hour == 8000
    assert result.downstream_input_per_hour == 9600
    assert result.net_rate_per_hour == 1600
    assert set(result.upstream_equipment_codes) == {"zr03"}
    assert set(result.downstream_equipment_codes) == {"pk03"}


def test_calculate_all_net_rates_uses_buffer_inventories():
    segments = by_segment(calculate(load_sample_snapshot()))

    assert segments[("BUF_ZR_PK", "HG182T", "ZR", "PK")].net_rate_per_hour == 3200
    assert segments[("BUF_ZR_PK", "HG182R", "ZR", "PK")].net_rate_per_hour == 1600


def test_net_rate_result_includes_cycle_and_workshop_from_inventory_cycle():
    result = by_segment(calculate(load_sample_snapshot()))[
        ("BUF_ZR_PK", "HG182T", "ZR", "PK")
    ]

    assert result.cycle_code == "CYCLE_S2_01"
    assert result.cycle_name == "S2 cycle"
    assert result.workshop_code == "S2"
    assert result.workshop_name == "S2 workshop"
    assert result.inventory_quantity == 1600


def test_s1_same_product_process_machines_do_not_enter_s2_net_rate():
    snapshot = load_sample_snapshot()
    snapshot.machine_masters.extend(
        [
            MachineMaster(
                equipment_code="s1_zr_hg182t",
                process_code="ZR",
                line_code="LINE_S1_01",
            ),
            MachineMaster(
                equipment_code="s1_pk_hg182t",
                process_code="PK",
                line_code="LINE_S1_01",
            ),
        ]
    )
    snapshot.machine_statuses.extend(
        [
            MachineRuntimeStatus(
                equipment_code="s1_zr_hg182t",
                process_code="ZR",
                status="running",
                product_code="HG182T",
                output_rate_per_hour=9999,
            ),
            MachineRuntimeStatus(
                equipment_code="s1_pk_hg182t",
                process_code="PK",
                status="running",
                product_code="HG182T",
                input_rate_per_hour=9999,
            ),
        ]
    )

    result = by_segment(calculate(snapshot))[("BUF_ZR_PK", "HG182T", "ZR", "PK")]

    assert result.workshop_code == "S2"
    assert result.upstream_output_per_hour == 16000
    assert result.downstream_input_per_hour == 19200
    assert set(result.upstream_equipment_codes) == {"zr01", "zr02"}
    assert set(result.downstream_equipment_codes) == {"pk01", "pk02"}


def test_unresolved_inventory_workshop_does_not_mix_all_workshops():
    snapshot = load_sample_snapshot()
    first_inventory = snapshot.buffer_inventories[0]
    snapshot.buffer_inventories[0] = first_inventory.model_copy(
        update={"cycle_code": "UNKNOWN_CYCLE", "cycle_name": "unknown cycle"}
    )

    result = by_segment(calculate(snapshot))[
        ("BUF_ZR_PK", "HG182T", "ZR", "PK")
    ]

    assert result.cycle_code == "UNKNOWN_CYCLE"
    assert result.workshop_code is None
    assert result.upstream_output_per_hour == 0
    assert result.downstream_input_per_hour == 0
    assert result.net_rate_per_hour == 0
    assert result.upstream_equipment_codes == []
    assert result.downstream_equipment_codes == []
