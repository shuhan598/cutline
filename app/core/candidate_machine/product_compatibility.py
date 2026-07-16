from __future__ import annotations


SOURCE_GRADE_RANK = {
    "A-": 1,
    "A": 2,
}


def is_wafer_spec_compatible(
    *,
    current_wafer_spec: str,
    target_wafer_spec: str,
    workshop_code: str,
    process_name: str,
) -> bool:
    """Algorithm compatibility helpers."""

    if current_wafer_spec == target_wafer_spec:
        return True
    return (
        workshop_code == "S2"
        and process_name != "\u4e1d\u7f51"
        and {current_wafer_spec, target_wafer_spec} == {"R", "P"}
    )


def is_source_grade_compatible(
    *,
    current_source_grade: str,
    target_source_grade: str,
) -> bool:
    """Algorithm compatibility helpers."""

    if current_source_grade not in SOURCE_GRADE_RANK:
        return False
    if target_source_grade not in SOURCE_GRADE_RANK:
        return False
    return (
        SOURCE_GRADE_RANK[current_source_grade]
        >= SOURCE_GRADE_RANK[target_source_grade]
    )
