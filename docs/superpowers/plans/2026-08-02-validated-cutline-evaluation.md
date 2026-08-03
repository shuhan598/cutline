# Validated Cutline Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make the formal cutline endpoint reject invalid backend data and invalid routes with HTTP 422 before running the algorithm, while preserving existing HTTP 200 business outcomes and HTTP 500 unknown-error behavior.

**Architecture:** The API loads `CutlineAlgorithmRequest` once and passes that object through the existing completeness validator before calling `CutlineService`. The validator gains strict per-workshop/per-loop route checks, and the API maps only known input and snapshot conversion failures to structured 422 responses.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, pytest

---

### Task 1: Strict Process Route Completeness

**Files:**
- Modify: `tests/adapters/test_backend_request_validator.py`
- Modify: `tests/adapters/test_snapshot_adapter.py`
- Modify: `app/adapters/backend_request_validator.py`
- Modify: `app/core/workshop/buffer_process_resolver.py`

- [x] **Step 1: Write failing route-validation tests**

Add focused tests using `sample_payload()` for:

```python
def test_route_must_contain_exactly_one_silk_screen_process(): ...
def test_duplicate_silk_screen_process_is_reported(): ...
def test_silk_screen_process_must_have_maximum_sequence(): ...
def test_non_consecutive_unique_sequences_are_allowed(): ...
def test_route_neighbor_codes_and_names_must_match_sorted_adjacency(): ...
def test_first_process_upstream_must_be_empty(): ...
def test_last_silk_screen_downstream_must_be_empty(): ...
def test_route_validation_is_isolated_by_workshop_and_loop(): ...
```

Assert the existing issue schema and repository naming convention, including `dataset == "process_routes"`, locatable `record_key`, and codes `missing_silk_screen_process`, `duplicate_silk_screen_process`, `silk_screen_not_last`, `broken_process_route`, and `invalid_last_process_downstream`.

- [x] **Step 2: Run the new tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/adapters/test_backend_request_validator.py
```

Expected: new route tests fail because missing/duplicate/non-terminal silk screen and strict adjacency are not yet checked.

- [x] **Step 3: Let the validator accept the formal request model**

Import `CutlineAlgorithmRequest` and define the accepted validation input without changing runtime behavior:

```python
from app.schemas.request_schema import AgvRelationRequest, CutlineAlgorithmRequest

CompletenessRequest = BackendAlgorithmRequest | CutlineAlgorithmRequest

def validate(self, request: CompletenessRequest) -> BackendRequestValidationResult:
    ...
```

Update private method annotations that receive the top-level request to use the same alias. Do not duplicate any validation logic.

- [x] **Step 4: Implement strict route validation**

Keep grouping by `(workshop_code, loop_code)` and the existing `duplicate_sequence` behavior. Add exact-name silk-screen cardinality and last-position checks. Only run adjacency comparisons when sequences are unique:

```python
ordered_routes = sorted(indexed_routes, key=lambda item: item[1].sequence)
silk_routes = [item for item in ordered_routes if item[1].process_name == "丝网"]
```

For each ordered process, compare both upstream/downstream codes and names with the immediately adjacent process. Require empty upstream fields on the first process and empty downstream fields on the final silk-screen process. Preserve existing missing-reference and null-field reporting so old callers do not lose diagnostics.

- [x] **Step 5: Run adapter tests and verify GREEN**

Before the GREEN run, update the Buffer resolver regression tests so sequences 10/20 are accepted when no route lies between them, while a 10/30 Buffer relation is rejected when a sequence-20 process exists in the same workshop and loop. Replace the numeric `downstream.sequence == upstream.sequence + 1` condition with a check for a strictly intermediate route sequence.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/adapters/test_backend_request_validator.py tests/adapters/test_agv_order_binding_validator.py tests/adapters/test_pending_cutline_adapters.py
```

Expected: all selected adapter tests pass.

### Task 2: Formal Endpoint Validation and Error Mapping

**Files:**
- Modify: `tests/api/test_fastapi_interfaces.py`
- Modify: `app/api/cutline_api.py`

- [x] **Step 1: Write failing API boundary tests**

Use `build_stockout_auto_payload()` as the complete formal payload and add tests for:

```python
def test_cutline_evaluate_rejects_empty_orders_with_backend_issues(): ...
def test_cutline_evaluate_rejects_order_with_unknown_product(): ...
def test_cutline_evaluate_rejects_missing_required_field_with_backend_error(): ...
def test_cutline_evaluate_maps_loader_error_to_backend_data_invalid(): ...
def test_cutline_evaluate_maps_snapshot_conversion_error_to_422(): ...
def test_cutline_evaluate_does_not_map_unknown_runtime_error_to_422(): ...
```

The first four assert HTTP 422 and `detail.code == "BACKEND_DATA_INVALID"`. The snapshot conversion test asserts `detail.code == "SNAPSHOT_CONVERSION_FAILED"`. Use `TestClient(..., raise_server_exceptions=False)` for the unknown runtime test and assert HTTP 500.

Update the existing delegation test to use the complete fixture so the stub service is reached only after completeness succeeds. Keep `/stub/algo/run` tests on their current payload to prove its behavior is unchanged.

- [x] **Step 2: Run API tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/api/test_fastapi_interfaces.py
```

Expected: new tests fail because `/cutline/evaluate` currently skips completeness validation and does not map `SnapshotConversionError`.

- [x] **Step 3: Add structured backend issue conversion**

In `app/api/cutline_api.py`, reuse `BackendValidationIssue` and add small API-only helpers that build the existing issue fields from Pydantic and loader failures. Return this envelope through `HTTPException(status_code=422, detail=...)`:

```python
{
    "code": "BACKEND_DATA_INVALID",
    "message": "后端数据不完整或数据关联关系错误",
    "issues": [issue.model_dump(mode="json") for issue in issues],
}
```

Do not change `_raise_request_validation_error`, because `/backend/validate` must preserve its existing error shape.

- [x] **Step 4: Add the load-once validated formal request helper**

Implement:

```python
def _load_validated_cutline_request(
    payload: dict[str, Any],
) -> CutlineAlgorithmRequest:
    request = _load_cutline_request_for_evaluation(payload)
    validation = _backend_validator.validate(request)
    if not validation.valid:
        _raise_backend_data_invalid(validation.issues)
    return request
```

The loader helper catches only `ValidationError` and `BackendRequestLoadError`. It calls `BackendRequestLoader.load_cutline_dict()` exactly once. `/backend/validate` continues to use `load_dict()`, and `/stub/algo/run` continues to use the existing schema-only helper.

- [x] **Step 5: Map snapshot conversion at the API boundary**

Wrap only the service invocation for `/cutline/evaluate`:

```python
request = _load_validated_cutline_request(payload)
try:
    return service.evaluate_algorithm(request)
except SnapshotConversionError as exc:
    raise HTTPException(
        status_code=422,
        detail={
            "code": "SNAPSHOT_CONVERSION_FAILED",
            "message": str(exc),
            "issues": [],
        },
    ) from exc
```

Do not add `except Exception`; injected `RuntimeError` must remain a 500.

- [x] **Step 6: Run API tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/api/test_fastapi_interfaces.py
```

Expected: all API tests pass.

### Task 3: Real-Chain Integration Coverage

**Files:**
- Create: `tests/integration/test_v3_validated_api_flow.py`

- [x] **Step 1: Write integration tests against the real FastAPI and service chain**

Create tests using `create_app()`, `TestClient`, and `build_stockout_auto_payload()`:

```python
def test_complete_formal_payload_runs_the_real_chain(): ...
def test_same_missing_orders_payload_is_valid_false_and_evaluate_422(): ...
def test_duplicate_route_sequence_is_rejected_before_service(): ...
def test_silk_screen_not_last_is_rejected_before_service(): ...
def test_duplicate_silk_screen_is_rejected_before_service(): ...
def test_real_snapshot_conversion_failure_returns_422(): ...
```

For the real snapshot conversion case, keep `machine_lines` populated and set `lines=[]`; completeness permits the optional collections, while `SnapshotAdapter` raises its existing explicit conversion error.

- [x] **Step 2: Run integration tests and verify RED or GREEN for each covered layer**

Run the new file after each test is added. Tests for behavior not implemented yet must be observed failing before production changes; tests added after Tasks 1 and 2 must be regression-checked by temporarily reverting the relevant behavior or by confirming they fail against the pre-change revision before restoring the implementation.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/integration/test_v3_validated_api_flow.py
```

Expected after Tasks 1 and 2: all tests pass.

### Task 4: Verification and Scope Audit

**Files:**
- Review: all changed files

- [x] **Step 1: Compile application, tests, and examples**

Run:

```powershell
.\.venv\Scripts\python.exe -m compileall -q app tests examples
```

Expected: exit code 0 with no output.

- [x] **Step 2: Run directly related suites**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/api
.\.venv\Scripts\python.exe -m pytest -q tests/adapters
.\.venv\Scripts\python.exe -m pytest -q tests/integration
```

Expected: every command exits 0 with no failures.

- [x] **Step 3: Run the full test suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: more than the 1437-test baseline is collected and all tests pass.

- [x] **Step 4: Audit the diff against forbidden scope**

Run:

```powershell
git status --short
git diff -- app tests docs/superpowers
```

Confirm no files under overflow, stockout, candidate-machine, silk-screen compatibility, pending/active algorithms, mixing, or return calculation were modified. Confirm `/backend/validate`, `/stub/algo/run`, normal response schemas, and algorithm formulas remain unchanged.
