# Cutline V6 Static/Dynamic API Design

## Goal

Split the formal API into static catalog publication, static catalog patching, and dynamic evaluation while preserving the existing algorithm formulas and keeping cross-round state inside the algorithm service.

## Architecture

- `CatalogStore` keeps the active immutable catalog plus a bounded history. Full publication and patch application validate a complete merged catalog before atomically switching the active version. Catalog hashes use UTF-8 JSON with sorted object keys and compact separators; array order remains business-significant.
- `AlgorithmStateStore` keeps per-workshop pending plans, active events, return/mixing watermarks, and the process-wide `state_generation`. Workshop evaluation is serialized and state is replaced only after a successful pipeline result.
- Strict V6 wire models expose `POST /cutline/static-data`, `PATCH /cutline/static-data`, and `POST /cutline/evaluate`. The evaluate adapter resolves the requested catalog version and converts `snapshot_meta` plus `dynamic` data into the existing internal request model. Static arrays, persistence state, and internal AGV aliases are forbidden on the formal wire contract.

## Data Flow

1. Static full publish validates all seven catalog datasets, computes a hash, applies idempotency/version conflict rules, and returns the retained versions.
2. Static patch resolves `base_catalog_version`, applies per-dataset upserts and explicit deletes by the documented business key, validates the merged snapshot, and publishes `next_catalog_version` atomically.
3. Evaluate resolves the requested immutable catalog before running the pipeline. Missing versions or missing static references return documented recovery errors without executing the algorithm. A successful response adds `catalog_version`, `state_generation`, and `state_reset`; persistence state is not serialized.

## Errors and Restart Semantics

The API returns `{detail: {code, message, ...}}` for `STATIC_DATA_INVALID`, `IDEMPOTENCY_KEY_REUSED`, `CATALOG_VERSION_CONFLICT`, `BASE_CATALOG_VERSION_NOT_FOUND`, `BASE_CATALOG_VERSION_STALE`, `CATALOG_VERSION_NOT_FOUND`, `STATIC_CATALOG_REQUIRED`, `STATIC_CATALOG_DATA_MISSING`, `DYNAMIC_DATA_INVALID`, and `INTERNAL_ERROR` using the HTTP statuses defined by the V6 design document.

The service does not persist catalogs or algorithm state. Each process start creates a new `state_generation`; the first successful evaluation for each workshop returns `state_reset=true`, and later successful evaluations in that generation return `false`.

## Testing

Contract tests cover strict request models and response fields. Store tests cover deterministic hashing, idempotent retries, version/content conflicts, explicit deletes, stale bases, and atomic validation failure. API/integration tests cover catalog-version pinning, missing-reference recovery errors, restart state reset, per-workshop state continuity, and rejection of legacy flat fields or `persistence_state`.

