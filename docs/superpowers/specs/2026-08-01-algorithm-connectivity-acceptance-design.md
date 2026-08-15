选择器会拒绝 target_buffer_code == warning.buffer_code# Algorithm Completeness And Connectivity Acceptance Design

## Goal

Add automated business acceptance tests that prove the complete algorithm chain
is connected from backend request ingestion through response mapping, including
the state carried between repeated algorithm invocations.

The tests validate existing behavior. They do not change core calculations,
request or response contracts, or introduce algorithm-owned persistence.

## Test Boundary

The primary boundary is the real `CutlineService` entry point. Every acceptance
request passes through:

1. `BackendRequestLoader`
2. `SnapshotAdapter`
3. `CutlinePipeline`
4. existing core calculators and evaluators
5. `AlgorithmResponseMapper`

Core components are not mocked. Existing FastAPI tests remain responsible for
HTTP routing and validation behavior; repeating all business assertions at the
HTTP layer would add runtime and duplication without improving algorithm
connectivity coverage.

## Test Structure

Use a hybrid structure rather than one oversized scenario:

- A stockout timeline proves the longest stateful path across multiple rounds.
- An overflow timeline proves the opposite machine-count direction and actual
  machine identification.
- A compact acceptance matrix covers independent and mutually exclusive branches.

All tests live in one dedicated integration module. Reusable payload construction
stays in the existing shared V3 fixture factory and integration helpers.

## Stateful Stockout Timeline

The stockout timeline uses real response identifiers at every boundary:

1. Submit a request that produces a stockout warning and automatic `CutlinePlan`.
2. Assert no active event is created in the plan-generation round.
3. Build backend-persisted pending context from the returned plan, warning, and
   original request context.
4. Submit a second request with unchanged target-order machine count and assert
   that no active event is created.
5. Submit a later request where the expected count is reached and the recommended
   machine has a valid AGV order transition into the target order.
6. Persist the returned active event into the next request.
7. Drive the real `ReturnEvaluator` through negative-rate timer creation, strict
   stability-window completion, return recommendation, and event closure.

The test must not hard-code generated `plan_id` or `event_id` values. It obtains
them from the previous real response and verifies their continuity in later
requests and responses.

## Stateful Overflow Timeline

The overflow timeline uses a payload that can generate a real automatic overflow
plan with a target interval distinct from the overflowing source interval:

1. Produce an overflow warning and automatic plan.
2. Persist the plan as `WAIT_EXECUTION` context.
3. Reduce the target-order machine count to the plan's expected value.
4. Provide an AGV transition out of the target order.
5. Assert that an active event is created for the actual switched machine.

This proves that stockout confirms an increase while overflow confirms a decrease.

## Pending Execution Matrix

Focused real-chain cases cover:

- unchanged machine count keeps the plan waiting and creates no event;
- a recommended machine transition is preferred;
- if no recommended machine transitions, another matching interval machine is
  identified as the actual machine;
- a matching AGV transition without the required count change creates no event;
- an expired plan creates no event;
- a persisted event with the same plan and machine suppresses duplicates;
- transitions outside the plan execution window are ignored.

Pending plan status is request context only. The tests do not expect pending
state or execution status in the response.

## Functional Acceptance Matrix

The dedicated acceptance suite proves the following through real service calls:

| Area | Acceptance evidence |
| --- | --- |
| Identity conversion | dynamic machine maps through `p166_jt_group` to internal `machine_code` |
| Order conversion | AGV `linename` and Buffer `bound_source_name` map by unique `product_name` |
| Workshop routing | machine process resolves through process route to workshop |
| Inventory grouping | physical buffers aggregate by `main_id` and `order_code` |
| AGV authority | current order and `wafer_spec` come from AGV relations |
| Net rate | upstream output and downstream input produce expected interval rate |
| Stockout | prediction, warning, candidates, plan, pending confirmation, active event |
| Overflow | aggregation, prediction, warning, candidates, plan, pending confirmation |
| Manual decisions | no candidate and insufficient capacity remain compact interventions |
| Mixing | successful trace and isolated mixing failure behavior |
| Silk screen | not-ready and preparation branches |
| Return | timer start, timer clear, strict stability window, recommendation, closure |
| Robustness | deterministic output, request immutability, isolated business errors |
| Contract | response does not expose pending status and keeps existing field shapes |

Where an existing integration test already proves a branch through the same real
boundary, the acceptance module may reference the shared scenario rather than
duplicate every low-level assertion. The new tests focus on cross-round continuity
and any uncovered overflow execution path.

## Test Data And State Persistence

The algorithm does not persist state. Test helpers emulate the backend's defined
responsibility by carrying these values between requests:

- the generated plan and warning identity into `pending_cutline_plans`;
- the confirmed event into `active_cutline_events`;
- `negative_start_time` updates returned by the algorithm into the next event
  snapshot;
- closed event IDs by removing closed events before subsequent rounds.

The helper must serialize only fields accepted by current request schemas. It
must not add pending fields to the response or infer a new public contract.

## Failure Diagnostics

Each timeline is split into named test phases or small tests sharing explicit
helpers. Assertions include the round, plan ID, event ID, machine code, warning
type, order code, and relevant counts so a connectivity break is localized.

Tests use exact numeric expectations for representative net-rate, prediction,
inventory, and capacity values. Collection assertions use stable ordering only
where the production contract guarantees it.

## Verification

Run the focused acceptance module first, then all existing integration tests and
the complete suite:

```powershell
.\.venv\Scripts\pytest.exe -q tests\integration\test_algorithm_connectivity_acceptance.py
.\.venv\Scripts\pytest.exe -q tests\integration
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\python.exe -m compileall -q app tests examples
git diff --check
```

Success requires no skipped acceptance cases, no changes under `app/core`, no
Response Schema changes, and no regressions in the existing suite.
