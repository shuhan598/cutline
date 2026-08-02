# AGV Product Matching and Machine Code Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development task-by-task. Do not commit or push; the user explicitly prohibited Git commits for this task.

**Goal:** Resolve AGV and Buffer bindings by product model name and normalize realtime machine identifiers through `p166_jt_group` before building the algorithm snapshot.

**Architecture:** Keep raw-to-standard field projection in the Loader, centralize uniqueness and exact-reference lookup in focused Adapter index classes, and pass only standard `machine_code` plus `order_code` into core models. Reuse the existing machine/process and Buffer/process workshop resolution paths.

**Tech Stack:** Python 3.13, Pydantic 2, pytest 9, FastAPI.

---

### Task 1: External and internal contracts

**Files:**
- Modify: `tests/schemas/test_agv_order_binding_contract.py`
- Modify: `tests/adapters/test_agv_order_binding_loader.py`
- Modify: `app/schemas/backend_request_schema.py`
- Modify: `app/schemas/request_schema.py`
- Modify: `app/schemas/common_schema.py`
- Modify: `app/adapters/backend_request_loader.py`

- [x] Change tests so raw AGV requires `linename`, allows nullable `lastlinename`, and has no `lastlinecode`.
- [x] Change tests so orders have no `order_name` and machine masters require `p166_jt_group`.
- [x] Run the focused tests and confirm failures are caused by the old contracts.
- [x] Implement the minimal Schema and Loader field changes: `linename -> product_name`, `lastlinename -> previous_product_name`; remove the old order mapping.
- [x] Re-run focused tests and confirm they pass.

### Task 2: Reference index classes

**Files:**
- Create: `app/adapters/snapshot_reference_index.py`
- Modify: `tests/adapters/test_snapshot_adapter.py`

- [x] Add failing tests for blank/duplicate standard and realtime machine codes, blank/duplicate product codes and names, duplicate order codes/product names, and order/product mismatch.
- [x] Run the focused tests and confirm the missing classes/behaviors fail.
- [x] Implement `MachineMasterIndex`, `ProductCatalogIndex`, and `CurrentOrderIndex` with exact trimmed matching and explicit diagnostics.
- [x] Re-run the focused tests and confirm they pass.

### Task 3: Snapshot conversion and workshop validation

**Files:**
- Modify: `tests/adapters/test_snapshot_adapter.py`
- Modify: `app/adapters/snapshot_adapter.py`
- Modify: `app/adapters/agv_binding_selector.py`

- [x] Convert the base test request to distinct standard and realtime machine identifiers and unique product/order names.
- [x] Add failing tests for AGV `linename` resolution, ignored `lastlinename`, latest-time conflict fields, unknown identifiers, runtime normalization, missing current orders, and AGV/Buffer workshop conflicts.
- [x] Run the focused SnapshotAdapter tests and confirm expected failures.
- [x] Reorder adapter conversion so products/orders/routes are indexed before AGV and runtime association.
- [x] Resolve AGV machines by standard code, realtime machines by `p166_jt_group`, and both to the same internal code.
- [x] Resolve AGV and Buffer product names through the current-order index and enforce workshop equality.
- [x] Re-run SnapshotAdapter tests and confirm they pass.

### Task 4: Backend completeness validation

**Files:**
- Modify: `tests/adapters/test_agv_order_binding_validator.py`
- Modify: `tests/adapters/test_backend_request_validator.py`
- Modify: `app/adapters/backend_request_validator.py`

- [x] Add failing validation tests for both machine indexes, product/order uniqueness and consistency, AGV/Buffer product-name lookup, runtime mapping, latest binding conflicts, workshop checks, and running-machine binding checks after normalization.
- [x] Run the focused validator tests and confirm expected failures.
- [x] Update relationship targets and validation logic without silently overwriting duplicates.
- [x] Re-run validator tests and confirm they pass.

### Task 5: Core-facing product-name field and fixtures

**Files:**
- Modify: `app/core/candidate_machine/stockout_candidate_finder.py`
- Modify: `app/core/candidate_machine/overflow_candidate_finder.py`
- Modify: core/schema/service test helpers that construct `AlgorithmOrder` or `AlgorithmAgvRelation`
- Modify: `tests/fixtures/v3_full_route_factory.py`

- [x] Update tests to construct internal orders without `order_name` and AGV relations with `product_name`.
- [x] Confirm the focused candidate/net-rate/mixing/silk/service tests fail against the old internal fields.
- [x] Use AGV `product_name` for the unchanged candidate result field `current_order_name`.
- [x] Update the V3 factory so realtime codes are visibly different from standard codes and Buffer/AGV names are product model names.
- [x] Re-run focused core and integration tests.

### Task 6: Examples and active documentation

**Files:**
- Modify: `examples/generate_v3_scenarios.py`
- Regenerate/update: all valid input JSON under `examples/`
- Modify: `README.md`
- Modify: `docs/backend-request-interface.md`
- Modify: `docs/backend-field-source-mapping.md`
- Modify: `docs/2026-07-14-algo-request-document-field-mapping.md`

- [x] Update example contract tests first to assert no valid request contains `lastlinecode` or order `order_name`, and to assert distinct realtime/standard codes.
- [x] Run example tests and confirm they fail on old samples.
- [x] Regenerate scenario inputs/responses from the updated shared factory and manually update non-generated ingestion samples.
- [x] Update active documentation to describe the new chains and field meanings.
- [x] Re-run example and API/service tests.

### Task 7: Review and complete verification

**Files:**
- Review all changed files; preserve the pre-existing mapper diff.

- [ ] Run focused Schema, Loader, Validator, SnapshotAdapter, core, service, API, and example tests.
- [ ] Run `python -m compileall app tests examples`.
- [ ] Report Ruff/Pyright/Mypy as not project-configured if no configuration/executable exists.
- [ ] Run the complete `pytest -q` suite and record counts/warnings.
- [ ] Run `git diff --check` and inspect `git diff --stat`.
- [ ] Run `examples/run_cutline_algorithm.py` with a valid updated sample and validate the emitted JSON with `CutlineAlgorithmResponse`.
- [ ] Search production, normal tests, examples, README, and active interface docs for old fields/matching logic; allow only explicit negative-contract assertions or historical Superpowers design records.
- [ ] Request independent spec and code-quality review, fix every critical/important finding, and repeat the relevant verification.
