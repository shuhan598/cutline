# Ignore Multi-Value Buffer Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Silently exclude a complete `buffer_realtime` record when `bound_source_name` contains at least two non-empty ASCII-comma-separated values.

**Architecture:** Add one pure predicate in `app.utils` and call it at every boundary that interprets Buffer realtime bindings. Filter before validation, snapshot inventory conversion, and physical main aggregation so ignored records cannot affect inventory, capacity, warnings, or errors.

**Tech Stack:** Python 3.13, Pydantic, pytest, Pyright

---

### Task 1: Lock the behavior with failing regression tests

**Files:**
- Modify: `tests/core/buffer_aggregation/test_main_buffer_aggregator.py`
- Modify: `tests/adapters/test_snapshot_adapter.py`
- Modify: `tests/adapters/test_agv_order_binding_validator.py`

- [ ] Add a core test with one valid row and one comma-separated row in another main. Assert that only the valid main is present and `batch.issues` is empty.
- [ ] Add a snapshot test that sets one row to `"Product A,Product B"`. Assert that its Buffer inventory and physical main state are absent and no aggregation issue references it.
- [ ] Add a validator test asserting that the same record produces no `bound_source_name` issue.
- [ ] Run the three new tests and confirm the core test fails because the ignored row currently creates `order_mapping_not_found`.

### Task 2: Add the shared predicate and apply it

**Files:**
- Create: `app/utils/buffer_binding.py`
- Modify: `app/adapters/backend_request_validator.py`
- Modify: `app/adapters/snapshot_adapter.py`
- Modify: `app/core/buffer_aggregation/main_buffer_aggregator.py`

- [ ] Add `is_multi_value_bound_source_name(value: object) -> bool`, splitting only strings on ASCII comma and returning true when at least two trimmed components are non-empty. Add a Chinese docstring explaining the temporary compatibility rule.
- [ ] In Validator, continue before blank and order mapping checks when the predicate is true.
- [ ] In SnapshotAdapter, continue before resolving the order and constructing inventory when the predicate is true.
- [ ] In MainBufferAggregator, exclude matching rows before grouping by `main_id`; add a short Chinese comment explaining that the whole realtime row is ignored.
- [ ] Run the focused tests and confirm they pass.

### Task 3: Regression verification

**Files:**
- No additional file changes.

- [ ] Run all adapter and aggregation tests.
- [ ] Run the complete `pytest` suite.
- [ ] Run Pyright with the project virtual environment.
- [ ] Run `python -m compileall -q app tests examples`.
- [ ] Run `git diff --check` and inspect `git status --short`.
- [ ] Do not run `git add`, `git commit`, or `git push`.
