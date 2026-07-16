import importlib

import pytest


def _module():
    return importlib.import_module("app.core.candidate_machine.machine_load")


@pytest.mark.parametrize(
    ("input_quantity", "output_quantity", "expected"),
    [
        (10000, 8000, (0.8, 0.2)),
        (0, 0, (0.0, 1.0)),
        (0, 1000, (1.0, 0.0)),
        (8000, 10000, (1.25, -0.25)),
    ],
)
def test_runtime_load_uses_unscaled_realtime_input_and_output(
    input_quantity: float,
    output_quantity: float,
    expected: tuple[float, float],
):
    utilization_rate, idle_rate = _module().calculate_runtime_load(
        input_quantity_30m=input_quantity,
        output_quantity_30m=output_quantity,
    )

    assert utilization_rate == pytest.approx(expected[0])
    assert idle_rate == pytest.approx(expected[1])


def test_hourly_output_is_realtime_output_times_two():
    assert _module().calculate_hourly_output(8000) == 16000

