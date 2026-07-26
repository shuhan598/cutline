# Machine Workshop Route Source Implementation Plan

> **For Codex:** Execute in the current workspace without commits, pushes, branch
> switches, or worktrees. Follow test-driven development: add each regression,
> confirm it fails for the expected reason, then implement the smallest change.

**Goal:** Make process routes the sole authority for a machine's workshop while
preserving line compatibility, AGV production identity, formulas, and result contracts.

**Architecture:** Add a shared `MachineWorkshopResolver`, validate runtime-participating
machines in `SnapshotAdapter`, and inject the same resolver rules into net rate,
candidate, and silk-screen contexts. Preserve module-specific exception types by
translating the resolver error at each boundary.

**Tech Stack:** Python 3.13, Pydantic 2, FastAPI, pytest.

---

### Task 1: Add resolver contract tests

**Files:**
- Create: `tests/core/workshop/test_machine_workshop_resolver.py`
- Create: `app/core/workshop/__init__.py`
- Create: `app/core/workshop/machine_workshop_resolver.py`

**Steps:**
1. Add tests for one route, duplicate process across loops in the same workshop,
   stable cross-workshop conflict errors, missing process errors, and machine-context
   errors containing machine and process codes.
2. Run the new test file and confirm import/behavior failures.
3. Implement the minimal resolver and error class.
4. Run the new test file to green.

### Task 2: Add SnapshotAdapter participation validation

**Files:**
- Modify: `tests/adapters/test_snapshot_adapter.py`
- Modify: `app/adapters/snapshot_adapter.py`

**Steps:**
1. Add failing tests for runtime machine missing a route, cross-workshop conflicts,
   same-workshop duplicate routes, and unused static machine missing a route.
2. Confirm failures occur because Adapter lacks the new validation.
3. Construct the shared resolver after route conversion, validate only machines
   referenced by converted runtimes, and translate errors to `SnapshotConversionError`.
4. Run Adapter tests to green.

### Task 3: Switch net-rate workshop authority

**Files:**
- Modify: `tests/core/net_rate/test_algorithm_net_rate_calculator.py`
- Modify: `app/core/net_rate/net_rate_calculator.py`

**Steps:**
1. Extend the test factory with process routes.
2. Add line-versus-route positive and negative tests plus missing/conflict error tests.
3. Confirm new assertions fail against line-based matching.
4. Add the resolver to `_AlgorithmNetRateContext`, translate its errors, and replace
   line workshop reads in `_matching_runtimes`.
5. Run net-rate tests, including existing `main_id` and AGV regressions.

### Task 4: Switch candidate workshop authority

**Files:**
- Modify: `tests/core/candidate_machine/helpers.py`
- Modify: `tests/core/candidate_machine/test_candidate_context.py`
- Modify: `tests/core/candidate_machine/test_algorithm_stockout_candidate_finder.py`
- Modify: `tests/core/candidate_machine/test_algorithm_overflow_candidate_finder.py`
- Modify: `app/core/candidate_machine/candidate_context.py`
- Modify: `app/core/candidate_machine/stockout_candidate_finder.py`
- Modify: `app/core/candidate_machine/overflow_candidate_finder.py`

**Steps:**
1. Add route helpers and default routes to the shared candidate snapshot.
2. Add CandidateContext resolver/error tests.
3. Add stockout and overflow line-versus-route tests.
4. Add S2 R/P positive and inverse negative tests driven by route workshop.
5. Confirm failures prove current dependence on `line.workshop_code`.
6. Implement `machine_workshop_code()` and replace finder comparison,
   compatibility, and result workshop reads.
7. Run all candidate tests to green.

### Task 5: Switch silk-screen workshop authority

**Files:**
- Modify: `tests/core/silk_screen/test_order_transition_planner.py`
- Modify: `tests/integration/test_v3_silk_screen_flow.py`
- Modify: `app/core/silk_screen/order_transition_planner.py`

**Steps:**
1. Add process-route fixtures to silk unit snapshots.
2. Change the existing cross-workshop test to use distinct process codes because a
   single process code may no longer span workshops.
3. Add a line-versus-route regression and resolver error tests.
4. Confirm failures.
5. Resolve workshop through the shared resolver while preserving line relation checks.
6. Run silk unit and integration tests to green.

### Task 6: Add real-service regression and update shared examples

**Files:**
- Modify: `tests/api/test_fastapi_interfaces.py`
- Modify as needed: `tests/fixtures/v3_full_route_factory.py`
- Regenerate if factory changes: `examples/scenarios/*.json`

**Steps:**
1. Add a non-mock `/cutline/evaluate` test that changes the candidate line workshop
   away from the route workshop and proves the route workshop still selects it.
2. Confirm failure before implementation or by reverting the relevant production change.
3. Run API, integration, example, and fake-data contract tests.
4. Regenerate deterministic scenarios only if shared factory data requires changes.

### Task 7: Audit and document field authority

**Files:**
- Modify: `README.md`
- Modify: `docs/backend-request-interface.md`
- Modify: `docs/2026-07-14-algo-request-document-field-mapping.md`
- Modify: `docs/superpowers/specs/2026-07-26-agv-wafer-spec-source-design.md`
- Create: `docs/backend-field-source-mapping.md`

**Steps:**
1. Search all production uses of `line.workshop_code`, machine-line indices, and
   machine contexts.
2. Confirm no core use remains where line workshop expresses machine ownership.
3. Document the new route chain and retained line compatibility.
4. Document conflict, missing-route, and runtime participation validation behavior.

### Task 8: Review and final verification

**Steps:**
1. Review the complete diff against every approved requirement.
2. Run a specification compliance review, then a code quality review.
3. Fix all critical or important findings and rerun affected tests.
4. Execute exactly:

```powershell
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\python.exe -m compileall -q app tests examples
git diff --check
```

5. Report changed files, resolver call sites, validation scope, removed core line
   workshop reads, retained compatibility, tests, exact command results, and any gaps.
