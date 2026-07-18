# FastAPI Backend Interface Design

- Date: 2026-07-18
- Scope: expose HTTP interfaces for backend request validation, cutline evaluation, and health checks.

## Goals

The service exposes three endpoints:

- `GET /health` returns a simple readiness response.
- `POST /backend/validate` accepts the current backend JSON shape, applies the existing transitional cleanup for `machine_realtime.period_quantity` and `machine_realtime.out_time`, validates it as `BackendAlgorithmRequest`, then returns `BackendRequestValidationResult`.
- `POST /cutline/evaluate` accepts `CutlineAlgorithmRequest`, calls `CutlineService.evaluate_algorithm`, and returns `CutlineAlgorithmResponse`.

## Boundaries

The backend validation endpoint does not run the algorithm and does not convert to `AlgorithmSnapshot`.

The cutline evaluation endpoint uses the existing algorithm request contract. It does not accept `BackendAlgorithmRequest` directly because that model intentionally omits fields still required by `SnapshotAdapter`.

## Error Handling

FastAPI handles request body validation errors as HTTP 422. Backend model validation inside `/backend/validate` is converted to the same 422 shape.

Completeness issues are business validation results, not transport errors. They return HTTP 200 with `valid=false` and a populated `issues` list.

## Tests

API tests cover route registration, health response, valid backend validation, business validation failure, schema validation failure, and service delegation for cutline evaluation.
