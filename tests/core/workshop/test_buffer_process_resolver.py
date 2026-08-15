from dataclasses import dataclass

import pytest

from app.core.workshop.buffer_process_resolver import (
    BufferProcessResolutionError,
    BufferProcessResolver,
)


@dataclass(frozen=True)
class _Route:
    process_code: str
    sequence: int
    workshop_code: str = "S1"
    loop_code: str = "LOOP2"


@dataclass(frozen=True)
class _Buffer:
    served_process_codes: list[str]
    buffer_code: str = "BUF-01"
    loop_code: str = "LOOP2"


@dataclass(frozen=True)
class _RouteWithoutLoop:
    process_code: str
    sequence: int
    workshop_code: str = "S1"


@dataclass(frozen=True)
class _BufferWithoutLoop:
    served_process_codes: list[str]
    buffer_code: str = "BUF-WITHOUT-LOOP"


def _resolver(*routes: _Route) -> BufferProcessResolver:
    return BufferProcessResolver(routes)


def test_resolves_cross_loop_processes_in_same_workshop():
    resolver = _resolver(
        _Route("OXIDATION", 40, loop_code="LOOP2"),
        _Route("ALKALI_POLISH", 50, loop_code="LOOP3"),
    )

    resolution = resolver.resolve(
        _Buffer(["OXIDATION", "ALKALI_POLISH"])
    )

    assert resolution.workshop_code == "S1"
    assert resolution.upstream_process_code == "OXIDATION"
    assert resolution.downstream_process_code == "ALKALI_POLISH"


def test_reversed_served_codes_are_ordered_by_backend_sequence():
    resolver = _resolver(
        _Route("OXIDATION", 40),
        _Route("ALKALI_POLISH", 50),
    )

    resolution = resolver.resolve(
        _Buffer(["ALKALI_POLISH", "OXIDATION"])
    )

    assert resolution.upstream_process_code == "OXIDATION"
    assert resolution.downstream_process_code == "ALKALI_POLISH"


def test_intermediate_route_does_not_make_interval_invalid():
    resolver = _resolver(
        _Route("OXIDATION", 40),
        _Route("INTERMEDIATE", 45),
        _Route("ALKALI_POLISH", 50),
    )

    resolution = resolver.resolve(
        _Buffer(["OXIDATION", "ALKALI_POLISH"])
    )

    assert resolution.upstream_process_code == "OXIDATION"
    assert resolution.downstream_process_code == "ALKALI_POLISH"


def test_buffer_loop_does_not_filter_route_candidates():
    resolver = _resolver(
        _Route("OXIDATION", 40, loop_code="LOOP2"),
        _Route("ALKALI_POLISH", 50, loop_code="LOOP3"),
    )

    resolution = resolver.resolve(
        _Buffer(
            ["OXIDATION", "ALKALI_POLISH"],
            loop_code="OBVIOUSLY-WRONG",
        )
    )

    assert resolution.workshop_code == "S1"
    assert resolution.upstream_process_code == "OXIDATION"
    assert resolution.downstream_process_code == "ALKALI_POLISH"


@pytest.mark.parametrize(
    "served_process_codes",
    [[], ["OXIDATION"], ["OXIDATION", "ALKALI_POLISH", "ANNEAL"]],
)
def test_requires_exactly_two_served_process_codes(served_process_codes):
    resolver = _resolver(
        _Route("OXIDATION", 40),
        _Route("ALKALI_POLISH", 50),
    )

    with pytest.raises(
        BufferProcessResolutionError,
        match=r"Buffer BUF-01 must serve exactly two processes",
    ):
        resolver.resolve(_Buffer(served_process_codes))


def test_rejects_missing_process_route_with_buffer_and_process_context():
    resolver = _resolver(_Route("OXIDATION", 40))

    with pytest.raises(
        BufferProcessResolutionError,
        match=r"Buffer BUF-01 process MISSING has no route",
    ):
        resolver.resolve(_Buffer(["OXIDATION", "MISSING"]))


def test_rejects_processes_without_one_common_workshop():
    resolver = _resolver(
        _Route("OXIDATION", 40, workshop_code="S1"),
        _Route("ALKALI_POLISH", 50, workshop_code="S2"),
    )

    with pytest.raises(
        BufferProcessResolutionError,
        match=(
            r"Buffer BUF-01.*OXIDATION.*ALKALI_POLISH"
            r".*same workshop"
        ),
    ):
        resolver.resolve(_Buffer(["OXIDATION", "ALKALI_POLISH"]))


def test_rejects_ambiguous_common_workshops():
    resolver = _resolver(
        _Route("OXIDATION", 40, workshop_code="S1"),
        _Route("ALKALI_POLISH", 50, workshop_code="S1"),
        _Route("OXIDATION", 60, workshop_code="S2"),
        _Route("ALKALI_POLISH", 70, workshop_code="S2"),
    )

    with pytest.raises(
        BufferProcessResolutionError,
        match=(
            r"Buffer BUF-01.*OXIDATION.*ALKALI_POLISH"
            r".*multiple.*pairs"
        ),
    ):
        resolver.resolve(_Buffer(["OXIDATION", "ALKALI_POLISH"]))


def test_rejects_multiple_route_pairs_within_one_workshop():
    resolver = _resolver(
        _Route("OXIDATION", 40, workshop_code="S1"),
        _Route("OXIDATION", 41, workshop_code="S1"),
        _Route("ALKALI_POLISH", 50, workshop_code="S1"),
    )

    with pytest.raises(
        BufferProcessResolutionError,
        match=(
            r"Buffer BUF-01.*OXIDATION.*ALKALI_POLISH"
            r".*multiple.*pairs"
        ),
    ):
        resolver.resolve(_Buffer(["OXIDATION", "ALKALI_POLISH"]))


def test_rejects_equal_sequences_without_guessing_direction():
    resolver = _resolver(
        _Route("OXIDATION", 40),
        _Route("ALKALI_POLISH", 40),
    )

    with pytest.raises(
        BufferProcessResolutionError,
        match=r"Buffer BUF-01 served process routes have equal sequence",
    ):
        resolver.resolve(_Buffer(["OXIDATION", "ALKALI_POLISH"]))


def test_resolves_route_and_buffer_views_without_loop_fields():
    resolver = BufferProcessResolver(
        [
            _RouteWithoutLoop("OXIDATION", 40),
            _RouteWithoutLoop("ALKALI_POLISH", 50),
        ]
    )

    resolution = resolver.resolve(
        _BufferWithoutLoop(["ALKALI_POLISH", "OXIDATION"])
    )

    assert resolution.workshop_code == "S1"
    assert resolution.upstream_process_code == "OXIDATION"
    assert resolution.downstream_process_code == "ALKALI_POLISH"
