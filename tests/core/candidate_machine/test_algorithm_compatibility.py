import pytest

import app.core.candidate_machine.product_compatibility as compatibility


@pytest.mark.parametrize(
    (
        "current_spec",
        "target_spec",
        "workshop_code",
        "process_name",
        "expected",
    ),
    [
        ("N", "N", "S1", "丝网", True),
        ("R", "P", "S2", "制绒", True),
        ("P", "R", "S2", "制绒", True),
        ("R", "P", "S2", "丝网", False),
        ("R", "P", "S2", "丝网01", True),
        ("R", "P", "S1", "制绒", False),
        ("N", "P", "S2", "制绒", False),
    ],
)
def test_algorithm_wafer_spec_compatibility_is_exactly_scoped(
    current_spec: str,
    target_spec: str,
    workshop_code: str,
    process_name: str,
    expected: bool,
):
    assert compatibility.is_wafer_spec_compatible(
        current_wafer_spec=current_spec,
        target_wafer_spec=target_spec,
        workshop_code=workshop_code,
        process_name=process_name,
    ) is expected


@pytest.mark.parametrize(
    ("current_grade", "target_grade", "expected"),
    [
        ("A", "A", True),
        ("A", "A-", True),
        ("A-", "A-", True),
        ("A-", "A", False),
        ("", "A", False),
        ("UNKNOWN", "A-", False),
        ("A", "UNKNOWN", False),
    ],
)
def test_source_grade_compatibility_only_allows_equal_or_down_grade(
    current_grade: str,
    target_grade: str,
    expected: bool,
):
    assert compatibility.is_source_grade_compatible(
        current_source_grade=current_grade,
        target_source_grade=target_grade,
    ) is expected
