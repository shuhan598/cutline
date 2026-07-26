import pytest

from app.core.workshop.machine_workshop_resolver import (
    MachineWorkshopResolutionError,
    MachineWorkshopResolver,
)
from app.schemas.common_schema import (
    AlgorithmMachineMaster,
    AlgorithmProcessRoute,
)


def _route(
    process_code: str = "P01",
    *,
    workshop_code: str = "S1",
    loop_code: str = "LOOP-01",
) -> AlgorithmProcessRoute:
    return AlgorithmProcessRoute(
        process_code=process_code,
        process_name=process_code,
        sequence=1,
        cache_type="BUFFER",
        workshop_code=workshop_code,
        workshop_name=workshop_code,
        loop_code=loop_code,
        loop_name=loop_code,
        upstream_process_code=None,
        upstream_process_name=None,
        downstream_process_code=None,
        downstream_process_name=None,
    )


def _machine(
    machine_code: str = "EA001",
    process_code: str = "P01",
) -> AlgorithmMachineMaster:
    return AlgorithmMachineMaster(
        machine_code=machine_code,
        machine_name=machine_code,
        process_code=process_code,
        process_name=process_code,
    )


def test_resolves_process_to_its_route_workshop():
    resolver = MachineWorkshopResolver([_route()])

    assert resolver.resolve_by_process_code("P01") == "S1"
    assert resolver.resolve_machine_workshop(_machine()) == "S1"


def test_same_process_in_multiple_loops_of_same_workshop_is_allowed():
    resolver = MachineWorkshopResolver(
        [
            _route(loop_code="LOOP-01"),
            _route(loop_code="LOOP-02"),
        ]
    )

    assert resolver.resolve_by_process_code("P01") == "S1"


def test_cross_workshop_conflict_is_stable_and_lists_all_workshops():
    routes = [
        _route(workshop_code="S2", loop_code="LOOP-02"),
        _route(workshop_code="S1", loop_code="LOOP-01"),
        _route(workshop_code="S3", loop_code="LOOP-03"),
    ]

    resolver = MachineWorkshopResolver(routes)

    with pytest.raises(
        MachineWorkshopResolutionError,
        match=r"Process P01 belongs to multiple workshops: S1, S2, S3",
    ):
        resolver.resolve_by_process_code("P01")


def test_machine_conflict_error_keeps_machine_process_and_workshops():
    resolver = MachineWorkshopResolver(
        [
            _route(workshop_code="S2", loop_code="LOOP-02"),
            _route(workshop_code="S1", loop_code="LOOP-01"),
        ]
    )

    with pytest.raises(
        MachineWorkshopResolutionError,
        match=(
            r"Machine EA001 process P01 belongs to multiple workshops: S1, S2"
        ),
    ):
        resolver.resolve_machine_workshop(_machine())


def test_unknown_process_fails_without_fallback():
    resolver = MachineWorkshopResolver([_route()])

    with pytest.raises(
        MachineWorkshopResolutionError,
        match=r"Process UNKNOWN has no process route",
    ):
        resolver.resolve_by_process_code("UNKNOWN")


def test_machine_error_keeps_machine_and_process_codes():
    resolver = MachineWorkshopResolver([_route()])

    with pytest.raises(
        MachineWorkshopResolutionError,
        match=r"Machine EA099 process UNKNOWN has no process route",
    ):
        resolver.resolve_machine_workshop(_machine("EA099", "UNKNOWN"))
