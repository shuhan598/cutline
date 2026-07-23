# AGV Current Order Binding Implementation Plan

> **Execution rule:** Follow strict TDD. For every behavior change, add or update the smallest test first, run it and observe the expected failure, then make the minimum production change and rerun the focused test.

**Goal:** Remove orders from external machine realtime records and derive `AlgorithmMachineRuntime.current_order_code` from the latest effective AGV binding while preserving all core algorithm and response behavior.

**Architecture:** Keep the backend raw contract and algorithm standard contract separate. Centralize all raw-to-standard AGV mapping in `BackendRequestLoader`. Make both calculation routes and `/backend/validate` pass through that normalization. Let `SnapshotAdapter` select and validate effective standard bindings.

**Tech stack:** Python 3.13, Pydantic 2.x, FastAPI, pytest.

**Git constraint:** Do not run any mutating Git command and do not commit.

---

## Task 1: Prepare the declared test environment

**Files:**

- Read: `requirements.txt`

**Steps:**

1. Create an ignored local virtual environment.
2. Install `requirements.txt`; if FastAPI TestClient exposes a missing optional
   HTTP client, use the installed package metadata's compatible constraint
   rather than changing FastAPI versions.
3. Record Python, Pydantic, FastAPI and pytest versions.
4. Run the unchanged baseline test command and distinguish dependency failures from code failures.

## Task 2: Drive the three contract changes with Schema tests

**Files:**

- Modify: `tests/schemas/test_backend_request_schema.py`
- Modify: `tests/schemas/test_cutline_algorithm_request_schema.py`
- Modify: `tests/schemas/test_algorithm_common_schema.py`
- Modify: `app/schemas/backend_request_schema.py`
- Modify: `app/schemas/request_schema.py`
- Modify: `app/schemas/common_schema.py`

**Red tests:**

1. `BackendMachineRealtime` accepts no `order_code` and rejects it as extra.
2. `MachineRealtimeRequest` accepts no `order_code` and rejects it as extra.
3. `BackendAgvRelation` exposes exactly the five raw fields.
4. `AgvRelationRequest` and `AlgorithmAgvRelation` expose exactly the five standard fields.
5. Standard AGV rejects legacy route, Buffer and process fields.

**Green implementation:**

1. Remove external runtime `order_code`.
2. Replace raw, standard and internal AGV fields.
3. Update descriptions and exports without changing response schemas.

## Task 3: Drive Loader normalization

**Files:**

- Modify: `tests/adapters/test_backend_request_loader.py`
- Modify: `app/adapters/backend_request_loader.py`

**Red tests:**

1. Map each raw field to its standard field.
2. Do not mutate nested caller data.
3. Ignore `equipmentcode`, `processcode`, `processname` and arbitrary onsite fields only for recognized raw records.
4. Preserve strict unknown-field rejection for standard records.
5. Accept matching raw and standard pairs and retain only standard fields.
6. Reject conflicting pairs with index, both field names and both values.
7. Do not default missing `createtime`.
8. Load a formal `CutlineAlgorithmRequest` only after normalization.
9. Backend ingestion loading uses the same record normalizer.

**Green implementation:**

1. Add the single `_RAW_AGV_FIELD_MAP`.
2. Add pure/deep-copy normalization helpers.
3. Add standard request loading and backend raw projection methods.
4. Keep JSON read errors wrapped in `BackendRequestLoadError`.

## Task 4: Drive Backend Validator changes

**Files:**

- Modify: `tests/adapters/test_backend_request_validator.py`
- Modify: `app/adapters/backend_request_validator.py`

**Red tests:**

1. Remove runtime-order requirements and foreign key checks.
2. Validate normalized AGV machine and order codes.
3. Report every running machine with no AGV record.
4. Do not require or compare AGV process fields.
5. Allow stopped machines without AGV.
6. Ignore future and non-selected historical AGV records.
7. Report selected machine-name mismatch and latest same-time order conflict.

**Green implementation:**

1. Reuse Loader AGV normalization; do not duplicate the raw field map.
2. Replace old runtime-order relationships and special checks.
3. Preserve all unrelated completeness checks.

## Task 5: Drive SnapshotAdapter binding selection and merge

**Files:**

- Modify: `tests/adapters/test_snapshot_adapter.py`
- Add: `app/adapters/agv_binding_selector.py`
- Modify: `app/adapters/snapshot_adapter.py`

**Red tests:**

1. Runtime current order comes from AGV, not machine realtime.
2. Machine process remains from machine master.
3. AGV process extras cannot override machine master.
4. Latest `binding_time <= snapshot_time` wins regardless of input order.
5. Future records do not participate.
6. Exact latest duplicates deduplicate.
7. Latest order code/name conflicts fail.
8. Naive binding time compares as UTC+08:00 against aware snapshot time.
9. Running machine without an effective binding fails.
10. Stopped machine without binding produces `None`.
11. Selected machine/order code and exact name checks fail clearly.
12. Unknown or inconsistent future/non-selected records do not fail.
13. AGV conversion and request objects are not mutated.
14. Product lookup through selected order remains intact.

**Green implementation:**

1. Convert products/orders before AGV selection.
2. Add a shared UTC+08:00 latest-effective binding selector used by
   SnapshotAdapter and Backend Validator.
3. Build a deterministic selected binding index.
4. Validate selected bindings only.
5. Pass the binding index into runtime conversion.
6. Store selected internal AGV bindings in the snapshot.

## Task 6: Drive FastAPI normalization

**Files:**

- Modify: `tests/api/test_fastapi_interfaces.py`
- Modify: `app/api/cutline_api.py`

**Red tests:**

1. `/cutline/evaluate` accepts raw AGV fields.
2. `/stub/algo/run` accepts raw AGV fields.
3. `/backend/validate` accepts the same raw AGV fields.
4. All three paths invoke the Loader normalization entry point.
5. Schema and raw/standard conflicts return 422.

**Green implementation:**

1. Accept request bodies as dictionaries at the calculation routes.
2. Parse via the Loader before invoking the service.
3. Centralize Pydantic/load-error to FastAPI 422 translation.
4. Keep dependency injection and response models unchanged.

## Task 7: Update the shared V3 fixture and integration helpers

**Files:**

- Modify: `tests/fixtures/v3_full_route_factory.py`
- Modify: `tests/integration/helpers.py`
- Modify: relevant `tests/integration/test_v3_*.py`
- Modify: `tests/service/test_cutline_algorithm_service.py`
- Modify: `tests/test_v3_fake_data_contract.py`

**Red tests:**

1. All fixture runtimes omit `order_code`.
2. All fixture AGV records use only raw five fields.
3. Scenario order changes update AGV code, name and time.
4. Real service and integration helpers load through the Loader.
5. Stockout, overflow, candidates, silk, mixing and return results remain unchanged.

**Green implementation:**

1. Refactor fixture machine definitions and AGV builders.
2. Replace `_set_runtime(..., order_code=...)` with an AGV binding helper.
3. Route JSON payload construction through Loader at test/service boundaries.
4. Leave all core assertions and formulas unchanged.

## Task 8: Regenerate and verify examples and documentation

**Files:**

- Modify: `examples/generate_v3_scenarios.py`
- Modify: `examples/run_cutline_algorithm.py`
- Regenerate: `examples/*.json`
- Regenerate: `examples/scenarios/*.json`
- Regenerate: `debug_outputs/*.json`
- Modify: `README.md`
- Modify: `docs/backend-request-interface.md`
- Modify: `docs/algo-request.json`
- Modify: `tests/test_current_examples.py`

**Steps:**

1. Update the generator to use Loader for service requests.
2. Preserve the reduced backend ingestion fields without adding `BackendOrder.order_name`.
3. Regenerate every committed request/response artifact from the shared factory.
4. Update tests and documentation to describe raw AGV input and standard internal mapping.
5. Verify no external runtime `order_code` or legacy AGV process/route field remains.

## Task 9: Run the required verification sequence

Run, in order:

1. `pytest -q tests/adapters/`
2. `pytest -q tests/schemas/`
3. `pytest -q tests/api/`
4. `pytest -q tests/integration/`
5. `pytest -q`
6. `python -m compileall -q app tests examples`
7. `git diff --check`
8. `git status`

Also inspect `git diff` to confirm:

- no `app/core/` change;
- no Buffer logic change;
- no response Schema change;
- no mutating Git command was used.

## Task 10: Final report

Report the requested 25 items, including dependency setup, every grouped/full test result, compile/diff/status output, and explicit confirmation that no commit or push occurred.
