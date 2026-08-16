# Buffer Bound Source Format Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ignore complete Buffer realtime rows whose first hyphen-delimited product name is not a valid numeric-letter-Chinese product format.

**Architecture:** Add one pure predicate in `app/utils/buffer_binding.py` that combines existing multi-value filtering with the new format check. Replace the three independent boundary checks in Backend Validator, SnapshotAdapter, and MainBufferAggregator so invalid rows cannot affect validation, aggregation, warnings, or errors.

**Tech Stack:** Python 3, regular expressions, Pydantic, pytest

---

### Task 1: Add failing format and boundary tests

**Files:**
- Create: `tests/utils/test_buffer_binding.py`
- Modify: `tests/adapters/test_snapshot_adapter.py`
- Modify: `tests/core/buffer_aggregation/test_main_buffer_aggregator.py`
- Modify: `tests/adapters/test_agv_order_binding_validator.py`

- [ ] **Step 1: Test the pure predicate before implementation**

```python
import pytest

from app.utils import buffer_binding


@pytest.mark.parametrize(
    ("value", "ignored"),
    (
        ("210R公版-退火下-AUTO", False),
        ("210N艺馨-氧化下-AUTO", False),
        ("210R公版2-背膜下-AUTO", False),
        ("天合返洗验证-退火下-AUTO", True),
        ("210公版-退火下-AUTO", True),
        ("210R-退火下-AUTO", True),
        ("R210公版-退火下-AUTO", True),
        ("产品一", True),
        ("Product A", True),
        ("Product A,Product B", True),
    ),
)
def test_should_ignore_bound_source_name(value, ignored):
    assert buffer_binding.should_ignore_bound_source_name(value) is ignored
```

- [ ] **Step 2: Run the pure test and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/utils/test_buffer_binding.py -q
```

Expected: FAIL with `AttributeError` because the new predicate is not implemented.

- [ ] **Step 3: Add boundary assertions**

Use `210N不存在-退火下-AUTO` for the existing unknown-product error tests, and add a `天合返洗验证-退火下-AUTO` case asserting the complete row is absent from validation/snapshot/main aggregation rather than reported as an order mapping error.

### Task 2: Implement and route the shared predicate

**Files:**
- Modify: `app/utils/buffer_binding.py`
- Modify: `app/adapters/backend_request_validator.py`
- Modify: `app/adapters/snapshot_adapter.py`
- Modify: `app/core/buffer_aggregation/main_buffer_aggregator.py`

- [ ] **Step 1: Implement the pure format and combined ignore checks**

```python
import re

_BOUND_SOURCE_PRODUCT_PATTERN = re.compile(
    r"^[0-9]+[A-Za-z]+(?=[0-9A-Za-z\u4e00-\u9fff]*[\u4e00-\u9fff])"
    r"[0-9A-Za-z\u4e00-\u9fff]+$"
)


def is_valid_bound_source_product_name(value: object) -> bool:
    if not isinstance(value, str):
        return False
    product_name = value.strip().split("-", 1)[0].strip()
    return bool(_BOUND_SOURCE_PRODUCT_PATTERN.fullmatch(product_name))


def should_ignore_bound_source_name(value: object) -> bool:
    return is_multi_value_bound_source_name(value) or not is_valid_bound_source_product_name(value)
```

- [ ] **Step 2: Replace each boundary's multi-value-only guard**

In all three consumers, import `should_ignore_bound_source_name` and replace the existing `is_multi_value_bound_source_name(...)` row filter with it. Leave `normalize_bound_source_product_name()` unchanged for valid rows.

- [ ] **Step 3: Run pure and boundary tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/utils/test_buffer_binding.py tests/adapters/test_snapshot_adapter.py tests/core/buffer_aggregation/test_main_buffer_aggregator.py tests/adapters/test_agv_order_binding_validator.py -q
```

Expected: all tests pass after updating old invalid-name fixtures to valid-format names where they are intended to participate.

### Task 3: Verify current request and regressions

**Files:**
- Input: `request-to-cutline-current-format.json`

- [ ] **Step 1: Run the complete test suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

- [ ] **Step 2: Post current request to `/cutline/evaluate`**

Assert HTTP 200, no `order_mapping_not_found` for `31011110`, four full-capacity manual interventions from the earlier fix, and no `pending_cutline_plan_creation_error`.

- [ ] **Step 3: Run `git diff --check` and inspect the final diff**

Confirm no Response Schema or unrelated algorithm changes were introduced.
