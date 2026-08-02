# Pending Cutline Confirmation Design

**Date:** 2026-08-02

## Goal

Stop treating a warning recommendation as an executed cutline. A generated plan
remains pending until a later request contains an AGV binding record that proves
one physical machine changed from its saved baseline order to a valid target
order inside the confirmation window. Only that confirmed transition creates an
active event and enters return tracking.

The service remains stateless. The backend owns persistence and sends both
`pending_cutline_plans` and `active_cutline_events` on later requests. The public
`CutlineAlgorithmResponse` contract is unchanged.

## Current behavior and boundary

`CutlinePipeline.evaluate_algorithm` currently builds a cutline decision and
immediately calls `_create_active_cutline_events`. The event start time is the
plan calculation time plus the configured execution delay. No runtime or AGV
transition is checked. New events are returned to the backend, which must save
and resubmit them in `active_cutline_events`; the repository contains no database
or other persistence implementation.

The existing `new_active_cutline_events` response field is the confirmation
channel. Under the new behavior it contains only events proved by a returned
Pending plan. Its stable event id remains `CUT-{plan_id}-{machine_code}`, so the
backend can correlate the event with its persisted plan without adding public
response fields.

## Considered approaches

1. **Typed request-carried Pending state (selected).** The backend persists a
   complete immutable baseline and resubmits it. The Adapter validates it and a
   core detector compares it with windowed AGV history. This is deterministic,
   horizontally scalable, and respects the response freeze.
2. **Process-local cache.** This would make the service appear stateful, but it
   loses data on restart and diverges between workers. It is explicitly
   prohibited.
3. **Return Pending state in the public response.** This would make backend
   integration easier, but changes the frozen response contract and is
   explicitly prohibited. The backend already has the warning, selected plan,
   and request snapshot needed to construct the Pending record.

## Typed data model

The shared Pending schema contains these models.

### `BaselineMachineBinding`

- Standard `machine_code`.
- Baseline `order_code`, `product_code`, and `product_name`.
- Baseline wafer size, wafer spec, and source grade needed to reuse candidate
  compatibility rules.
- Authoritative `process_code` and `workshop_code`.
- `agv_record_time` of the baseline observation.

The collection covers every machine in the monitored workshop and output-side
process at warning time, not only recommended machines. Each baseline record
must be no later than `warning_time`. Any raw AGV record in
`(warning_time, created_at]` is an explicit unmonitored-gap error rather than a
record that can be silently folded into the baseline or confirmation history.

### `PendingCandidateMachine`

- Standard machine code and a copy of its baseline order/product identity.
- Expected target order/product identity.
- Process and workshop.
- Source and target Buffer context plus the target interval.
- Baseline and target wafer/grade context needed to validate the saved
  recommendation and create a return-trackable event.

Membership in `candidate_machines` means the machine was recommended. A
confirmed baseline machine outside that collection is a customer-selected
machine.

### `PendingCutlinePlan`

- `plan_id`, `warning_id`, `warning_type`, `warning_time`.
- `created_at`, `expire_at`, and `status` (`PENDING` or
  `PARTIALLY_CONFIRMED`).
- Warning business scope: workshop, warning Buffer, upstream/output-side
  process, downstream process, and monitored order.
- `before_machine_count`, `before_machine_codes`, `expected_machine_count`, and
  direction (`increase` for stockout, `decrease` for overflow).
- Candidate machines, all baseline bindings, and
  `confirmed_machine_codes`.

`before_machine_codes` is the subset of baseline machines producing the
monitored order. Counts must agree with the sets. Candidate and baseline keys,
plan ids, and open warning business keys are unique; duplicates are errors, not
dictionary overwrites.
The confirmed count cannot exceed
`abs(expected_machine_count - before_machine_count)`. A stockout confirmation
must originate from a baseline order other than the monitored order; an
overflow confirmation must originate from the monitored order.

### Internal detection results

The detector returns typed confirmed transitions and per-plan evaluations.
Evaluations can be `PENDING`, `PARTIALLY_CONFIRMED`, `COMPLETED`, or `EXPIRED`,
but these internal statuses are not mapped to the public response.

## Adapter and snapshot flow

The request adds optional `pending_cutline_plans` with an independent empty-list
default. Both the direct algorithm request and backend validation request parse
the same strict typed records.

The Snapshot Adapter:

1. Builds the existing standard machine, product, order, route, and Buffer
   indexes.
2. Validates and normalizes Pending plans against those indexes.
3. Keeps the existing single latest AGV relation per machine for normal core
   calculations.
4. Additionally converts only AGV records that fall inside at least one returned
   plan's machine/window into `agv_binding_history`. This avoids making unrelated
   old or future records part of current-order validation while preserving
   enough history to detect a transition at the 30-minute boundary.
5. Preserves `previous_product_name` on internal AGV records. Current order is
   still resolved exclusively by `linename -> product_name -> order_code`.

Same-machine, same-time history records are deduplicated only when every business
field agrees. Conflicting machine name, current product, previous product, wafer
spec, or order resolution is a conversion error.

The default `AlgorithmConfig.cutline_confirmation_window_minutes` is `30.0`.
`expire_at` must equal `created_at + configured window`. Every comparison uses
snapshot/request times; server wall-clock time is never read.

## Confirmation algorithm

For each Pending plan, the detector first scans candidate machines, then other
baseline machines. It ignores already-confirmed machines and transitions already
represented by an input active event.

A record is eligible only when:

- `created_at < binding_time <= expire_at`;
- `binding_time <= snapshot.current_time`;
- the standard machine, authoritative workshop, and output-side process match
  the saved scope;
- the current order differs from the saved baseline.

For a recommended machine, the current order/product and target interval must
equal the saved expected target. For a non-recommended machine:

- stockout requires `other order -> monitored stockout order`;
- overflow requires `monitored overflow order -> a compatible target interval`
  that can absorb production and is not the warning Buffer.

The non-recommended path reuses the existing wafer-spec and source-grade
compatibility functions, including the S2 P/R rule, and the existing
machine-to-workshop resolver. It does not change candidate selection itself.

If current `lastlinename` is nonblank, it must equal the saved baseline product
name. A mismatch is an explicit binding conflict. Null or blank remains valid and
never determines current order.

Machine counts use running runtimes in the pending workshop and output-side
process whose current standard `current_order_code` equals the monitored order.
The count is recorded as an auxiliary/full-completion signal only. A binding
transition can be confirmed even if a simultaneous in/out change leaves the
total unchanged.

The detector scans eligible records before classifying a plan as expired, so a
transition at exactly `expire_at` is confirmed even when the request arrives
later. Records after `expire_at` and records after the snapshot are ignored.

If one physical transition is claimed by multiple plans, one recommended claim
can take priority over only non-recommended claims. Otherwise the detector raises
a conflict containing the plan ids, machine, and binding time.

## Event creation, deduplication, and return evaluation

Each confirmed transition becomes one `AlgorithmActiveCutlineEvent` through the
existing tracker. Its machine code is the standard code and its
`cutline_start_time` is the observable AGV binding record time. The internal event
also keeps plan/warning scope, process, and whether the machine was recommended;
the public event projection remains byte-for-byte the existing shape.

Deduplication checks:

- `pending.confirmed_machine_codes`;
- request `active_cutline_events`;
- events created earlier in the current batch;
- the stable plan/machine event id and machine/binding-time transition key.

The Pipeline order becomes:

1. Calculate interval rates needed by return evaluation.
2. Detect Pending transitions and create real events.
3. Merge existing and newly confirmed events without duplicates.
4. Run `ReturnEvaluator` only on that merged set.
5. Apply same-round negative-timer changes to new event state and normal updates
   to existing events.
6. Generate current warnings, candidates, and plans.
7. Suppress an equivalent new plan while a non-expired Pending or metadata-rich
   active event already owns the same warning business key.
8. Run the unchanged silk-screen and mixing-trace calculations.

Mixing trace remains a scheduled plan-time forecast and its formulas/invocation
contract are unchanged. It uses the same deterministic future event id; only
active-event creation and return tracking wait for observed execution.

## Backend responsibilities

This repository has no persistence implementation. On an automatic decision the
backend must combine the response plan with the same request snapshot to persist
the complete Pending record above. On later calls it sends the Pending record and
all still-active events.

When `new_active_cutline_events` returns, the backend correlates each stable event
id/machine to its Pending plan, adds the machine to
`confirmed_machine_codes`, changes status to `PARTIALLY_CONFIRMED` when work
remains, and persists the event. It stops returning completed plans. At expiry it
drops only unconfirmed work; confirmed active events continue through the normal
return lifecycle. If it resends an expired plan, the algorithm safely ignores it.

Because the public active-event shape is frozen, the backend must retain/enrich
the internal plan/warning/recommended metadata from its Pending record when it
submits an active event for duplicate-plan suppression. Legacy minimal events
remain accepted and continue return tracking.

## Error handling and tests

Schema/Adapter errors reject malformed Pending state before core execution. Core
confirmation errors use a named domain exception and are exposed as a
`pending_cutline_confirmation` pipeline error; they never silently select the
first duplicate or guess a target.

Tests cover strict schemas, Loader and Adapter conversion, windowed AGV history,
stockout/overflow recommended and customer-selected transitions, null/conflicting
previous product, history/future/expiry boundaries, partial and multi-round
confirmation, count-only changes, count-neutral swaps, duplicate input/state,
multi-plan claims, same-round return evaluation, response-contract invariance,
and the existing calculation regressions.
