# Pending Cutline Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not commit or push; the user explicitly prohibited both.

**Goal:** Add a stateless, backend-persisted Pending plan confirmation flow so only AGV-proved machine transitions create active cutline events and enter return tracking.

**Architecture:** Add strict shared Pending models, validate them while building the Snapshot, preserve only relevant windowed AGV history, and introduce a focused `PendingCutlineDetector`. Reorder the Pipeline to confirm/merge/evaluate real events before generating new recommendations while leaving all warning, candidate, return, silk-screen, mixing formulas, and the public Response schema unchanged.

**Tech Stack:** Python 3.13, Pydantic 2, pytest 9, FastAPI.

---

### Task 1: Pending contracts and configuration

**Files:**
- Create: `app/schemas/pending_cutline_schema.py`
- Modify: `app/schemas/common_schema.py`
- Modify: `app/schemas/request_schema.py`
- Modify: `app/schemas/backend_request_schema.py`
- Create: `tests/schemas/test_pending_cutline_plan_schema.py`
- Modify: `tests/schemas/test_cutline_algorithm_request_schema.py`
- Modify: `tests/schemas/test_algorithm_common_schema.py`
- Modify: `tests/schemas/test_algorithm_snapshot.py`

- [ ] Write RED schema tests for `BaselineMachineBinding`, `PendingCandidateMachine`, and `PendingCutlinePlan`, including typed nested values, `PENDING`/`PARTIALLY_CONFIRMED`, direction literals, independent empty defaults, count mismatch, duplicate codes, and forbidden extras.
- [ ] Add a RED assertion that `AlgorithmConfig().cutline_confirmation_window_minutes == 30.0` and rejects zero, negative, bool, infinity, and NaN.
- [ ] Add RED request/backend tests proving `pending_cutline_plans` parses when present and defaults to an independent empty list when omitted.
- [ ] Add RED common/snapshot tests proving internal AGV bindings retain nullable `previous_product_name` and Snapshot has typed `pending_cutline_plans` plus `agv_binding_history`.
- [ ] Run `python -m pytest -q tests/schemas/test_pending_cutline_plan_schema.py tests/schemas/test_cutline_algorithm_request_schema.py tests/schemas/test_algorithm_common_schema.py tests/schemas/test_algorithm_snapshot.py` and confirm failures identify missing contracts.
- [ ] Implement strict shared Pydantic models with no `Any`, add the 30-minute config, add the two request collections, and preserve `previous_product_name` internally.
- [ ] Extend the internal active event with optional hidden plan/warning/process/recommended metadata while leaving `app/schemas/response_schema.py` untouched.
- [ ] Re-run the focused schema command and confirm it passes.

### Task 2: Pending relational validation and windowed AGV history

**Files:**
- Create: `app/adapters/pending_cutline_plan_adapter.py`
- Create: `app/adapters/pending_agv_binding_adapter.py`
- Modify: `app/adapters/snapshot_adapter.py`
- Modify: `app/adapters/backend_request_validator.py`
- Modify: `tests/adapters/test_pending_cutline_plan_adapter.py`
- Modify: `tests/adapters/test_snapshot_adapter.py`
- Modify: `tests/adapters/test_backend_request_validator.py`

- [ ] Write RED Adapter tests for duplicate plan ids/business keys, bad window length, invalid direction, count/baseline inconsistency, duplicate baseline/candidate/confirmed codes, candidate missing from baseline, wrong workshop/process, unknown machine/product/order/Buffer, and invalid stockout/overflow direction.
- [ ] Write RED history tests proving only records in at least one baseline machine's `(created_at, expire_at]` window and not after snapshot time are retained; exact duplicates collapse and same-time field conflicts name the plan/machine/time/values.
- [ ] Write RED tests for a transition exactly at `expire_at`, a transition after expiry, an old `linename != lastlinename`, a future record, and nullable/blank previous product.
- [ ] Run the focused Adapter tests and confirm they fail because the adapters/history do not exist.
- [ ] Implement `PendingCutlinePlanAdapter` using existing machine/order/product indexes plus `MachineWorkshopResolver` and Buffer process relations. Build grouped lists before indexes so no duplicate is hidden by overwrite.
- [ ] Implement `PendingAgvBindingAdapter` using normalized project timestamps, exact product-name/current-order resolution, standard machine codes, existing machine/workshop checks, and explicit same-time conflict detection.
- [ ] Integrate both into `SnapshotAdapter` after reference/Buffer indexes are ready. Keep existing latest AGV selection for normal current Snapshot fields and add relevant history separately.
- [ ] Extend active-event input conversion to preserve optional hidden metadata and validate it when supplied.
- [ ] Add completeness-validator checks for Pending duplicate/blank structural fields without duplicating detector business logic.
- [ ] Re-run all Adapter tests and confirm they pass.

### Task 3: Real transition detector

**Files:**
- Create: `app/core/cutline_confirmation/__init__.py`
- Create: `app/core/cutline_confirmation/pending_cutline_detector.py`
- Create: `tests/core/cutline_confirmation/helpers.py`
- Create: `tests/core/cutline_confirmation/test_pending_cutline_detector.py`

- [ ] Build typed test helpers that create a complete Snapshot, Pending plan, baselines, candidates, relevant AGV history, and interval-rate results without untyped dictionaries.
- [ ] Write RED normal tests for unchanged bindings, recommended stockout/overflow changes, customer-selected machines, count-neutral in/out changes, nullable previous product, matching previous product, partial multi-machine execution, multiple rounds, later independent plans, expiry, and the exact 30-minute boundary.
- [ ] Write RED error/ignore tests for baseline count mismatch, wrong direction, status-only count changes, historical/future/late records, previous-product conflict, different workshop/process noise, and duplicate history.
- [ ] Write a RED multi-plan claim test asserting the error contains both plan ids, machine code, and AGV time and produces no duplicate events.
- [ ] Run `python -m pytest -q tests/core/cutline_confirmation/test_pending_cutline_detector.py` and confirm the missing detector fails.
- [ ] Implement `PendingCutlineDetectionError`, typed transition/evaluation results, candidate-first matching, non-candidate fallback, compatibility reuse (`is_wafer_spec_compatible`, `is_source_grade_compatible`), running monitored-order count calculation, expiry-after-detection ordering, and three-layer deduplication.
- [ ] Keep counts auxiliary: never require the aggregate count to change before confirming a valid per-machine binding transition.
- [ ] Re-run detector tests and confirm they pass.

### Task 4: Pipeline orchestration and event lifecycle

**Files:**
- Modify: `app/service/cutline_pipeline.py`
- Modify: `app/core/return_judge/active_cutline_event_tracker.py`
- Modify: `app/mappers/algorithm_response_mapper.py`
- Modify: `tests/service/test_algorithm_pipeline_pending_flow.py`
- Modify: `tests/service/test_algorithm_pipeline_complete_flow.py`
- Modify: `tests/service/test_algorithm_pipeline_decision_flow.py`
- Modify: `tests/mappers/test_algorithm_response_mapper.py`

- [ ] Reverse the old immediate-event test: a warning and automatic plan with no returned Pending must keep its warning/decision but return no new active event and no return result.
- [ ] Add RED spy tests for Pipeline order: net rates → Pending detection → event merge → Return → new warnings/decisions; prove unconfirmed Pending never enters Return.
- [ ] Add RED tests for same-round evaluation of newly confirmed events, merging with existing events, stable event ids, existing/confirmed/current-batch deduplication, and a later plan for the same machine.
- [ ] Add RED business-key tests that a live equivalent Pending or metadata-rich active event suppresses an equivalent new plan without suppressing its warning.
- [ ] Add a RED mapper test proving new-event negative timer state is carried in the new event and not redundantly emitted as an update; keep immediate return recommendation/close behavior valid.
- [ ] Run the focused Pipeline/mapper tests and confirm expected old-behavior failures.
- [ ] Remove the decision-to-event path. Create events only from detector transitions with `cutline_start_time=AGV.binding_time`, standard machine code, target interval, and recommended/customer-selected metadata.
- [ ] Merge new and input events before `ReturnEvaluator`; apply evaluator state immutably to new events and preserve existing update/close semantics.
- [ ] Catch only `PendingCutlineDetectionError` and expose a located `pending_cutline_confirmation` pipeline error.
- [ ] Suppress equivalent plan construction for live tracked business keys while leaving warning/candidate/selection formulas untouched.
- [ ] Preserve the existing scheduled mixing-trace invocation and deterministic future event id; do not change mixing calculations.
- [ ] Re-run focused Pipeline/mapper tests and confirm they pass.

### Task 5: V3 fixtures, integration flow, examples, and docs

**Files:**
- Modify: `tests/fixtures/v3_full_route_factory.py`
- Create: `tests/integration/test_v3_pending_cutline_flow.py`
- Modify: `tests/integration/test_v3_stockout_flow.py`
- Modify: `tests/integration/test_v3_return_flow.py`
- Modify: `tests/integration/test_v3_mixing_flow.py`
- Modify: `tests/test_current_examples.py`
- Modify: `examples/generate_v3_scenarios.py`
- Modify: all generated request JSON under `examples/`
- Modify: `README.md`
- Modify: `docs/backend-request-interface.md`
- Modify: `docs/backend-field-source-mapping.md`

- [ ] Add fixture builders for a warning round, a backend-created Pending record, a later AGV transition with both baseline and new history records, partial confirmation, expiration, and a persisted active event.
- [ ] Update first-round integration assertions: warnings, candidates/plans, and scheduled mixing remain; `new_active_cutline_events` is empty.
- [ ] Add integration tests for stockout candidate confirmation, overflow candidate confirmation, non-candidate confirmation, partial execution, boundary expiry, no-change expiry, and confirmed event return lifecycle.
- [ ] Assert the eventual event id matches the deterministic id already referenced by the scheduled plan-time mixing trace, without changing mixing formulas.
- [ ] Add `pending_cutline_plans: []` to normal samples and at least one generated multi-round Pending confirmation scenario with visibly later AGV time.
- [ ] Update active docs with the backend persistence contract, complete field table, status transitions, event confirmation channel, standard-code guarantee, and AGV `createtime` caveat.
- [ ] Run integration, API, example, service, and response-contract tests and confirm they pass.

### Task 6: Independent review and complete verification

**Files:**
- Review every task-owned diff while preserving all worktree changes that predated this request.

- [ ] Run the new schema/detector/Pipeline/integration tests.
- [ ] Run Backend Loader, Snapshot Adapter, all schemas, cutline plan, ReturnEvaluator, stockout/overflow warning and candidate, silk-screen, and mixing regression groups.
- [ ] Run `python -m compileall -q app tests examples`.
- [ ] Run project-configured Ruff and Pyright/Mypy; if configuration or executable is absent, report that fact rather than claiming a pass.
- [ ] Run complete `python -m pytest -q` and record exact counts/warnings.
- [ ] Run `git diff --check`.
- [ ] Run a valid updated Pending confirmation sample through `examples/run_cutline_algorithm.py` and validate stdout with `CutlineAlgorithmResponse.model_validate_json`.
- [ ] Search for `_create_active_cutline_events`, direct decision/plan-to-event creation, Pending fields in response models, `datetime.now`, process-local Pending caches, `lastlinecode`, and order `order_name`.
- [ ] Request independent spec/code review, fix all high/medium findings with RED/GREEN tests, and repeat affected verification.
- [ ] Record `git status --short`, task-aware `git diff --stat`, unchanged Response schema evidence, no persistence implementation, backend-required fields, AGV timestamp uncertainty, and the fact that no commit/push occurred.
