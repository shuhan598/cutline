# FastAPI Backend Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add usable FastAPI endpoints for backend validation, cutline evaluation, and health checks.

**Architecture:** Keep API orchestration in `app/api`. `app/main.py` creates and wires the FastAPI app. Existing schemas, loader, validator, and service remain the source of behavior.

**Tech Stack:** Python, FastAPI, Pydantic v2, pytest, FastAPI TestClient.

---

### Task 1: API Tests

**Files:**
- Create: `tests/api/test_fastapi_interfaces.py`

- [ ] Add tests for `GET /health`, `POST /backend/validate`, and `POST /cutline/evaluate`.
- [ ] Run `pytest tests/api/test_fastapi_interfaces.py -q` and verify the tests fail because the app and routes are not implemented.

### Task 2: API Implementation

**Files:**
- Modify: `app/main.py`
- Modify: `app/api/health_api.py`
- Modify: `app/api/cutline_api.py`

- [ ] Implement `create_app()` and `app`.
- [ ] Register health and cutline routers.
- [ ] Implement backend validation and cutline evaluation handlers.
- [ ] Run `pytest tests/api/test_fastapi_interfaces.py -q` and verify the tests pass.

### Task 3: Regression Verification

**Files:**
- No production edits expected.

- [ ] Run focused schema/adapter/API tests.
- [ ] Run the full test suite if focused tests are clean.
