from dataclasses import FrozenInstanceError, fields

import pytest

from app.core.workshop.process_loop_catalog import (
    _PROCESS_LOOP_CATALOG,
    ProcessLoopAssignment,
    UnknownProcessNameError,
    normalize_process_name,
    resolve_process_loop,
)


PROCESS_LOOP_CASES = [
    ("发料机", "LOOP1", "一循环"),
    ("制绒", "LOOP2", "二循环"),
    ("硼扩", "LOOP2", "二循环"),
    ("氧化", "LOOP2", "二循环"),
    ("碱抛", "LOOP3", "三循环"),
    ("POLY", "LOOP3", "三循环"),
    ("退火", "LOOP3", "三循环"),
    ("RCA", "LOOP4", "四循环"),
    ("ALD", "LOOP5", "五循环"),
    ("正膜", "LOOP5", "五循环"),
    ("背膜", "LOOP5", "五循环"),
    ("丝网", "LOOP5", "五循环"),
]


def test_catalog_contains_exactly_the_twelve_approved_process_names():
    approved_process_names = {
        "发料机",
        "制绒",
        "硼扩",
        "氧化",
        "碱抛",
        "POLY",
        "退火",
        "RCA",
        "ALD",
        "正膜",
        "背膜",
        "丝网",
    }

    assert len(_PROCESS_LOOP_CATALOG) == 12
    assert set(_PROCESS_LOOP_CATALOG) == approved_process_names


def test_catalog_keys_match_every_assignment_process_name():
    assert all(
        process_name == assignment.process_name
        for process_name, assignment in _PROCESS_LOOP_CATALOG.items()
    )


def test_catalog_rejects_adding_processes():
    original_catalog = dict(_PROCESS_LOOP_CATALOG)
    extra_assignment = ProcessLoopAssignment("额外", "LOOP6", "六循环")

    try:
        with pytest.raises(TypeError):
            _PROCESS_LOOP_CATALOG["额外"] = extra_assignment
    finally:
        if isinstance(_PROCESS_LOOP_CATALOG, dict):
            _PROCESS_LOOP_CATALOG.clear()
            _PROCESS_LOOP_CATALOG.update(original_catalog)


def test_catalog_rejects_deleting_processes():
    original_catalog = dict(_PROCESS_LOOP_CATALOG)

    try:
        with pytest.raises(TypeError):
            del _PROCESS_LOOP_CATALOG["发料机"]
    finally:
        if isinstance(_PROCESS_LOOP_CATALOG, dict):
            _PROCESS_LOOP_CATALOG.clear()
            _PROCESS_LOOP_CATALOG.update(original_catalog)


@pytest.mark.parametrize(
    ("process_name", "loop_code", "loop_name"),
    PROCESS_LOOP_CASES,
)
def test_resolves_complete_catalog_and_trims_every_process_name(
    process_name: str,
    loop_code: str,
    loop_name: str,
):
    assert resolve_process_loop(f" \t{process_name}\n") == (
        ProcessLoopAssignment(
            process_name=process_name,
            loop_code=loop_code,
            loop_name=loop_name,
        )
    )


@pytest.mark.parametrize(
    ("raw_name", "normalized_name"),
    [
        ("poly", "POLY"),
        ("PoLy", "POLY"),
        ("rca", "RCA"),
        ("RcA", "RCA"),
        ("ald", "ALD"),
        ("AlD", "ALD"),
        (" unknown ", "unknown"),
    ],
)
def test_normalizes_only_supported_ascii_acronyms(
    raw_name: str,
    normalized_name: str,
):
    assert normalize_process_name(raw_name) == normalized_name


@pytest.mark.parametrize(
    ("raw_name", "canonical_name", "loop_code", "loop_name"),
    [
        ("pOlY", "POLY", "LOOP3", "三循环"),
        ("rCa", "RCA", "LOOP4", "四循环"),
        ("aLd", "ALD", "LOOP5", "五循环"),
    ],
)
def test_resolves_supported_ascii_acronyms_case_insensitively(
    raw_name: str,
    canonical_name: str,
    loop_code: str,
    loop_name: str,
):
    assert resolve_process_loop(raw_name) == ProcessLoopAssignment(
        process_name=canonical_name,
        loop_code=loop_code,
        loop_name=loop_name,
    )


@pytest.mark.parametrize(
    "raw_name",
    ["多晶硅沉积", "RCA清洗", "氧 化", "unknown"],
)
def test_rejects_aliases_internal_spacing_and_unknown_names(
    raw_name: str,
):
    with pytest.raises(UnknownProcessNameError) as exc_info:
        resolve_process_loop(raw_name)

    assert raw_name in str(exc_info.value)


def test_unknown_error_preserves_the_untrimmed_original_name():
    raw_name = "  unknown  "

    with pytest.raises(UnknownProcessNameError) as exc_info:
        resolve_process_loop(raw_name)

    assert repr(raw_name) in str(exc_info.value)


def test_process_loop_assignment_is_frozen_and_slotted():
    assignment = resolve_process_loop("发料机")

    assert not hasattr(assignment, "__dict__")
    with pytest.raises(FrozenInstanceError):
        assignment.loop_code = "LOOP9"


def test_process_loop_assignment_has_only_the_approved_fields():
    field_names = tuple(
        field.name for field in fields(ProcessLoopAssignment)
    )

    assert field_names == ("process_name", "loop_code", "loop_name")
    assert "sequence" not in field_names
