# Cutline V6 Static/Dynamic API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement strict V6 static catalog publication/patching and dynamic evaluation APIs with in-memory versioned catalogs and per-workshop algorithm state.

**Architecture:** Add focused catalog and state stores, strict V6 request/response models, an adapter that composes the existing internal request from a catalog snapshot and dynamic payload, and API routes that preserve existing pipeline formulas. Keep legacy stub/regression routes intact while making formal `/cutline/evaluate` use the new contract.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, pytest.

---

### Task 1: Add catalog and state store tests

**Files:**
- Create: `tests/service/test_catalog_store.py`
- Create: `tests/service/test_algorithm_state_store.py`

- [x] Write failing tests for deterministic catalog hashes, idempotent publish, version/content conflicts, explicit patch deletes/upserts, stale bases, and atomic validation failure.
- [x] Write failing tests for process generation, per-workshop first-success reset, and state replacement only after success.
- [x] Run focused pytest commands and confirm failures are due to missing stores.

### Task 2: Implement catalog and state stores

**Files:**
- Create: `app/service/catalog_store.py`
- Create: `app/service/algorithm_state_store.py`

- [x] Implement immutable catalog records, stable SHA-256 hashing, bounded retention, idempotency tracking, business-key patch merging, and typed domain errors.
- [x] Implement process-wide generation and per-workshop serialized state snapshots with commit-on-success semantics.
- [x] Run focused tests to green.

### Task 3: Add strict V6 wire schemas and adapters

**Files:**
- Create: `app/schemas/v6_schema.py`
- Create: `app/adapters/v6_request_adapter.py`
- Create: `tests/schemas/test_v6_schema.py`
- Create: `tests/adapters/test_v6_request_adapter.py`

- [x] Define seven static datasets, full publish, patch, dynamic-only evaluate request, catalog response, evaluate response metadata, and catalog error detail with `extra="forbid"`.
- [x] Ensure dynamic wire fields map to existing request models and top-level `catalog_version` fills internal snapshot metadata without accepting flat static arrays or persistence state.
- [x] Run focused schema/adapter tests to green.

### Task 4: Add API routes and service integration

**Files:**
- Modify: `app/api/cutline_api.py`
- Modify: `app/main.py`
- Modify: `app/service/cutline_service.py`
- Create: `tests/api/test_v6_static_dynamic_api.py`

- [x] Add `POST/PATCH /cutline/static-data` with `Idempotency-Key`, domain error mapping, and atomic publication.
- [x] Update formal `POST /cutline/evaluate` to resolve a requested immutable catalog, reject missing catalogs/references before pipeline execution, inject per-workshop state, and return `catalog_version`, `state_generation`, and `state_reset` without `persistence_state`.
- [x] Keep `/stub/algo/run` and existing internal tests compatible.
- [x] Run API tests to green.

### Task 5: Contract fixtures and verification

**Files:**
- Create: `contracts/cutline-v6/*.schema.json`
- Create: `tests/integration/test_v6_static_dynamic_flow.py`

- [x] Add JSON schemas/fixtures for full publish, patch, evaluate, success response, and catalog errors.
- [x] Cover version pinning across publication, restart reset behavior, missing-reference recovery, and rejection of legacy fields.
- [x] Run focused/core pytest suites and verify syntax without changing algorithm formulas. Legacy flat-evaluate tests remain expected migration failures.
