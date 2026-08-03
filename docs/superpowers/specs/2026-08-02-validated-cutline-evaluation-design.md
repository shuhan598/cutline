# Validated Cutline Evaluation Design

- Date: 2026-08-02
- Scope: formal cutline request validation, route integrity validation, HTTP error mapping, and regression coverage.

## Goals

The formal `POST /cutline/evaluate` endpoint must execute this chain before any algorithm calculation:

```text
JSON
-> BackendRequestLoader
-> BackendRequestCompletenessValidator
-> SnapshotAdapter
-> CutlinePipeline
-> AlgorithmResponseMapper
-> Response
```

The endpoint must load the payload into `CutlineAlgorithmRequest` once, validate that same parsed object, and only call `CutlineService` when completeness validation succeeds. `/backend/validate` and `/stub/algo/run` retain their existing behavior.

## Architecture

`app/api/cutline_api.py` owns HTTP concerns. A focused helper loads and validates the formal evaluation request. It reuses `BackendRequestLoader.load_cutline_dict()` and `BackendRequestCompletenessValidator`; it does not introduce a second loader, validator, service, or exception hierarchy.

`BackendRequestCompletenessValidator` accepts both existing external request models because they expose the same datasets used by completeness checks. The formal endpoint passes its already parsed `CutlineAlgorithmRequest`, avoiding a second parse of the payload.

`BufferProcessResolver` treats two served processes as adjacent when no process in the same workshop and loop has a sequence strictly between them. This preserves route-order adjacency for valid non-consecutive sequences such as 10/20/30 without changing Buffer inventory or algorithm calculations.

`CutlineService` continues to adapt the request into `AlgorithmSnapshot`, execute `CutlinePipeline`, and map the response. It continues to propagate `SnapshotConversionError` and unknown exceptions unchanged. The API boundary maps only recognized input-domain exceptions to HTTP status codes.

## Route Integrity Rules

Process routes remain grouped by `(workshop_code, loop_code)`. Sequences must be sortable and unique within a group, but they need not be consecutive.

Each group must contain exactly one process whose `process_name` is exactly `"丝网"`. Fuzzy matching is forbidden. A missing silk-screen process, duplicate silk-screen processes, or a silk-screen process whose sequence is not the maximum sequence makes the request incomplete.

For a group with unique sequences, routes are sorted by sequence and checked as a strict chain:

- The first process has null upstream code and name.
- Each non-first process has the previous process's code and name as its upstream code and name.
- Each non-last process has the next process's code and name as its downstream code and name.
- The last process has null downstream code and name.
- The last process is the exact `"丝网"` process.

Validation produces existing `BackendValidationIssue` objects with the dataset, route identity, process identity, field, and a clear message. New issue codes follow the repository's lowercase snake-case convention:

- `missing_silk_screen_process`
- `duplicate_silk_screen_process`
- `silk_screen_not_last`
- `broken_process_route`
- `invalid_last_process_downstream`

The existing `duplicate_sequence` code remains unchanged for compatibility.

## HTTP Error Mapping

Pydantic `ValidationError`, `BackendRequestLoadError`, and completeness failures return HTTP 422 with this envelope:

```json
{
  "detail": {
    "code": "BACKEND_DATA_INVALID",
    "message": "后端数据不完整或数据关联关系错误",
    "issues": []
  }
}
```

Completeness failures serialize the existing issues with `model_dump(mode="json")`. Loader and Pydantic failures are represented with the same existing issue fields rather than a new issue schema.

`SnapshotConversionError` returns HTTP 422 with:

```json
{
  "detail": {
    "code": "SNAPSHOT_CONVERSION_FAILED",
    "message": "the original conversion error message",
    "issues": []
  }
}
```

The API does not catch arbitrary `Exception`. Unknown program errors therefore retain HTTP 500 behavior. Pipeline branches already represented as normal response decisions, manual intervention, or `errors` remain HTTP 200.

## Testing

Tests follow red-green-refactor and reuse current fixtures.

Adapter tests cover route grouping, non-consecutive valid sequences, Buffer adjacency by sorted route order, duplicate sequences, missing/duplicate/non-terminal silk screen, strict adjacent code and name links, first-process upstream emptiness, and last-process downstream emptiness.

API and integration tests cover:

- a complete formal payload returning HTTP 200 without response schema changes;
- missing orders returning `valid=false` from `/backend/validate` and HTTP 422 from `/cutline/evaluate`;
- an order referencing an unknown product returning HTTP 422;
- route integrity failures returning HTTP 422 with locatable issues;
- a real `SnapshotConversionError` returning `SNAPSHOT_CONVERSION_FAILED`;
- an injected unknown `RuntimeError` remaining HTTP 500;
- `/backend/validate` and `/stub/algo/run` retaining their current behavior.

Verification uses the repository virtual environment and runs compileall, directly related API/adapter/integration tests, and the full pytest suite. The pre-change baseline is 1437 collected tests, with 165 directly related tests passing.

## Non-Goals

This work does not change overflow calculations, stockout calculations, candidate-machine rules, exact silk-screen compatibility checks, pending or active event behavior, mixing, return calculation, cutline plan calculation, or response fields.
