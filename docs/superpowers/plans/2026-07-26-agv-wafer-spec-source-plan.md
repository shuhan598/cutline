# AGV Wafer Spec Source Implementation Plan

> **后续变更说明：** 本计划记录 AGV 规格改造当时的实施步骤。其中机台所属车间来源
> 已被 `2026-07-26-machine-workshop-route-source-design.md` 更新为工艺路线。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The user explicitly forbids commits and branch changes, so verification checkpoints replace commit steps.

**Goal:** Make AGV the authoritative source of each machine's current order, order name, and wafer specification without changing runtime structure, net-rate formulas, or candidate compatibility rules.

**Architecture:** Extend the existing three-layer AGV contract and SnapshotAdapter output, then add AGV indices to the existing net-rate and candidate contexts. Keep line data for compatibility while removing core reads that treat `line.wafer_spec` as current production state. The later workshop-source design replaces the workshop lookup portion with process-route resolution.

**Tech Stack:** Python 3.13, Pydantic v2, FastAPI, pytest

---

### Task 1: AGV Contract, Loader, and Snapshot Conversion

**Files:**
- Modify: `app/schemas/backend_request_schema.py`
- Modify: `app/schemas/request_schema.py`
- Modify: `app/schemas/common_schema.py`
- Modify: `app/adapters/backend_request_loader.py`
- Modify: `app/adapters/snapshot_adapter.py`
- Test: `tests/schemas/test_agv_order_binding_contract.py`
- Test: `tests/adapters/test_agv_order_binding_loader.py`
- Test: `tests/adapters/test_agv_order_binding_validator.py`
- Test: `tests/adapters/test_snapshot_adapter.py`
- Test: `tests/schemas/test_algorithm_common_schema.py`

- [ ] **Step 1: Write failing contract, mapping, conflict, and adapter tests**

Add `waferspec` to `RAW_AGV_FIELDS`, `wafer_spec` to `STANDARD_AGV_FIELDS`,
and add the values to all AGV test records. Assert Loader normalization includes
`"wafer_spec": "N"`, the raw/standard conflict parameterization includes
`("waferspec", "wafer_spec")`, and selected adapter output contains the latest
record's `wafer_spec`. Assert:

```python
assert "current_wafer_spec" not in AlgorithmMachineRuntime.model_fields
```

Add a same-machine/same-time/different-spec test that converts successfully and
asserts a deterministic selected value without expecting a conflict.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/schemas/test_agv_order_binding_contract.py `
  tests/adapters/test_agv_order_binding_loader.py `
  tests/adapters/test_agv_order_binding_validator.py `
  tests/adapters/test_snapshot_adapter.py `
  tests/schemas/test_algorithm_common_schema.py
```

Expected: failures identify the missing `waferspec/wafer_spec` fields and missing
SnapshotAdapter propagation.

- [ ] **Step 3: Implement the minimal contract and conversion changes**

Add:

```python
class BackendAgvRelation(_BackendRequestModel):
    ...
    waferspec: str

class AgvRelationRequest(RequestModel):
    ...
    wafer_spec: str = Field(..., description="AGV 绑定的当前硅片规格")

class AlgorithmAgvRelation(AlgorithmModel):
    ...
    wafer_spec: str = Field(..., description="当前硅片规格")
```

Extend `_RAW_AGV_FIELD_MAP` with `"waferspec": "wafer_spec"`. In
`SnapshotAdapter._convert_agv_relations`, choose a deterministic record from the
latest same-identity records and pass its `wafer_spec` to `AlgorithmAgvRelation`.
Do not change `AlgorithmMachineRuntime`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass.

### Task 2: Net Rate Uses AGV Order and Wafer Spec

**Files:**
- Modify: `app/core/net_rate/net_rate_calculator.py`
- Test: `tests/core/net_rate/test_algorithm_net_rate_calculator.py`
- Test: `tests/core/net_rate/test_snapshot_only_contract.py`

- [ ] **Step 1: Write failing AGV-source tests**

Extend the net-rate test helpers to create `AlgorithmAgvRelation` entries. Add tests
that prove:

```python
line.wafer_spec == "N"
agv.wafer_spec == "R"
result.wafer_spec == "R"
```

and prove only machines whose AGV order/spec match contribute, even when their line
spec differs. Replace the old multiple-line-spec failure test with deterministic
multiple-AGV selection by `machine_code`. Change missing-spec tests to expect an
explicit `snapshot.agv_relations` error. Retain existing `main_id` aggregation tests.

- [ ] **Step 2: Run focused net-rate tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/core/net_rate
```

Expected: new tests fail because net rate still reads runtime order and line spec.

- [ ] **Step 3: Implement AGV indices and matching**

Add `AlgorithmAgvRelation` imports and an `agv_by_machine_code` index to
`_AlgorithmNetRateContext`. Resolve order spec with:

```python
relations = sorted(
    (item for item in snapshot.agv_relations if item.order_code == order_code),
    key=lambda item: item.machine_code,
)
```

Raise `NetRateCalculationError` if empty; otherwise use `relations[0].wafer_spec`.
In `_matching_runtimes`, use the runtime machine code to obtain the AGV relation and
check `agv.order_code` and `agv.wafer_spec`. The original line-based workshop lookup
in this historical plan is superseded by the shared process-route resolver.

- [ ] **Step 4: Run focused net-rate tests and verify GREEN**

Run the Step 2 command. Expected: all net-rate tests pass.

### Task 3: Candidate Context and Finders Use AGV

**Files:**
- Modify: `app/core/candidate_machine/candidate_context.py`
- Modify: `app/core/candidate_machine/stockout_candidate_finder.py`
- Modify: `app/core/candidate_machine/overflow_candidate_finder.py`
- Modify: `app/schemas/result_schema.py`
- Modify: any production response mapper that explicitly constructs candidate models
- Test: `tests/core/candidate_machine/helpers.py`
- Test: `tests/core/candidate_machine/test_candidate_context.py`
- Test: `tests/core/candidate_machine/test_algorithm_stockout_candidate_finder.py`
- Test: `tests/core/candidate_machine/test_algorithm_overflow_candidate_finder.py`
- Test: `tests/core/candidate_machine/test_algorithm_compatibility.py`
- Test: `tests/core/cutline_plan/helpers.py`
- Test: every test that directly constructs either CandidateMachine model

- [ ] **Step 1: Write failing context and candidate tests**

Add an AGV helper supporting machine code, order code, order name, wafer spec, and
binding time. Populate candidate snapshots with selected AGV relations. Add tests:

- stockout accepts line N / AGV R / warning R;
- stockout rejects line R / AGV N / warning R outside the S2 exception;
- runtime order deliberately differs from AGV and AGV remains authoritative;
- overflow source order, name, and spec come from AGV and ignore line spec;
- existing S2 R/P compatibility still passes;
- both candidate model dumps contain `current_order_name`.

- [ ] **Step 2: Run focused candidate tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/core/candidate_machine `
  tests/core/cutline_plan
```

Expected: failures show missing AGV index/name field and old line/runtime reads.

- [ ] **Step 3: Implement CandidateContext and finder changes**

Index `snapshot.agv_relations` by machine code and add a method returning the current
`AlgorithmAgvRelation`, raising `CandidateMachineCalculationError` for a running
candidate with no relation. Keep `machine_context` unchanged.

In both finders, obtain the AGV after the running-status check. Use:

```python
current_order, current_product = context.order_product(candidate_agv.order_code)
```

and pass `candidate_agv.wafer_spec` to the existing compatibility function. Fill
`current_order_code`, `current_order_name`, and `current_wafer_spec` from AGV.
For overflow source identity, compare AGV order/spec with the selected source detail.

Add required `current_order_name: str` fields to both candidate result models and
update every direct constructor. Do not change compatibility, sorting, capacity,
same-Buffer, or workshop logic.

- [ ] **Step 4: Run focused candidate tests and verify GREEN**

Run the Step 2 command. Expected: all candidate and plan tests pass.

### Task 4: Shared Fixtures, API Chain, Examples, and Documentation

**Files:**
- Modify: `tests/fixtures/v3_full_route_factory.py`
- Modify: `tests/api/test_fastapi_interfaces.py`
- Modify: `tests/service/test_cutline_algorithm_service.py`
- Modify: `tests/integration/test_v3_overflow_flow.py`
- Modify: `tests/test_v3_fake_data_contract.py`
- Modify: other strict request fixtures found by repository search
- Modify: `examples/generate_v3_scenarios.py` if generation behavior requires it
- Modify: `examples/backend_ingestion_request_sample.json`
- Modify: `examples/backend_request_sample.json`
- Modify: `examples/backend_request_stockout_plan_sample.json`
- Modify: `examples/scenarios/*.json`
- Modify: `README.md`
- Modify: `docs/backend-request-interface.md`
- Modify: `docs/2026-07-14-algo-request-document-field-mapping.md`

- [ ] **Step 1: Write failing full-chain and fixture-contract tests**

Update the shared AGV factory API so a binding accepts:

```python
machine_code
order_code
order_name
wafer_spec
binding_time
```

Assert every raw AGV fixture contains `waferspec`, raw FastAPI requests accept it,
and the service call receives `AgvRelationRequest.wafer_spec`. Add or adjust an
end-to-end FastAPI test covering Loader -> SnapshotAdapter -> Pipeline ->
ResponseMapper with `waferspec`.

- [ ] **Step 2: Run focused integration tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/api `
  tests/service `
  tests/integration `
  tests/test_v3_fake_data_contract.py `
  tests/test_current_examples.py
```

Expected: strict AGV records and unchanged factory/example data fail until updated.

- [ ] **Step 3: Update factories and regenerate examples**

Derive default AGV specs from the machine's bound line only when building compatible
test data; allow each scenario/test to override AGV spec independently. Add
`"waferspec": "N"` or the scenario's R/P value to every raw example and
`"wafer_spec"` to standard examples. Regenerate scenario JSON with the existing
generator after updating its source factory.

Update README and request documentation to describe six raw AGV fields, the mapping,
the AGV order/spec authority, missing-data error, retained line compatibility field,
and retained line/machine-line compatibility fields. Machine workshop authority is
defined by the later process-route source design.

- [ ] **Step 4: Run focused integration tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass.

### Task 5: Audit and Final Verification

**Files:**
- Inspect all modified files
- Inspect every `line.wafer_spec` and AGV example occurrence

- [ ] **Step 1: Audit forbidden and retained reads**

Run:

```powershell
rg -n "line\.wafer_spec" app/core
rg -n '"equipmentid"|"waferspec"' examples tests docs README.md
rg -n "current_order_name" app tests
```

Expected: no `line.wafer_spec` current-production read remains in net rate or either
candidate finder; line Schema/conversion compatibility fields remain.

- [ ] **Step 2: Run full tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Run compilation**

Run:

```powershell
.\.venv\Scripts\python.exe -m compileall -q app tests examples
```

Expected: exit code 0 with no output.

- [ ] **Step 4: Check patch whitespace**

Run:

```powershell
git diff --check
```

Expected: exit code 0 with no output.

- [ ] **Step 5: Review final diff against every approved requirement**

Confirm no runtime spec field, no new wafer-spec conflict checks, no formula or
aggregation changes, no same-Buffer rule changes, no branch/commit operations, and
report exact changed files, data flow, test results, warnings, and any remaining work.
