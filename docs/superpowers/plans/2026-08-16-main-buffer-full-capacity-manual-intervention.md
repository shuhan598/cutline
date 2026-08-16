# Main Buffer Full Capacity Manual Intervention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure a physical main Buffer at or above capacity produces manual intervention even when its aggregate growth rate is zero or negative.

**Architecture:** Keep the correction inside `MachineSelectionEvaluator._physical_main_resolved()`, where physical capacity and projected rates are already available. Preserve downstream contracts so the existing failure-reason and plan-building branches produce `current_buffer_already_over_capacity` and `manual_intervention` without response changes.

**Tech Stack:** Python 3, Pydantic, pytest

---

### Task 1: Lock the physical-main full-capacity behavior

**Files:**
- Modify: `tests/core/cutline_plan/test_machine_selection_evaluator_overflow.py`

- [ ] **Step 1: Write the failing regression test**

```python
@pytest.mark.parametrize(
    ("source_inventory", "source_rate"),
    ((1100, 0), (1200, 100), (1200, -100)),
)
def test_batch_at_or_over_capacity_builds_manual_intervention(
    source_inventory,
    source_rate,
):
    snapshot_value, warning, intervals, source, targets = _batch_context(
        source_rate=source_rate,
        source_inventory=source_inventory,
        source_capacity=1100,
        targets=(("ORD-TARGET", "BUF-TARGET", 0, 3900, 3900),),
    )
    selection = _select(
        _batch_candidates(source, targets),
        snapshot_value=snapshot_value,
        warning=warning,
        intervals=intervals,
        overflows=[],
    )

    decision = CutlinePlanBuilder().build_overflow_decision(
        snapshot_value,
        warning,
        selection,
    )

    assert selection.selected_machines == []
    assert selection.risk_resolved is False
    assert selection.failure_reason == "current_buffer_already_over_capacity"
    assert decision.plan is None
    assert decision.manual_intervention is not None
    assert (
        decision.manual_intervention.reason
        == "current_buffer_already_over_capacity"
    )
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/cutline_plan/test_machine_selection_evaluator_overflow.py::test_batch_at_or_over_capacity_builds_manual_intervention -q
```

Expected before implementation: three failures because the current batch path returns `risk_resolved=True` and builds an empty automatic plan.

### Task 2: Apply capacity-first risk resolution

**Files:**
- Modify: `app/core/cutline_plan/machine_selection_evaluator.py:1587`
- Test: `tests/core/cutline_plan/test_machine_selection_evaluator_overflow.py`

- [ ] **Step 1: Implement the minimal capacity guard**

```python
def _physical_main_resolved(self, snapshot, main_id, virtual_groups, batch):
    physical = self._physical_state(batch, main_id)
    if (
        physical is not None
        and physical.total_capacity is not None
        and physical.total_inventory >= physical.total_capacity
    ):
        return False
    total_rate = sum(
        state.inventory_change_rate for state in virtual_groups.values()
    )
    minutes = self._physical_overflow_minutes(physical, total_rate)
    return total_rate <= 0 or (
        minutes is not None
        and minutes > snapshot.config.overflow_warning_lead_minutes
    )
```

- [ ] **Step 2: Run the regression test and verify GREEN**

Run the Task 1 command.

Expected: `1 passed`.

- [ ] **Step 3: Run cutline-plan regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/cutline_plan/test_machine_selection_evaluator_overflow.py tests/core/cutline_plan/test_plan_builder.py -q
```

Expected: all tests pass.

### Task 3: Verify pipeline and real request behavior

**Files:**
- Test: `tests/service/test_algorithm_pipeline_decision_flow.py`
- Input: `request-to-cutline-current-format.json`

- [ ] **Step 1: Run the existing pipeline decision contract**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/service/test_algorithm_pipeline_decision_flow.py -q
```

Expected: all tests pass, including overflow-without-candidates producing manual intervention without a pipeline error.

- [ ] **Step 2: Evaluate the current JSON through `/cutline/evaluate`**

Use FastAPI `TestClient` to post `request-to-cutline-current-format.json` and assert:

```python
assert response.status_code == 200
assert len(body["overflow_warnings"]) == 4
assert len(body["cutline_decisions"]) == 4
assert all("manual_intervention" in item for item in body["cutline_decisions"])
assert not any(
    error["reason"] == "pending_cutline_plan_creation_error"
    for error in body["errors"]
)
```

Expected: four manual decisions and no empty-plan Pending creation errors.

- [ ] **Step 3: Run the broader relevant suite**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/cutline_plan tests/service/test_algorithm_pipeline_decision_flow.py tests/integration/test_v3_overflow_flow.py -q
```

Expected: all tests pass.
