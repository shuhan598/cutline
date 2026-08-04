# Main Buffer Aggregation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and superpowers:test-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace single-layer Buffer calculations with one shared, capability-aware `MainBufferAggregationBatch` while preserving every formal request, response, persistence, and round-trip field.

**Architecture:** `SnapshotAdapter` performs existing global conversion, then invokes one centralized `MainBufferAggregator`. The resulting immutable group batch is stored on `AlgorithmSnapshot` and consumed by NetRate, warning, candidate, selection, and round-trip lookup code without re-aggregation. Pipeline maps aggregation issues once into the existing `AlgorithmPipelineError` schema.

**Tech Stack:** Python 3.13, Pydantic 2.x, dataclasses, pytest.

**Git constraint:** Do not run `git add`, `git commit`, `git push`, `git reset`, `git clean`, `git checkout -- .`, or `git restore .`.

---

## File Structure

- Create `app/core/buffer_aggregation/models.py`: frozen keys, groups, issues, batch indexes, and capability helpers.
- Create `app/core/buffer_aggregation/main_buffer_aggregator.py`: the only mainID grouping and two-pass validation implementation.
- Create `tests/core/buffer_aggregation/test_main_buffer_aggregator.py`: focused group, issue, index, and capability tests.
- Modify `app/adapters/snapshot_adapter.py`: invoke the aggregator once after base conversion and preserve valid physical inventory rows.
- Modify `app/adapters/backend_request_validator.py`: leave structural validation intact while routing group-local static Buffer association failures to the aggregator.
- Modify `app/schemas/request_schema.py`: add only the internal batch field on `AlgorithmSnapshot`; do not change formal request fields or types.
- Modify `app/schemas/result_schema.py`: add internal `GroupKey` and receiver/donor/target locator fields where required; do not change response models.
- Modify NetRate, prediction, warning, candidate, selection, Pipeline, and minimal Pending/return lookup modules to consume the shared batch.
- Modify focused tests, integration fixtures, API contract tests, and response snapshots in place.

## Task 1: Internal Group Models and First-Pass Aggregator

**Files:**

- Create: `app/core/buffer_aggregation/__init__.py`
- Create: `app/core/buffer_aggregation/models.py`
- Create: `app/core/buffer_aggregation/main_buffer_aggregator.py`
- Create: `tests/core/buffer_aggregation/__init__.py`
- Create: `tests/core/buffer_aggregation/test_main_buffer_aggregator.py`

- [ ] **Step 1: Write failing model and first-pass tests**

Add exact tests named `test_one_main_sums_unique_layer_inventory_and_capacity`,
`test_zero_inventory_is_valid`,
`test_duplicate_realtime_buffer_invalidates_group_without_double_counting`,
`test_representative_code_is_stable_sorted_real_layer`,
`test_static_mapping_unresolved_disables_all_six_capabilities`,
`test_capacity_unavailable_keeps_stockout_and_donor_capabilities_only`,
`test_same_main_order_workshop_and_ordered_process_conflicts_are_isolated`,
`test_issue_deduplication_lists_all_related_buffer_codes`, and
`test_index_conflict_never_overwrites_first_group`. Each assertion must inspect
the concrete `MainBufferGroup`, capability flags, issue fields, and batch index
contents rather than only asserting list lengths.

- [ ] **Step 2: Run tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/core/buffer_aggregation/test_main_buffer_aggregator.py
```

Expected: collection fails because `app.core.buffer_aggregation` does not exist.

- [ ] **Step 3: Implement frozen keys and batch models**

Use explicit types equivalent to:

```python
@dataclass(frozen=True, order=True)
class PhysicalBufferKey:
    workshop_code: str
    ordered_service_process_codes: tuple[str, ...]

@dataclass(frozen=True, order=True)
class GroupKey:
    physical_buffer_key: PhysicalBufferKey
    main_id: str
    order_code: str

@dataclass(frozen=True)
class MainBufferAggregationIssue:
    code: str
    main_id: str
    representative_buffer_code: str | None
    message: str
    affected_capabilities: tuple[str, ...]
```

Define `MainBufferGroup` with all six capability flags and `MainBufferAggregationBatch` with authoritative `groups_by_group_key`, tuple-valued multi-indexes, and conflict-safe lookup methods.

- [ ] **Step 4: Implement the minimal first-pass aggregator**

Expose one `MainBufferAggregator.aggregate` entry point accepting keyword-only
`realtime_buffers: Iterable[BufferRealtimeView]`,
`buffer_masters: Iterable[BufferMasterView]`,
`buffer_relations: Iterable[BufferRelationView]`, and
`orders: Iterable[OrderView]`, returning `MainBufferAggregationBatch`.

Group by `main_id`, normalize codes with `strip()`, resolve one order, preserve ordered process tuples, sum each realtime/static layer once, and aggregate issues by `(code, main_id)` before finalizing indexes.

- [ ] **Step 5: Run focused tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/core/buffer_aggregation/test_main_buffer_aggregator.py
```

Expected: all Task 1 tests pass.

## Task 2: Second-Pass Cross-main Validation and Full-capacity Boundary

**Files:**

- Modify: `app/core/buffer_aggregation/main_buffer_aggregator.py`
- Modify: `app/core/buffer_aggregation/models.py`
- Test: `tests/core/buffer_aggregation/test_main_buffer_aggregator.py`

- [ ] **Step 1: Write failing second-pass and capacity-boundary tests**

Add exact tests named
`test_same_physical_key_and_order_on_multiple_mains_disables_each_group`,
`test_cross_main_conflict_emits_one_issue_per_main_listing_all_main_ids`,
`test_process_order_and_workshop_are_part_of_physical_key`,
`test_inventory_equal_capacity_keeps_overflow_source_but_disables_receive`, and
`test_inventory_over_capacity_has_zero_minutes_capability_and_issue`.

- [ ] **Step 2: Run the new tests and verify RED**

Run the five node IDs with `-q`; expect capability or issue assertions to fail.

- [ ] **Step 3: Implement second-pass validation**

Index successful first-pass groups by `(physical_buffer_key, order_code)`. For collisions, create one issue per `main_id`, list all conflicting mains in each message, disable all six capabilities, and rebuild all indexes without silent overwrite.

For `total_inventory >= total_capacity`, preserve overflow source capabilities, set `auto_receive_eligible=False`, and emit a distinct over-capacity issue without treating the group as structurally invalid.

- [ ] **Step 4: Run all aggregator tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/core/buffer_aggregation/
```

## Task 3: Snapshot Integration and Pipeline Issue Mapping

**Files:**

- Modify: `app/adapters/snapshot_adapter.py`
- Modify: `app/adapters/backend_request_validator.py`
- Modify: `app/schemas/request_schema.py`
- Modify: `app/service/cutline_pipeline.py`
- Test: `tests/adapters/test_snapshot_adapter.py`
- Test: `tests/adapters/test_backend_request_validator.py`
- Test: `tests/service/test_algorithm_pipeline_upper_flow.py`
- Test: `tests/api/test_fastapi_interfaces.py`

- [ ] **Step 1: Write failing integration tests**

Cover exactly one aggregator invocation, `AlgorithmSnapshot.main_buffer_batch`, valid-row preservation, local main failure returning HTTP 200, all groups invalid returning HTTP 200, top-level/schema/global-route failure remaining HTTP 422, and issue mapping:

```python
assert error.stage == "main_buffer_aggregation"
assert error.warning_type is None
assert error.warning_key == main_id
assert error.reason == issue_code
```

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/adapters/test_snapshot_adapter.py tests/service/test_algorithm_pipeline_upper_flow.py tests/api/test_fastapi_interfaces.py
```

- [ ] **Step 3: Integrate the batch without changing formal schemas**

Add only an internal `main_buffer_batch` field to `AlgorithmSnapshot`, with an empty-batch default for direct unit fixtures. Move group-local order, duplicate layer, workshop, process-list, and static association failures out of Adapter-wide exceptions. Keep request field definitions, types, nullability, route validation, and global reference errors unchanged.

Pipeline initializes `errors` from a single deduplicated batch issue mapping before other stages; downstream independent errors remain unchanged.

- [ ] **Step 4: Run adapter, service, and API tests and verify GREEN**

Use the Step 2 command and `tests/adapters/test_backend_request_validator.py`.

## Task 4: Shared NetRate, Depletion, and Warning Results

**Files:**

- Modify: `app/core/net_rate/net_rate_calculator.py`
- Modify: `app/core/prediction_time/depletion_time/depletion_time_calculator.py`
- Modify: `app/core/prediction_time/overflow_time/overflow_time_calculator.py`
- Modify: `app/core/warning/stockout_warning.py`
- Modify: `app/core/warning/overflow_warning.py`
- Modify: `app/schemas/result_schema.py`
- Test: `tests/core/net_rate/test_algorithm_net_rate_calculator.py`
- Test: `tests/core/prediction_time/test_algorithm_depletion_time_calculator.py`
- Test: `tests/core/prediction_time/test_algorithm_overflow_time_calculator.py`
- Test: `tests/core/warning/test_algorithm_stockout_warning.py`
- Test: `tests/core/warning/test_algorithm_overflow_warning.py`

- [ ] **Step 1: Write failing shared-batch calculation tests**

Test one rate call per eligible group, signed `inventory_change_rate`, aggregated depletion, one warning per group, summed layer capacity, zero overflow minutes at/over capacity, no overflow result for capacity-unavailable groups, and single-layer compatibility.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/core/net_rate/ tests/core/prediction_time/ tests/core/warning/
```

- [ ] **Step 3: Replace downstream aggregation with batch consumption**

NetRate iterates `snapshot.main_buffer_batch.groups_by_group_key` filtered by `stockout_eligible`, calculates machine rates once, and emits existing result fields from the group. OverflowTime reads the same rate/group key and `overflow_eligible`; it never rescans masters or inventories. Depletion and warning evaluators remain formula/threshold consumers and preserve representative codes only in compatibility fields.

- [ ] **Step 4: Run focused tests and verify GREEN**

Use the Step 2 command.

## Task 5: Stockout Receiver/Donor Candidates and Per-warning Selection

**Files:**

- Modify: `app/core/candidate_machine/candidate_context.py`
- Modify: `app/core/candidate_machine/stockout_candidate_finder.py`
- Modify: `app/core/cutline_plan/machine_selection_evaluator.py`
- Modify: `app/schemas/result_schema.py`
- Test: `tests/core/candidate_machine/test_algorithm_stockout_candidate_finder.py`
- Test: `tests/core/cutline_plan/test_machine_selection_evaluator_stockout.py`
- Test: `tests/service/test_algorithm_pipeline_decision_flow.py`

- [ ] **Step 1: Write failing stockout TDD cases**

Cover unique `receiver_group_key`/`donor_group_key`/`donor_main_id`, donor aggregate inventory, receiver `+R`, donor `-R`, one-machine strict improvement, multi-machine cumulative resolution, donor depletion protection, receiver overflow protection, per-warning state isolation, duplicate-machine rejection, capacity-unavailable receiver candidates plus forced manual result, and no Pending.

- [ ] **Step 2: Run stockout tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/core/candidate_machine/test_algorithm_stockout_candidate_finder.py tests/core/cutline_plan/test_machine_selection_evaluator_stockout.py tests/service/test_algorithm_pipeline_decision_flow.py
```

- [ ] **Step 3: Implement stockout group location and virtual state**

Locate donor by `(receiver.physical_buffer_key, donor_order_code)` through batch indexes. Add internal locator fields only. For each warning create fresh `dict[GroupKey, VirtualGroupState]` and `set[str]`; maintain only mutable `inventory_change_rate` plus read-only inventory/capacity. Apply an individual machine to virtual state when receiver risk strictly improves and bilateral safety checks pass. Mark final risk resolved only when receiver rate is nonnegative or depletion reaches the configured lead.

When `auto_receive_eligible=False`, preserve candidates but return an unresolved selection so existing PlanBuilder creates ManualIntervention and Pending factory sees no plan.

- [ ] **Step 4: Run stockout tests and verify GREEN**

Use the Step 2 command.

## Task 6: Overflow Group Targets and Per-warning Selection

**Files:**

- Modify: `app/core/candidate_machine/overflow_candidate_finder.py`
- Modify: `app/core/cutline_plan/machine_selection_evaluator.py`
- Modify: `app/schemas/result_schema.py`
- Test: `tests/core/candidate_machine/test_algorithm_overflow_candidate_finder.py`
- Test: `tests/core/cutline_plan/test_machine_selection_evaluator_overflow.py`
- Test: `tests/integration/test_v3_overflow_flow.py`

- [ ] **Step 1: Write failing overflow target and selection tests**

Test targets from `group_keys_by_physical_buffer_key`, exclusion of same group/main/order/process-order/workshop/non-receiver groups, proof that warning growth details are not the target source, existing compatibility filters, source `-R`, target `+R`, strict per-machine improvement, multi-machine final resolution, source depletion protection, target gap improvement, target overflow protection, distinct target state keys, machine deduplication, and manual/no Pending when unresolved.

- [ ] **Step 2: Run overflow tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/core/candidate_machine/test_algorithm_overflow_candidate_finder.py tests/core/cutline_plan/test_machine_selection_evaluator_overflow.py tests/integration/test_v3_overflow_flow.py
```

- [ ] **Step 3: Implement shared-batch overflow flow**

Require `source_group.auto_donate_eligible`. Enumerate target `GroupKey` values only from the source physical-key index, attach target keys to internal options, and retain existing machine/product sorting and compatibility. Use a fresh virtual state per warning and finalize only when source growth is nonpositive or overflow time is outside the configured lead.

- [ ] **Step 4: Run overflow tests and verify GREEN**

Use the Step 2 command.

## Task 7: Full-layer Round-trip Lookup

**Files:**

- Modify minimally: `app/core/cutline_confirmation/pending_cutline_detector.py`
- Modify minimally: `app/core/return_judge/return_evaluator.py`
- Modify only if required: `app/adapters/pending_cutline_plan_adapter.py`
- Modify only if required: `app/core/cutline_confirmation/pending_cutline_plan_factory.py`
- Test: `tests/core/cutline_confirmation/test_pending_cutline_detector.py`
- Test: `tests/core/return_judge/test_algorithm_return_evaluator.py`
- Test: `tests/integration/test_v3_pending_cutline_flow.py`
- Test: `tests/integration/test_v3_return_flow.py`

- [ ] **Step 1: Write failing arbitrary-layer lookup tests**

Test that a persisted code which is no longer the representative still resolves through `group_key_by_buffer_code`; missing/conflicting codes never use prefix guesses or silent first-match behavior; Pending/Active structures remain byte-for-field compatible.

- [ ] **Step 2: Run focused round-trip tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/core/cutline_confirmation/ tests/core/return_judge/ tests/integration/test_v3_pending_cutline_flow.py tests/integration/test_v3_return_flow.py
```

- [ ] **Step 3: Make minimal lookup substitutions**

Replace representative-only interval matching at existing locator boundaries with:

```text
buffer_code -> batch.group_key_by_buffer_code -> batch.groups_by_group_key
```

Keep Pending, Active, transition, mixing, return, and persistence models unchanged. Unresolved lookup blocks only the dependent transition and uses the existing error path.

- [ ] **Step 4: Run focused round-trip tests and verify GREEN**

Use the Step 2 command.

## Task 8: Public Contract, Integration, and Regression Coverage

**Files:**

- Modify: `tests/fixtures/v3_full_route_factory.py`
- Modify: `tests/integration/test_v3_buffer_main_id_grouping.py`
- Modify: `tests/service/test_algorithm_pipeline_complete_flow.py`
- Modify: `tests/schemas/test_cutline_algorithm_request_schema.py`
- Modify: `tests/schemas/test_cutline_algorithm_response.py`
- Modify: `tests/mappers/test_algorithm_response_mapper.py`
- Modify: `tests/api/test_fastapi_interfaces.py`
- Verify unchanged: `app/schemas/backend_request_schema.py`
- Verify unchanged: `app/schemas/response_schema.py`
- Verify unchanged: `app/mappers/algorithm_response_mapper.py`
- Verify unchanged: `app/api/`

- [ ] **Step 1: Add failing full-flow and exact-field tests**

Cover one physical Buffer with multiple main groups/orders, one main with multiple layers, correct source/target representative fields, all-invalid HTTP 200 errors, request field/type/nullability snapshots, response/Warning/Decision/SelectedMachine/Pending/Active/persistence field snapshots, Mapper nesting, and OpenAPI response schemas.

- [ ] **Step 2: Run integration and contract tests**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/integration/ tests/service/ tests/schemas/ tests/mappers/ tests/api/
```

Expected before fixture/integration completion: new assertions fail; existing public-field assertions remain green.

- [ ] **Step 3: Make only fixture and internal propagation adjustments**

Do not change formal schema or mapper fields. Update V3 grouping data so one main has one order and different mains share a physical key when appropriate. Preserve existing single-layer, S2 P/R, confirmation, Active, mixing, silk, return, and persistence outcomes.

- [ ] **Step 4: Run integration and contract tests and verify GREEN**

Use the Step 2 command.

## Task 9: Required Verification and Final Audit

- [ ] **Step 1: Run all focused suites in required order**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/core/buffer_aggregation/
.\.venv\Scripts\python.exe -m pytest -q tests/core/net_rate/
.\.venv\Scripts\python.exe -m pytest -q tests/core/prediction_time/ tests/core/warning/
.\.venv\Scripts\python.exe -m pytest -q tests/core/candidate_machine/ tests/core/cutline_plan/
.\.venv\Scripts\python.exe -m pytest -q tests/service/ tests/integration/
.\.venv\Scripts\python.exe -m pytest -q tests/core/cutline_confirmation/ tests/core/return_judge/ tests/core/mixing_trace/ tests/core/silk_screen/
.\.venv\Scripts\python.exe -m pytest -q tests/api/
```

- [ ] **Step 2: Run complete verification**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q app tests examples
git diff --check
git status --short
git diff --stat
git diff --name-only
```

Expected: test count is at least 1515 and higher after added tests; compile and diff checks exit 0.

- [ ] **Step 3: Audit protected paths and pre-existing files**

```powershell
git diff -- app/schemas/request_schema.py
git diff -- app/schemas/response_schema.py
git diff -- app/mappers/algorithm_response_mapper.py
git diff -- app/api
```

Any `request_schema.py` diff must contain only the internal `AlgorithmSnapshot.main_buffer_batch` addition, never formal request field/type/nullability changes. Response Schema, Mapper output fields, API hierarchy, Pending/Active public fields, persistence state, and the two task-preexisting untracked documents must remain unchanged.

- [ ] **Step 4: Prepare the required detailed report**

Report branch/HEAD, pre-task status, call chain, files and responsibilities, group structures/indexes, both validation passes, capability matrix, issue mapping, before/after stockout and overflow behavior, virtual-state keys, round-trip lookup, tests, exact command results, protected-schema diffs, historical issues, and explicit confirmation that commit/push were not executed.
