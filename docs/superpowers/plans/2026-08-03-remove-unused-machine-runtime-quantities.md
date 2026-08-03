# Remove Unused Machine Runtime Quantities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the three unused machine-runtime quantity fields from every input and internal layer without changing algorithm behavior.

**Architecture:** Keep the existing Loader → strict request → completeness validator → SnapshotAdapter → Pipeline chain. Narrow each machine-runtime model to the two sourced quantity values and let the existing `extra="forbid"` policy reject legacy keys.

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI, pytest

---

### Task 1: Add contract regression tests

**Files:**
- Modify: `tests/schemas/test_backend_request_schema.py`
- Modify: `tests/schemas/test_cutline_algorithm_request_schema.py`
- Modify: `tests/schemas/test_algorithm_common_schema.py`
- Modify: `tests/adapters/test_backend_request_loader.py`
- Modify: `tests/adapters/test_snapshot_adapter.py`
- Modify: `tests/api/test_fastapi_interfaces.py`
- Modify: `tests/examples/test_cutline_standard_examples.py`

- [ ] Remove the deleted keys from all test payload builders.
- [ ] Assert the backend and normalized request model fields contain only the sourced quantity keys.
- [ ] Assert the internal runtime model has only the two 30-minute quantity fields.
- [ ] Assert legacy keys are rejected by the strict request models and Loader.
- [ ] Assert the targeted OpenAPI component omits the deleted keys.
- [ ] Assert every request example recursively omits the deleted machine-runtime keys.
- [ ] Run the targeted tests and verify they fail because production Schema and Adapter definitions still contain the fields.

### Task 2: Delete fields from production layers

**Files:**
- Modify: `app/schemas/backend_request_schema.py`
- Modify: `app/schemas/request_schema.py`
- Modify: `app/schemas/common_schema.py`
- Modify: `app/adapters/backend_request_loader.py`
- Modify: `app/adapters/snapshot_adapter.py`

- [ ] Remove `completed_quantity` from the backend realtime model.
- [ ] Remove `completed_quantity` and `period_quantity` from the normalized request realtime model.
- [ ] Remove `period_quantity_30m` from the internal runtime model.
- [ ] Stop Loader cleanup of the deleted legacy key while preserving unrelated `out_time` handling.
- [ ] Stop SnapshotAdapter from mapping the deleted quantity.
- [ ] Run schema, loader, adapter and API tests and verify green.

### Task 3: Update all fixtures and examples

**Files:**
- Modify: `tests/fixtures/v3_full_route_factory.py`
- Modify: all affected test builders under `tests/`
- Modify: `examples/generate_v3_scenarios.py`
- Modify: `examples/generate_cutline_standard_examples.py` if required
- Modify: affected JSON files under `examples/`
- Modify: `docs/algo-request.json`

- [ ] Delete the unused keys from shared factories and direct test builders.
- [ ] Delete compatibility projection code from scenario generation.
- [ ] Regenerate all generated V3 and standard examples.
- [ ] Mechanically delete the keys from non-generated JSON examples.
- [ ] Run example and integration tests and verify business outputs remain unchanged.

### Task 4: Update interface documentation

**Files:**
- Modify: `docs/cutline_algorithm_input_output_spec.md`
- Modify: `docs/backend-request-interface.md`
- Modify: `docs/2026-07-14-algo-request-document-field-mapping.md`
- Modify: affected historical design documents where they still describe a live runtime contract

- [ ] Remove deleted fields from tables and JSON snippets.
- [ ] State that input/output quantities represent the latest 30-minute window and are doubled for hourly rates.
- [ ] Mark the external source window as a backend/customer confirmation risk without changing code.
- [ ] Remove obsolete compatibility claims.

### Task 5: Verify the repository

**Files:**
- Verify: `app/`, `tests/`, `examples/`, `docs/`

- [ ] Run `python -m compileall -q app tests examples`.
- [ ] Run API, adapter, integration and example test suites separately.
- [ ] Run full `pytest -q` and confirm the test count does not decrease.
- [ ] Run `git diff --check`.
- [ ] Search all requested spelling variants and classify any intentional test/plan references.
- [ ] Review the final diff to ensure core algorithm and response files were not modified.

