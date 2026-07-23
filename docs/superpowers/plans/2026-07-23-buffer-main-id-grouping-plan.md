# Buffer main_id Grouping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development while implementing every behavior change. Execute inline because the user explicitly requested work in the current workspace; do not create a worktree or perform branch integration.

**Goal:** Preserve physical Buffer inventory rows while calculating net rate, depletion, overflow inventory, growth and capacity at deterministic `main_id` group scope.

**Architecture:** SnapshotAdapter validates and preserves physical rows. NetRateCalculator is the single aggregation entrance and emits one order/interval result per `main_id`; downstream depletion and warnings propagate that identity, while OverflowTimeCalculator groups those order results once more by `main_id`. A sorted representative `buffer_code` keeps the existing candidate, plan and event chain compatible without changing public schemas.

**Tech Stack:** Python 3.13, Pydantic 2.x, pytest.

**Git constraint:** Do not run `git add`, `git commit`, `git push`, `git merge`, `git rebase`, `git reset`, `git checkout`, or `git switch`.

---

## Task 1: Drive internal Schema contracts

**Files:**

- Modify: `tests/schemas/test_algorithm_common_schema.py`
- Modify: `tests/schemas/test_algorithm_evaluate_result_schema.py`
- Modify: `app/schemas/common_schema.py`
- Modify: `app/schemas/result_schema.py`

- [ ] Add a failing exact-field test requiring `AlgorithmBufferOrderInventory`
  fields `main_id`, `buffer_code`, `order_code`, `current_quantity`.
- [ ] Add failing construction tests showing `main_id` is required and preserved.
- [ ] Add failing exact-field/construction assertions requiring `main_id` and
  `buffer_codes` on NetRate, Depletion, OverflowTime, StockoutWarning and
  OverflowWarning results.
- [ ] Run:

  ```powershell
  .\.venv\Scripts\python.exe -m pytest -q tests/schemas/test_algorithm_common_schema.py tests/schemas/test_algorithm_evaluate_result_schema.py
  ```

  Expected: failures because the new internal fields do not exist.

- [ ] Add the required fields to the existing models only; do not add a class or
  change `request_schema.py`, `backend_request_schema.py` or
  `response_schema.py`.
- [ ] Update existing direct test constructors with explicit deterministic
  values such as:

  ```python
  main_id="MAIN-01",
  buffer_code="BUF-01",
  buffer_codes=["BUF-01"],
  ```

- [ ] Rerun the focused Schema tests and confirm they pass.

## Task 2: Drive SnapshotAdapter physical-row preservation and validation

**Files:**

- Modify: `tests/adapters/test_snapshot_adapter.py`
- Modify: `app/adapters/snapshot_adapter.py`

- [ ] First update the test payload so every order row for a physical
  `buffer_code` uses the same nonblank `main_id`.
- [ ] Add failing tests for:
  - preserved `main_id`;
  - blank/`None` `main_id`;
  - one `buffer_code` assigned to two `main_id` values;
  - duplicate `(main_id, buffer_code, order_code)`;
  - same main, different physical buffers, same order being accepted;
  - workshop, upstream, downstream and `loop_code` conflicts.
- [ ] Assert conflict messages contain the main ID, both physical codes, field
  name and both actual values.
- [ ] Run:

  ```powershell
  .\.venv\Scripts\python.exe -m pytest -q tests/adapters/test_snapshot_adapter.py
  ```

  Expected: failures because `main_id` is not retained and group validation is
  absent.

- [ ] In `_convert_buffer_order_inventories`, preserve each row as:

  ```python
  AlgorithmBufferOrderInventory(
      main_id=item.main_id,
      buffer_code=item.buffer_code,
      order_code=order.order_code,
      current_quantity=item.current_quantity,
  )
  ```

- [ ] Add local indexes for physical-to-main identity, triple uniqueness and
  main-to-context consistency. Compare `workshop_code`,
  `upstream_process_code`, `downstream_process_code` and master `loop_code`.
- [ ] Keep the existing workshop/name order match unchanged and never mutate the
  request.
- [ ] Rerun the focused Adapter tests and confirm they pass.

## Task 3: Drive NetRate group aggregation

**Files:**

- Modify: `tests/core/net_rate/test_algorithm_net_rate_calculator.py`
- Modify: `app/core/net_rate/net_rate_calculator.py`

- [ ] Update direct inventory constructors to include `main_id`.
- [ ] Add failing tests proving:
  - `3600 + 7200` becomes one result with quantity `10800`;
  - `buffer_codes` is unique and sorted and representative `buffer_code` is the
    smallest code regardless of input order;
  - upstream/downstream rates retain their single-calculation values rather than
    being multiplied by physical layer count;
  - different orders in one main produce separate results;
  - different mains with the same interval remain separate.
- [ ] Wrap the existing upstream/downstream calculation methods in one test to
  count real invocations without mocking the calculator or pipeline; each
  aggregated order group must invoke each method once.
- [ ] Run:

  ```powershell
  .\.venv\Scripts\python.exe -m pytest -q tests/core/net_rate/test_algorithm_net_rate_calculator.py
  ```

  Expected: failures because calculation still iterates physical inventory rows.

- [ ] Add a private grouping method using dictionaries and the existing
  `AlgorithmBufferOrderInventory`; do not create an aggregate class.
- [ ] Resolve each physical relation, form the approved grouping key, sum
  quantities, collect sorted unique codes and choose `buffer_codes[0]`.
- [ ] Iterate groups deterministically and call the unchanged rate functions
  exactly once per group.
- [ ] Populate `main_id` and `buffer_codes` on each result.
- [ ] Rerun the focused NetRate tests and confirm they pass.

## Task 4: Drive Depletion propagation and single-result behavior

**Files:**

- Modify: `tests/core/prediction_time/test_algorithm_depletion_time_calculator.py`
- Modify: `app/core/prediction_time/depletion_time/depletion_time_calculator.py`

- [ ] Update result fixtures with `main_id` and `buffer_codes`.
- [ ] Add a failing test where aggregated quantity `10800` and rate `3600`
  produce one `180` minute result carrying the same group identity.
- [ ] Run the focused test and observe failure from missing propagation.
- [ ] Copy `main_id` and a defensive list copy of `buffer_codes` into the
  existing Depletion result. Leave the formula unchanged.
- [ ] Rerun the focused Depletion tests and confirm they pass.

## Task 5: Drive main-level Overflow calculation

**Files:**

- Modify: `tests/core/prediction_time/test_algorithm_overflow_time_calculator.py`
- Modify: `app/core/prediction_time/overflow_time/overflow_time_calculator.py`

- [ ] Update rate fixtures with group fields.
- [ ] Add failing tests proving:
  - all aggregated order inventories under one main are summed;
  - each order growth rate is counted once;
  - different order growth rates are algebraically summed;
  - capacities of unique physical codes are summed;
  - one physical code appearing for multiple orders contributes capacity once;
  - one main creates one result;
  - different mains sharing an interval create separate results;
  - representative code is the sorted minimum and `buffer_codes` is sorted;
  - no net-rate groups means no empty overflow result.
- [ ] Run:

  ```powershell
  .\.venv\Scripts\python.exe -m pytest -q tests/core/prediction_time/test_algorithm_overflow_time_calculator.py
  ```

  Expected: failures because overflow is still emitted per master
  `buffer_code`.

- [ ] Replace per-master output iteration with per-`main_id` net-rate grouping.
- [ ] Validate participating physical master/relation references and common
  interval context.
- [ ] Sum unique physical master capacities and existing per-order inventory and
  growth details once.
- [ ] Preserve all existing overflow boundary and time formulas.
- [ ] Rerun focused Overflow tests and confirm they pass.

## Task 6: Drive warning identity propagation and de-duplication

**Files:**

- Modify: `tests/core/warning/test_algorithm_stockout_warning.py`
- Modify: `tests/core/warning/test_algorithm_overflow_warning.py`
- Modify: `app/core/warning/stockout_warning.py`
- Modify: `app/core/warning/overflow_warning.py`

- [ ] Update prediction fixtures with group fields.
- [ ] Add failing assertions that warning results preserve `main_id` and sorted
  `buffer_codes`.
- [ ] Add failing tests showing one aggregated order yields one stockout warning
  and one main yields one overflow warning.
- [ ] Change warning uniqueness identities from representative physical code to
  `main_id` plus the existing order/spec/interval dimensions.
- [ ] Copy group fields into warning results without changing warning thresholds
  or sorting semantics.
- [ ] Run both warning directories and confirm green.

## Task 7: Keep candidate, selection, plan and return behavior compatible

**Files:**

- Modify: direct constructors in `tests/core/candidate_machine/`
- Modify: direct constructors in `tests/core/cutline_plan/`
- Modify: direct constructors in `tests/core/return_judge/`
- Verify unchanged unless the representative-code compatibility test fails:
  `app/core/return_judge/return_evaluator.py`

- [ ] Update internal result test builders with `main_id` and
  `buffer_codes=[buffer_code]`.
- [ ] Add/extend a real-chain test proving a multi-layer main produces one
  candidate result, one selection attempt, one plan and one activity event.
- [ ] Verify representative `buffer_code` still resolves the common process
  relation.
- [ ] Run:

  ```powershell
  .\.venv\Scripts\python.exe -m pytest -q tests/core/candidate_machine/ tests/core/cutline_plan/ tests/core/return_judge/
  ```

- [ ] Do not modify candidate filters, ordering, capacity formulas, plan rules or
  return conditions. Only make a minimal lookup compatibility adjustment if the
  failing test proves it necessary.

## Task 8: Update Pipeline fixtures and genuine multi-layer data

**Files:**

- Modify: `tests/service/test_algorithm_pipeline_upper_flow.py`
- Modify: `tests/service/test_algorithm_pipeline_upper_flow.py`
- Modify: `tests/service/test_algorithm_pipeline_complete_flow.py`
- Modify: `tests/service/test_algorithm_pipeline_decision_flow.py`
- Modify: `tests/service/test_cutline_algorithm_service.py`
- Modify: `tests/fixtures/v3_full_route_factory.py`
- Modify: `tests/integration/test_v3_*.py`
- Add or modify a real-chain grouping test under `tests/integration/`

- [ ] Make fixture `main_id` independent of order:

  ```text
  one physical buffer_code → one main_id
  multiple orders in that buffer_code → the same main_id
  ```

- [ ] Add a genuine same-main two-layer case with quantities `3600` and `7200`,
  equal workshop/upstream/downstream/loop, independent capacities and at least
  one additional order.
- [ ] Add failing real Pipeline assertions for aggregated quantity, one rate,
  one depletion/warning, one overflow/warning and deterministic representative.
- [ ] Keep no-warning, stockout, overflow, return, silk and mixing expected
  business outcomes unchanged.
- [ ] Run service and integration tests and make only fixture/assertion changes
  needed by the approved semantics.

## Task 9: Preserve the public response and regenerate examples

**Files:**

- Verify unchanged: `app/schemas/request_schema.py`
- Verify unchanged: `app/schemas/backend_request_schema.py`
- Verify unchanged: `app/schemas/response_schema.py`
- Verify behavior: `app/mappers/algorithm_response_mapper.py`
- Verify generator: `examples/generate_v3_scenarios.py`
- Regenerate: `examples/*.json`
- Regenerate: `examples/scenarios/*.json`
- Regenerate: `debug_outputs/*.json`
- Modify: `tests/schemas/test_cutline_algorithm_response.py`
- Modify: `tests/mappers/test_algorithm_response_mapper.py`
- Modify: `tests/test_current_examples.py`

- [ ] Add or retain exact public field-set assertions proving neither
  `main_id` nor `buffer_codes` is emitted.
- [ ] Regenerate committed JSON from the shared factory after it uses valid
  group IDs.
- [ ] Confirm response warning IDs and plan/event payloads use only the
  deterministic representative `buffer_code`.
- [ ] Run example and public response tests.

## Task 10: Required verification

- [ ] Run in order:

  ```powershell
  .\.venv\Scripts\python.exe -m pytest -q tests/schemas/
  .\.venv\Scripts\python.exe -m pytest -q tests/adapters/
  .\.venv\Scripts\python.exe -m pytest -q tests/core/net_rate/
  .\.venv\Scripts\python.exe -m pytest -q tests/core/prediction_time/
  .\.venv\Scripts\python.exe -m pytest -q tests/core/warning/
  .\.venv\Scripts\python.exe -m pytest -q tests/core/candidate_machine/
  .\.venv\Scripts\python.exe -m pytest -q tests/service/
  .\.venv\Scripts\python.exe -m pytest -q tests/integration/
  .\.venv\Scripts\python.exe -m pytest -q
  .\.venv\Scripts\python.exe -m compileall -q app tests examples
  git diff --check
  git status
  ```

- [ ] Inspect `git diff` to confirm:
  - no AGV behavior change;
  - no external request or response Schema change;
  - no candidate, plan, return, silk or mixing formula/rule change;
  - no aggregate inventory class;
  - no mutating Git command was executed.

## Task 11: Final report

Report the requested modification files, grouping key, field responsibilities,
representative rule, internal propagation, formula-preserving aggregation,
empty-realtime boundary, test/compile/diff/status evidence, and explicit
confirmation that `git add`, `git commit` and `git push` were not executed.
