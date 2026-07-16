# Backend Request Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a strict Pydantic v2 contract, transitional request loader, and structured completeness validator for the current backend JSON without mapping or invoking algorithm objects.

**Architecture:** Keep the new ingress path isolated as `JSON/dict -> BackendRequestLoader -> BackendAlgorithmRequest -> BackendRequestCompletenessValidator -> BackendRequestValidationResult`. Schema validation distinguishes missing fields from explicit nulls and empty datasets; completeness validation reports business-null fields, state-aware empty order codes, dataset gaps, and broken references without filling or normalizing data.

**Tech Stack:** Python 3.13, Pydantic v2, standard-library `json`/`copy`/`pathlib`, pytest 8

---

## Execution constraints

- Do not modify `app/core/**`, `app/service/**`, `app/api/**`, `app/schemas/common_schema.py`, `app/schemas/request_schema.py`, `app/schemas/response_schema.py`, or `app/adapters/snapshot_adapter.py`.
- Preserve the user's existing dirty worktree changes in `app/service/cutline_service.py`, `docs/算法设计v2.md`, `debug_outputs/`, the stockout full-flow examples, and `tests/test_stockout_full_flow.py`.
- The user declined Git write approval during design. Each task therefore ends with a read-only diff/status checkpoint instead of `git add` or `git commit`. Do not request Git write approval again unless the user explicitly changes that preference.
- Follow red-green-refactor: write each test first, run it and observe the expected failure, then add only the implementation required for that test group.

## File map

| Path | Responsibility |
| --- | --- |
| `app/schemas/backend_request_schema.py` | Fourteen strict external request models and field constraints |
| `app/adapters/backend_request_loader.py` | UTF-8/JSON loading, deep copy, and two-field transitional cleanup |
| `app/adapters/backend_request_validator.py` | Structured issue/result models and all completeness rules |
| `app/schemas/__init__.py` | Public exports for the fourteen request models |
| `app/adapters/__init__.py` | Public exports for loader and completeness validation |
| `examples/backend_request_sample.json` | Small, closed, valid external request example |
| `tests/schemas/test_backend_request_schema.py` | Required/null/type/constraint/extra-field schema tests |
| `tests/adapters/test_backend_request_loader.py` | Deep-copy, transitional cleanup, file and error tests |
| `tests/adapters/test_backend_request_validator.py` | Empty/null/code/reference/route and real-shape completeness tests |

### Task 1: Add the closed example and strict backend request schema

**Files:**
- Create: `examples/backend_request_sample.json`
- Create: `tests/schemas/test_backend_request_schema.py`
- Create: `app/schemas/backend_request_schema.py`

- [ ] **Step 1: Create the small valid request example**

Create `examples/backend_request_sample.json` with this exact closed dataset. Do not include transitional `period_quantity` or `out_time`; the formal example represents the target Python contract.

```json
{
  "snapshot_meta": {
    "run_id": "RUN-001",
    "trigger_type": "manual",
    "workshop_id": "WS-01",
    "snapshot_time": "2026-07-14T08:00:00+08:00",
    "params_version": 1,
    "catalog_version": "catalog-1",
    "catalog_loaded_at": "2026-07-14T07:55:00+08:00",
    "degraded_flags": []
  },
  "machine_realtime": [
    {
      "machine_code": "M-01",
      "status": "RUNNING",
      "order_code": "O-01",
      "tangent_time": null,
      "input_quantity": 12,
      "output_quantity": 10.5,
      "completed_quantity": 100
    }
  ],
  "machine_master": [
    {
      "machine_code": "M-01",
      "machine_name": "机台一",
      "process_code": "P-01",
      "process_name": "工序一"
    }
  ],
  "machine_process_times": [
    {
      "machine_code": "M-01",
      "machine_name": "机台一",
      "product_code": "PROD-01",
      "product_name": "产品一",
      "proc_seconds": 90,
      "actual_capacity": 120.5
    }
  ],
  "workshops": [
    {
      "workshop_code": "WS-01",
      "workshop_name": "一车间"
    }
  ],
  "lines": [
    {
      "line_code": "L-01",
      "line_name": "一号线",
      "wafer_spec": "182",
      "workshop_code": "WS-01",
      "workshop_name": "一车间"
    }
  ],
  "machine_lines": [
    {
      "machine_code": "M-01",
      "machine_name": "机台一",
      "line_code": "L-01",
      "line_name": "一号线",
      "wafer_spec": "182"
    }
  ],
  "orders": [
    {
      "order_code": "O-01",
      "order_status": "RUNNING",
      "total_quantity": 1000,
      "piece_source": "A",
      "estimated_yield": "98%",
      "product_code": "PROD-01",
      "product_name": "产品一",
      "workshop_code": "WS-01",
      "workshop_name": "一车间",
      "produced_quantity": 100.5,
      "remaining_quantity": 899.5
    }
  ],
  "products": [
    {
      "product_code": "PROD-01",
      "product_name": "产品一",
      "wafer_size": "182",
      "source_grade": "A",
      "material_code": "MAT-01",
      "material_name": "物料一"
    }
  ],
  "process_routes": [
    {
      "process_code": "P-01",
      "process_name": "工序一",
      "sequence": 1,
      "cache_type": "BUFFER",
      "workshop_code": "WS-01",
      "workshop_name": "一车间",
      "loop_code": "LOOP-01",
      "loop_name": "主循环",
      "upstream_process_code": null,
      "upstream_process_name": null,
      "downstream_process_code": "P-02",
      "downstream_process_name": "工序二"
    },
    {
      "process_code": "P-02",
      "process_name": "工序二",
      "sequence": 2,
      "cache_type": "BUFFER",
      "workshop_code": "WS-01",
      "workshop_name": "一车间",
      "loop_code": "LOOP-01",
      "loop_name": "主循环",
      "upstream_process_code": "P-01",
      "upstream_process_name": "工序一",
      "downstream_process_code": null,
      "downstream_process_name": null
    }
  ],
  "buffer_realtime": [
    {
      "main_id": "MAIN-01",
      "buffer_code": "B-01",
      "bound_source_name": "AUTO-01",
      "current_quantity": 250,
      "current_utilization_rate": 0.25
    }
  ],
  "buffer_master": [
    {
      "buffer_code": "B-01",
      "buffer_name": "一号缓存",
      "buffer_type": "PROCESS",
      "buffer_type_title": "工序缓存",
      "max_capacity": 1000,
      "safety_low": 100,
      "served_process_codes": ["P-01", "P-02"],
      "served_process_names": ["工序一", "工序二"],
      "loop_code": "LOOP-01",
      "loop_name": "主循环"
    }
  ],
  "agv_relations": [
    {
      "buffer_code": "B-01",
      "machine_code": "M-01",
      "line_code": "L-01",
      "line_name": "一号线",
      "last_line_code": "L-00",
      "last_line_name": "原路线",
      "process_code": "P-01",
      "process_name": "工序一"
    }
  ]
}
```

- [ ] **Step 2: Write the schema tests before creating the schema module**

Create `tests/schemas/test_backend_request_schema.py`:

```python
import json
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.backend_request_schema import (
    BackendAgvRelation,
    BackendAlgorithmRequest,
    BackendBufferMaster,
    BackendBufferRealtime,
    BackendLine,
    BackendMachineLine,
    BackendMachineMaster,
    BackendMachineProcessTime,
    BackendMachineRealtime,
    BackendOrder,
    BackendProcessRoute,
    BackendProduct,
    BackendSnapshotMeta,
    BackendWorkshop,
)


SAMPLE_PATH = (
    Path(__file__).resolve().parents[2] / "examples" / "backend_request_sample.json"
)

PUBLIC_MODELS = [
    BackendSnapshotMeta,
    BackendMachineRealtime,
    BackendMachineMaster,
    BackendMachineProcessTime,
    BackendWorkshop,
    BackendLine,
    BackendMachineLine,
    BackendOrder,
    BackendProduct,
    BackendProcessRoute,
    BackendBufferRealtime,
    BackendBufferMaster,
    BackendAgvRelation,
    BackendAlgorithmRequest,
]


def sample_payload() -> dict:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


def test_complete_request_parses_datetimes_and_numeric_types():
    request = BackendAlgorithmRequest.model_validate(sample_payload())

    assert isinstance(request.snapshot_meta.snapshot_time, datetime)
    assert isinstance(request.snapshot_meta.catalog_loaded_at, datetime)
    assert request.machine_realtime[0].tangent_time is None
    assert request.machine_realtime[0].input_quantity == 12.0
    assert request.machine_realtime[0].output_quantity == 10.5
    assert request.machine_process_times[0].proc_seconds == 90.0


def test_all_public_models_forbid_unknown_fields():
    assert all(model.model_config.get("extra") == "forbid" for model in PUBLIC_MODELS)


def test_unknown_top_level_field_is_rejected():
    payload = sample_payload()
    payload["unexpected"] = True

    with pytest.raises(ValidationError) as error:
        BackendAlgorithmRequest.model_validate(payload)

    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_unknown_nested_field_is_rejected():
    payload = sample_payload()
    payload["machine_realtime"][0]["equipment_code"] = "legacy"

    with pytest.raises(ValidationError) as error:
        BackendAlgorithmRequest.model_validate(payload)

    assert error.value.errors()[0]["loc"] == (
        "machine_realtime",
        0,
        "equipment_code",
    )


def test_missing_top_level_dataset_is_rejected_but_empty_dataset_is_structural():
    missing = sample_payload()
    del missing["orders"]

    with pytest.raises(ValidationError) as error:
        BackendAlgorithmRequest.model_validate(missing)

    assert error.value.errors()[0]["loc"] == ("orders",)

    empty = sample_payload()
    empty["orders"] = []
    assert BackendAlgorithmRequest.model_validate(empty).orders == []


@pytest.mark.parametrize(
    ("dataset", "field"),
    [
        ("workshops", "workshop_name"),
        ("buffer_realtime", "main_id"),
        ("agv_relations", "buffer_code"),
        ("agv_relations", "line_name"),
        ("agv_relations", "last_line_code"),
        ("agv_relations", "last_line_name"),
        ("agv_relations", "process_code"),
        ("agv_relations", "process_name"),
    ],
)
def test_compatibility_nullable_fields_require_presence(dataset: str, field: str):
    explicit_null = sample_payload()
    explicit_null[dataset][0][field] = None
    BackendAlgorithmRequest.model_validate(explicit_null)

    missing = sample_payload()
    del missing[dataset][0][field]
    with pytest.raises(ValidationError) as error:
        BackendAlgorithmRequest.model_validate(missing)

    assert error.value.errors()[0]["type"] == "missing"


def test_tangent_time_requires_presence_and_accepts_null():
    payload = sample_payload()
    BackendAlgorithmRequest.model_validate(payload)

    del payload["machine_realtime"][0]["tangent_time"]
    with pytest.raises(ValidationError) as error:
        BackendAlgorithmRequest.model_validate(payload)

    assert error.value.errors()[0]["loc"] == (
        "machine_realtime",
        0,
        "tangent_time",
    )


def test_route_edge_fields_require_presence_and_accept_null():
    payload = sample_payload()
    request = BackendAlgorithmRequest.model_validate(payload)

    assert request.process_routes[0].upstream_process_code is None
    assert request.process_routes[-1].downstream_process_code is None

    del payload["process_routes"][0]["upstream_process_name"]
    with pytest.raises(ValidationError) as error:
        BackendAlgorithmRequest.model_validate(payload)

    assert error.value.errors()[0]["type"] == "missing"


@pytest.mark.parametrize(
    ("dataset", "field", "invalid_value"),
    [
        ("machine_realtime", "input_quantity", -1),
        ("machine_realtime", "output_quantity", -0.1),
        ("machine_realtime", "completed_quantity", -1),
        ("machine_process_times", "proc_seconds", 0),
        ("machine_process_times", "actual_capacity", 0),
        ("orders", "total_quantity", -1),
        ("orders", "produced_quantity", -1),
        ("orders", "remaining_quantity", -1),
        ("buffer_realtime", "current_quantity", -1),
        ("buffer_realtime", "current_utilization_rate", -0.1),
        ("buffer_master", "max_capacity", 0),
        ("buffer_master", "safety_low", -1),
    ],
)
def test_numeric_boundaries_are_enforced(
    dataset: str,
    field: str,
    invalid_value: float,
):
    payload = sample_payload()
    payload[dataset][0][field] = invalid_value

    with pytest.raises(ValidationError):
        BackendAlgorithmRequest.model_validate(payload)


@pytest.mark.parametrize("field", ["served_process_codes", "served_process_names"])
def test_served_process_lists_cannot_be_empty(field: str):
    payload = sample_payload()
    payload["buffer_master"][0][field] = []

    with pytest.raises(ValidationError):
        BackendAlgorithmRequest.model_validate(payload)


def test_proc_seconds_stays_in_seconds():
    request = BackendAlgorithmRequest.model_validate(sample_payload())

    assert request.machine_process_times[0].proc_seconds == 90.0
```

- [ ] **Step 3: Run the schema test and confirm the red state**

Run:

```powershell
pytest tests/schemas/test_backend_request_schema.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.schemas.backend_request_schema'`.

- [ ] **Step 4: Implement the fourteen request models**

Create `app/schemas/backend_request_schema.py`:

```python
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _BackendRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BackendSnapshotMeta(_BackendRequestModel):
    run_id: str
    trigger_type: str
    workshop_id: str
    snapshot_time: datetime
    params_version: int
    catalog_version: str
    catalog_loaded_at: datetime
    degraded_flags: list[str]


class BackendMachineRealtime(_BackendRequestModel):
    machine_code: str
    status: str
    order_code: str
    tangent_time: datetime | None
    input_quantity: float = Field(ge=0)
    output_quantity: float = Field(ge=0)
    completed_quantity: float = Field(ge=0)


class BackendMachineMaster(_BackendRequestModel):
    machine_code: str
    machine_name: str
    process_code: str
    process_name: str


class BackendMachineProcessTime(_BackendRequestModel):
    machine_code: str
    machine_name: str
    product_code: str
    product_name: str
    proc_seconds: float = Field(gt=0)
    actual_capacity: float = Field(gt=0)


class BackendWorkshop(_BackendRequestModel):
    workshop_code: str
    workshop_name: str | None


class BackendLine(_BackendRequestModel):
    line_code: str
    line_name: str
    wafer_spec: str
    workshop_code: str
    workshop_name: str


class BackendMachineLine(_BackendRequestModel):
    machine_code: str
    machine_name: str
    line_code: str
    line_name: str
    wafer_spec: str


class BackendOrder(_BackendRequestModel):
    order_code: str
    order_status: str
    total_quantity: float = Field(ge=0)
    piece_source: str
    estimated_yield: str
    product_code: str
    product_name: str
    workshop_code: str
    workshop_name: str
    produced_quantity: float = Field(ge=0)
    remaining_quantity: float = Field(ge=0)


class BackendProduct(_BackendRequestModel):
    product_code: str
    product_name: str
    wafer_size: str
    source_grade: str
    material_code: str
    material_name: str


class BackendProcessRoute(_BackendRequestModel):
    process_code: str
    process_name: str
    sequence: int
    cache_type: str
    workshop_code: str
    workshop_name: str
    loop_code: str
    loop_name: str
    upstream_process_code: str | None
    upstream_process_name: str | None
    downstream_process_code: str | None
    downstream_process_name: str | None


class BackendBufferRealtime(_BackendRequestModel):
    main_id: str | None
    buffer_code: str
    bound_source_name: str
    current_quantity: float = Field(ge=0)
    current_utilization_rate: float = Field(ge=0)


class BackendBufferMaster(_BackendRequestModel):
    buffer_code: str
    buffer_name: str
    buffer_type: str
    buffer_type_title: str
    max_capacity: float = Field(gt=0)
    safety_low: float = Field(ge=0)
    served_process_codes: list[str] = Field(min_length=1)
    served_process_names: list[str] = Field(min_length=1)
    loop_code: str
    loop_name: str


class BackendAgvRelation(_BackendRequestModel):
    buffer_code: str | None
    machine_code: str
    line_code: str
    line_name: str | None
    last_line_code: str | None
    last_line_name: str | None
    process_code: str | None
    process_name: str | None


class BackendAlgorithmRequest(_BackendRequestModel):
    snapshot_meta: BackendSnapshotMeta
    machine_realtime: list[BackendMachineRealtime]
    machine_master: list[BackendMachineMaster]
    machine_process_times: list[BackendMachineProcessTime]
    workshops: list[BackendWorkshop]
    lines: list[BackendLine]
    machine_lines: list[BackendMachineLine]
    orders: list[BackendOrder]
    products: list[BackendProduct]
    process_routes: list[BackendProcessRoute]
    buffer_realtime: list[BackendBufferRealtime]
    buffer_master: list[BackendBufferMaster]
    agv_relations: list[BackendAgvRelation]
```

- [ ] **Step 5: Run the schema tests and confirm green**

Run:

```powershell
pytest tests/schemas/test_backend_request_schema.py -q
```

Expected: all tests in the file pass.

- [ ] **Step 6: Record the read-only checkpoint**

Run:

```powershell
git status --short
```

Expected new paths: `app/schemas/backend_request_schema.py`, `examples/backend_request_sample.json`, and `tests/schemas/test_backend_request_schema.py`; pre-existing dirty paths remain untouched.

### Task 2: Add the deep-copy transitional Loader

**Files:**
- Create: `tests/adapters/test_backend_request_loader.py`
- Create: `app/adapters/backend_request_loader.py`
- Read: `examples/backend_request_sample.json`

- [ ] **Step 1: Write Loader tests for cleanup, immutability, and errors**

Create `tests/adapters/test_backend_request_loader.py`:

```python
import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.adapters.backend_request_loader import (
    BackendRequestLoadError,
    BackendRequestLoader,
)
from app.schemas.backend_request_schema import BackendAlgorithmRequest


SAMPLE_PATH = (
    Path(__file__).resolve().parents[2] / "examples" / "backend_request_sample.json"
)


def sample_payload() -> dict:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


def test_load_dict_returns_model_without_mutating_nested_payload():
    payload = sample_payload()
    payload["machine_realtime"][0]["period_quantity"] = 10
    payload["machine_realtime"][0]["out_time"] = "2026-07-14T08:30:00+08:00"
    original = deepcopy(payload)

    request = BackendRequestLoader().load_dict(payload)

    assert isinstance(request, BackendAlgorithmRequest)
    assert payload == original
    assert "period_quantity" not in request.machine_realtime[0].model_dump()
    assert "out_time" not in request.machine_realtime[0].model_dump()


def test_cleanup_applies_to_every_machine_realtime_record():
    payload = sample_payload()
    second = deepcopy(payload["machine_realtime"][0])
    second["machine_code"] = "M-02"
    payload["machine_realtime"].append(second)
    for record in payload["machine_realtime"]:
        record["period_quantity"] = 0
        record["out_time"] = "2026-07-14T08:30:00+08:00"

    request = BackendRequestLoader().load_dict(payload)

    assert len(request.machine_realtime) == 2
    assert all(
        "period_quantity" not in record.model_dump()
        and "out_time" not in record.model_dump()
        for record in request.machine_realtime
    )


def test_loader_accepts_formal_payload_when_transitional_fields_are_absent():
    request = BackendRequestLoader().load_dict(sample_payload())

    assert request.machine_realtime[0].machine_code == "M-01"


def test_loader_does_not_delete_same_named_field_outside_machine_realtime():
    payload = sample_payload()
    payload["workshops"][0]["out_time"] = "must-not-be-cleaned"

    with pytest.raises(ValidationError) as error:
        BackendRequestLoader().load_dict(payload)

    assert error.value.errors()[0]["loc"] == ("workshops", 0, "out_time")


def test_loader_rejects_other_unknown_machine_field():
    payload = sample_payload()
    payload["machine_realtime"][0]["equipment_code"] = "legacy"

    with pytest.raises(ValidationError):
        BackendRequestLoader().load_dict(payload)


def test_load_json_file_reads_utf8_json(tmp_path: Path):
    path = tmp_path / "后端请求.json"
    path.write_text(
        json.dumps(sample_payload(), ensure_ascii=False),
        encoding="utf-8",
    )

    request = BackendRequestLoader().load_json_file(path)

    assert request.machine_master[0].machine_name == "机台一"


def test_missing_file_raises_load_error_with_path_and_reason(tmp_path: Path):
    path = tmp_path / "missing.json"

    with pytest.raises(BackendRequestLoadError) as error:
        BackendRequestLoader().load_json_file(path)

    assert str(path) in str(error.value)
    assert error.value.__cause__ is not None


def test_unreadable_path_raises_load_error_with_path_and_reason(tmp_path: Path):
    with pytest.raises(BackendRequestLoadError) as error:
        BackendRequestLoader().load_json_file(tmp_path)

    assert str(tmp_path) in str(error.value)
    assert error.value.__cause__ is not None


def test_invalid_utf8_raises_load_error(tmp_path: Path):
    path = tmp_path / "invalid-utf8.json"
    path.write_bytes(b"\xff\xfe")

    with pytest.raises(BackendRequestLoadError) as error:
        BackendRequestLoader().load_json_file(path)

    assert str(path) in str(error.value)
    assert isinstance(error.value.__cause__, UnicodeDecodeError)


def test_invalid_json_raises_load_error(tmp_path: Path):
    path = tmp_path / "invalid.json"
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(BackendRequestLoadError) as error:
        BackendRequestLoader().load_json_file(path)

    assert str(path) in str(error.value)
    assert isinstance(error.value.__cause__, json.JSONDecodeError)


def test_schema_validation_error_is_not_wrapped(tmp_path: Path):
    payload = sample_payload()
    del payload["orders"]
    path = tmp_path / "schema-invalid.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError):
        BackendRequestLoader().load_json_file(path)


def test_valid_json_with_non_object_root_raises_validation_error(tmp_path: Path):
    path = tmp_path / "array.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValidationError):
        BackendRequestLoader().load_json_file(path)
```

- [ ] **Step 2: Run Loader tests and confirm the red state**

Run:

```powershell
pytest tests/adapters/test_backend_request_loader.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.adapters.backend_request_loader'`.

- [ ] **Step 3: Implement the Loader and narrow error boundary**

Create `app/adapters/backend_request_loader.py`:

```python
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.schemas.backend_request_schema import BackendAlgorithmRequest


class BackendRequestLoadError(ValueError):
    """Raised when a backend request file cannot be read or decoded as JSON."""


class BackendRequestLoader:
    """Load the external backend contract without mapping algorithm objects."""

    def load_dict(self, payload: dict) -> BackendAlgorithmRequest:
        return self._validate_cleaned_payload(payload)

    def load_json_file(self, file_path: str | Path) -> BackendAlgorithmRequest:
        path = Path(file_path)
        try:
            with path.open(encoding="utf-8") as file:
                payload: Any = json.load(file)
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise BackendRequestLoadError(
                f"Failed to load backend request from {path}: {error}"
            ) from error

        return self._validate_cleaned_payload(payload)

    @staticmethod
    def _validate_cleaned_payload(payload: Any) -> BackendAlgorithmRequest:
        cleaned = deepcopy(payload)
        if isinstance(cleaned, dict):
            machine_realtime = cleaned.get("machine_realtime")
            if isinstance(machine_realtime, list):
                for record in machine_realtime:
                    if isinstance(record, dict):
                        record.pop("period_quantity", None)
                        record.pop("out_time", None)

        return BackendAlgorithmRequest.model_validate(cleaned)
```

- [ ] **Step 4: Run Loader and schema tests together**

Run:

```powershell
pytest tests/schemas/test_backend_request_schema.py tests/adapters/test_backend_request_loader.py -q
```

Expected: all tests in both files pass; Pydantic errors remain unwrapped.

- [ ] **Step 5: Record the transitional-cleanup checkpoint**

Run:

```powershell
rg -n "period_quantity|out_time" app/schemas/backend_request_schema.py app/adapters/backend_request_loader.py
```

Expected: no match in the Schema file; exactly the two `record.pop` cleanup calls in the Loader file.

### Task 3: Build structured completeness results and basic business rules

**Files:**
- Create: `tests/adapters/test_backend_request_validator.py`
- Create: `app/adapters/backend_request_validator.py`
- Read: `app/schemas/backend_request_schema.py`

- [ ] **Step 1: Write failing tests for empty datasets, business nulls, and state-aware codes**

Create `tests/adapters/test_backend_request_validator.py`:

```python
from pathlib import Path

import pytest

from app.adapters.backend_request_loader import BackendRequestLoader
from app.adapters.backend_request_validator import (
    BackendRequestCompletenessValidator,
    BackendRequestValidationResult,
    BackendValidationIssue,
)


SAMPLE_PATH = (
    Path(__file__).resolve().parents[2] / "examples" / "backend_request_sample.json"
)

CRITICAL_DATASETS = [
    "machine_realtime",
    "machine_master",
    "machine_process_times",
    "workshops",
    "orders",
    "products",
    "process_routes",
    "buffer_realtime",
    "buffer_master",
]


def valid_request():
    return BackendRequestLoader().load_json_file(SAMPLE_PATH)


def matching_issues(result, dataset: str, field: str | None):
    return [
        issue
        for issue in result.issues
        if issue.dataset == dataset and issue.field == field
    ]


def test_closed_request_is_complete():
    result = BackendRequestCompletenessValidator().validate(valid_request())

    assert result == BackendRequestValidationResult(valid=True, issues=[])


def test_validation_result_models_forbid_extra_fields():
    assert BackendValidationIssue.model_config.get("extra") == "forbid"
    assert BackendRequestValidationResult.model_config.get("extra") == "forbid"


@pytest.mark.parametrize("dataset", CRITICAL_DATASETS)
def test_each_empty_critical_dataset_is_reported(dataset: str):
    request = valid_request()
    setattr(request, dataset, [])

    result = BackendRequestCompletenessValidator().validate(request)

    issues = matching_issues(result, dataset, None)
    assert result.valid is False
    assert any(issue.code == "empty_dataset" for issue in issues)


@pytest.mark.parametrize(
    ("dataset", "field"),
    [
        ("workshops", "workshop_name"),
        ("buffer_realtime", "main_id"),
        ("agv_relations", "buffer_code"),
        ("agv_relations", "line_name"),
        ("agv_relations", "last_line_code"),
        ("agv_relations", "last_line_name"),
        ("agv_relations", "process_code"),
        ("agv_relations", "process_name"),
    ],
)
def test_compatibility_null_business_field_is_reported(dataset: str, field: str):
    request = valid_request()
    setattr(getattr(request, dataset)[0], field, None)

    result = BackendRequestCompletenessValidator().validate(request)

    issues = matching_issues(result, dataset, field)
    assert result.valid is False
    assert [issue.code for issue in issues] == ["null_field"]


def test_null_tangent_time_is_semantically_valid():
    request = valid_request()
    request.machine_realtime[0].tangent_time = None

    result = BackendRequestCompletenessValidator().validate(request)

    assert matching_issues(result, "machine_realtime", "tangent_time") == []


@pytest.mark.parametrize(
    ("status", "should_block"),
    [
        ("运行", True),
        ("running", True),
        ("RUNNING", True),
        ("Running", True),
        ("异常", False),
        ("stopped", False),
        ("unrecognized", False),
    ],
)
def test_empty_order_code_depends_on_machine_status(status: str, should_block: bool):
    request = valid_request()
    request.machine_realtime[0].status = status
    request.machine_realtime[0].order_code = ""

    result = BackendRequestCompletenessValidator().validate(request)

    issues = matching_issues(result, "machine_realtime", "order_code")
    assert (len(issues) == 1) is should_block
    if should_block:
        assert issues[0].code == "empty_code"
        assert result.valid is False


def test_other_empty_scalar_code_is_reported():
    request = valid_request()
    request.products[0].material_code = ""

    result = BackendRequestCompletenessValidator().validate(request)

    issues = matching_issues(result, "products", "material_code")
    assert [issue.code for issue in issues] == ["empty_code"]


def test_empty_served_process_code_element_is_reported():
    request = valid_request()
    request.buffer_master[0].served_process_codes[0] = ""

    result = BackendRequestCompletenessValidator().validate(request)

    issues = matching_issues(
        result,
        "buffer_master",
        "served_process_codes[0]",
    )
    assert [issue.code for issue in issues] == ["empty_code"]


def test_basic_rules_accumulate_instead_of_returning_early():
    request = valid_request()
    request.machine_master = []
    request.workshops[0].workshop_name = None
    request.products[0].material_code = ""

    result = BackendRequestCompletenessValidator().validate(request)

    assert result.valid is False
    assert {issue.code for issue in result.issues} >= {
        "empty_dataset",
        "null_field",
        "empty_code",
    }
    assert all(
        set(issue.model_dump())
        == {"code", "dataset", "field", "record_key", "message"}
        for issue in result.issues
    )
```

- [ ] **Step 2: Run the basic validator tests and confirm the red state**

Run:

```powershell
pytest tests/adapters/test_backend_request_validator.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.adapters.backend_request_validator'`.

- [ ] **Step 3: Implement result models and the three basic rule groups**

Create `app/adapters/backend_request_validator.py`:

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from app.schemas.backend_request_schema import BackendAlgorithmRequest


class _BackendValidationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BackendValidationIssue(_BackendValidationModel):
    code: str
    dataset: str
    field: str | None
    record_key: str | None
    message: str


class BackendRequestValidationResult(_BackendValidationModel):
    valid: bool
    issues: list[BackendValidationIssue]


_CRITICAL_DATASETS = (
    "machine_realtime",
    "machine_master",
    "machine_process_times",
    "workshops",
    "orders",
    "products",
    "process_routes",
    "buffer_realtime",
    "buffer_master",
)

_REQUIRED_NULL_FIELDS = {
    "workshops": ("workshop_name",),
    "buffer_realtime": ("main_id",),
    "agv_relations": (
        "buffer_code",
        "line_name",
        "last_line_code",
        "last_line_name",
        "process_code",
        "process_name",
    ),
}

_CODE_FIELDS = {
    "machine_realtime": ("machine_code",),
    "machine_master": ("machine_code", "process_code"),
    "machine_process_times": ("machine_code", "product_code"),
    "workshops": ("workshop_code",),
    "lines": ("line_code", "workshop_code"),
    "machine_lines": ("machine_code", "line_code"),
    "orders": ("order_code", "product_code", "workshop_code"),
    "products": ("product_code", "material_code"),
    "process_routes": (
        "process_code",
        "workshop_code",
        "loop_code",
        "upstream_process_code",
        "downstream_process_code",
    ),
    "buffer_realtime": ("buffer_code",),
    "buffer_master": ("buffer_code", "loop_code"),
    "agv_relations": (
        "buffer_code",
        "machine_code",
        "line_code",
        "last_line_code",
        "process_code",
    ),
}

_RECORD_KEY_FIELDS = {
    "machine_realtime": ("machine_code",),
    "machine_master": ("machine_code",),
    "machine_process_times": ("machine_code", "product_code"),
    "workshops": ("workshop_code",),
    "lines": ("line_code",),
    "machine_lines": ("machine_code", "line_code"),
    "orders": ("order_code",),
    "products": ("product_code",),
    "process_routes": ("workshop_code", "loop_code", "process_code"),
    "buffer_realtime": ("buffer_code",),
    "buffer_master": ("buffer_code",),
    "agv_relations": ("machine_code", "line_code"),
}


class BackendRequestCompletenessValidator:
    def validate(
        self,
        request: BackendAlgorithmRequest,
    ) -> BackendRequestValidationResult:
        issues: list[BackendValidationIssue] = []
        self._validate_empty_datasets(request, issues)
        self._validate_required_nulls(request, issues)
        self._validate_empty_codes(request, issues)
        return BackendRequestValidationResult(valid=not issues, issues=issues)

    def _validate_empty_datasets(
        self,
        request: BackendAlgorithmRequest,
        issues: list[BackendValidationIssue],
    ) -> None:
        for dataset in _CRITICAL_DATASETS:
            if not getattr(request, dataset):
                issues.append(
                    self._issue(
                        code="empty_dataset",
                        dataset=dataset,
                        field=None,
                        record_key=None,
                        message=f"{dataset} must not be empty",
                    )
                )

    def _validate_required_nulls(
        self,
        request: BackendAlgorithmRequest,
        issues: list[BackendValidationIssue],
    ) -> None:
        for dataset, fields in _REQUIRED_NULL_FIELDS.items():
            for index, record in enumerate(getattr(request, dataset)):
                for field in fields:
                    if getattr(record, field) is None:
                        issues.append(
                            self._issue(
                                code="null_field",
                                dataset=dataset,
                                field=field,
                                record_key=self._record_key(dataset, record, index),
                                message=f"{dataset}.{field} must not be null",
                            )
                        )

    def _validate_empty_codes(
        self,
        request: BackendAlgorithmRequest,
        issues: list[BackendValidationIssue],
    ) -> None:
        for dataset, fields in _CODE_FIELDS.items():
            for index, record in enumerate(getattr(request, dataset)):
                for field in fields:
                    if getattr(record, field) == "":
                        issues.append(
                            self._issue(
                                code="empty_code",
                                dataset=dataset,
                                field=field,
                                record_key=self._record_key(dataset, record, index),
                                message=f"{dataset}.{field} must not be an empty string",
                            )
                        )

        for index, machine in enumerate(request.machine_realtime):
            if machine.order_code == "" and self._is_running(machine.status):
                issues.append(
                    self._issue(
                        code="empty_code",
                        dataset="machine_realtime",
                        field="order_code",
                        record_key=self._record_key(
                            "machine_realtime",
                            machine,
                            index,
                        ),
                        message="running machine order_code must not be empty",
                    )
                )

        for index, buffer in enumerate(request.buffer_master):
            for code_index, process_code in enumerate(buffer.served_process_codes):
                if process_code == "":
                    field = f"served_process_codes[{code_index}]"
                    issues.append(
                        self._issue(
                            code="empty_code",
                            dataset="buffer_master",
                            field=field,
                            record_key=self._record_key(
                                "buffer_master",
                                buffer,
                                index,
                            ),
                            message=f"buffer_master.{field} must not be empty",
                        )
                    )

    @staticmethod
    def _is_running(status: str) -> bool:
        return status == "运行" or status.casefold() == "running"

    @staticmethod
    def _record_key(dataset: str, record: Any, index: int) -> str:
        values = [
            str(value)
            for field in _RECORD_KEY_FIELDS[dataset]
            if (value := getattr(record, field)) not in (None, "")
        ]
        return "|".join(values) if values else f"index:{index}"

    @staticmethod
    def _issue(
        *,
        code: str,
        dataset: str,
        field: str | None,
        record_key: str | None,
        message: str,
    ) -> BackendValidationIssue:
        return BackendValidationIssue(
            code=code,
            dataset=dataset,
            field=field,
            record_key=record_key,
            message=message,
        )
```

- [ ] **Step 4: Run the basic validator tests and confirm green**

Run:

```powershell
pytest tests/adapters/test_backend_request_validator.py -q
```

Expected: all currently defined validator tests pass.

- [ ] **Step 5: Record the basic-rule checkpoint**

Run:

```powershell
git status --short
```

Expected: only the planned backend request files are newly added; the known pre-existing dirty paths remain unchanged.

### Task 4: Add references, route grouping, issue de-duplication, and value checks

**Files:**
- Modify: `tests/adapters/test_backend_request_validator.py`
- Modify: `app/adapters/backend_request_validator.py`

- [ ] **Step 1: Append failing relationship and route tests**

Append the following tests to `tests/adapters/test_backend_request_validator.py`:

```python
@pytest.mark.parametrize(
    ("dataset", "field", "missing_value"),
    [
        ("machine_realtime", "machine_code", "M-MISSING"),
        ("machine_realtime", "order_code", "O-MISSING"),
        ("orders", "product_code", "PROD-MISSING"),
        ("orders", "workshop_code", "WS-MISSING"),
        ("machine_process_times", "machine_code", "M-MISSING"),
        ("machine_process_times", "product_code", "PROD-MISSING"),
        ("buffer_realtime", "buffer_code", "B-MISSING"),
    ],
)
def test_missing_reference_is_reported(
    dataset: str,
    field: str,
    missing_value: str,
):
    request = valid_request()
    setattr(getattr(request, dataset)[0], field, missing_value)

    result = BackendRequestCompletenessValidator().validate(request)

    issues = matching_issues(result, dataset, field)
    assert any(issue.code == "missing_reference" for issue in issues)


def test_nonempty_order_code_is_checked_even_for_non_running_machine():
    request = valid_request()
    request.machine_realtime[0].status = "异常"
    request.machine_realtime[0].order_code = "O-MISSING"

    result = BackendRequestCompletenessValidator().validate(request)

    issues = matching_issues(result, "machine_realtime", "order_code")
    assert [issue.code for issue in issues] == ["missing_reference"]


def test_empty_running_order_has_one_root_cause_issue_not_missing_reference():
    request = valid_request()
    request.machine_realtime[0].status = "运行"
    request.machine_realtime[0].order_code = ""

    result = BackendRequestCompletenessValidator().validate(request)

    issues = matching_issues(result, "machine_realtime", "order_code")
    assert [issue.code for issue in issues] == ["empty_code"]


def test_duplicate_sequence_is_scoped_to_workshop_and_loop():
    request = valid_request()
    request.process_routes[1].sequence = 1

    result = BackendRequestCompletenessValidator().validate(request)

    issues = matching_issues(result, "process_routes", "sequence")
    assert [issue.code for issue in issues] == ["duplicate_sequence"]


def test_same_sequence_in_a_different_loop_is_allowed():
    request = valid_request()
    other_loop = request.process_routes[0].model_copy(deep=True)
    other_loop.process_code = "Q-01"
    other_loop.process_name = "其他工序"
    other_loop.loop_code = "LOOP-02"
    other_loop.loop_name = "其他循环"
    other_loop.upstream_process_code = None
    other_loop.upstream_process_name = None
    other_loop.downstream_process_code = None
    other_loop.downstream_process_name = None
    request.process_routes.append(other_loop)

    result = BackendRequestCompletenessValidator().validate(request)

    assert matching_issues(result, "process_routes", "sequence") == []


def test_only_group_edges_allow_null_route_fields():
    request = valid_request()
    third = request.process_routes[1].model_copy(deep=True)
    third.process_code = "P-03"
    third.process_name = "工序三"
    third.sequence = 3
    third.upstream_process_code = "P-02"
    third.upstream_process_name = "工序二"
    third.downstream_process_code = None
    third.downstream_process_name = None
    request.process_routes[1].downstream_process_code = "P-03"
    request.process_routes[1].downstream_process_name = "工序三"
    request.process_routes[1].upstream_process_code = None
    request.process_routes[1].upstream_process_name = None
    request.process_routes.append(third)

    result = BackendRequestCompletenessValidator().validate(request)

    code_issues = matching_issues(
        result,
        "process_routes",
        "upstream_process_code",
    )
    name_issues = matching_issues(
        result,
        "process_routes",
        "upstream_process_name",
    )
    assert [issue.code for issue in code_issues] == ["null_field"]
    assert [issue.code for issue in name_issues] == ["null_field"]


def test_null_middle_route_code_does_not_also_report_missing_reference():
    request = valid_request()
    third = request.process_routes[1].model_copy(deep=True)
    third.process_code = "P-03"
    third.process_name = "工序三"
    third.sequence = 3
    third.upstream_process_code = "P-02"
    third.upstream_process_name = "工序二"
    request.process_routes[1].downstream_process_code = "P-03"
    request.process_routes[1].downstream_process_name = "工序三"
    request.process_routes[1].upstream_process_code = None
    request.process_routes.append(third)

    result = BackendRequestCompletenessValidator().validate(request)

    issues = matching_issues(
        result,
        "process_routes",
        "upstream_process_code",
    )
    assert [issue.code for issue in issues] == ["null_field"]


def test_route_reference_cannot_be_satisfied_by_another_group():
    request = valid_request()
    other_loop = request.process_routes[0].model_copy(deep=True)
    other_loop.process_code = "Q-01"
    other_loop.process_name = "其他工序"
    other_loop.loop_code = "LOOP-02"
    other_loop.loop_name = "其他循环"
    other_loop.upstream_process_code = None
    other_loop.upstream_process_name = None
    other_loop.downstream_process_code = None
    other_loop.downstream_process_name = None
    request.process_routes.append(other_loop)
    request.process_routes[0].downstream_process_code = "Q-01"
    request.process_routes[0].downstream_process_name = "其他工序"

    result = BackendRequestCompletenessValidator().validate(request)

    issues = matching_issues(
        result,
        "process_routes",
        "downstream_process_code",
    )
    assert [issue.code for issue in issues] == ["missing_reference"]


def test_served_process_must_exist_in_the_same_loop():
    request = valid_request()
    request.buffer_master[0].served_process_codes[0] = "P-MISSING"

    result = BackendRequestCompletenessValidator().validate(request)

    issues = matching_issues(
        result,
        "buffer_master",
        "served_process_codes[0]",
    )
    assert [issue.code for issue in issues] == ["missing_reference"]


def test_validator_defensively_checks_max_capacity():
    request = valid_request()
    request.buffer_master[0].max_capacity = 0

    result = BackendRequestCompletenessValidator().validate(request)

    issues = matching_issues(result, "buffer_master", "max_capacity")
    assert [issue.code for issue in issues] == ["invalid_value"]
```

- [ ] **Step 2: Run the new relationship tests and confirm the red state**

Run:

```powershell
pytest tests/adapters/test_backend_request_validator.py -q
```

Expected: the earlier basic tests pass; the new reference, duplicate-sequence, route-edge, served-process, and capacity tests fail because those rules are not yet called.

- [ ] **Step 3: Add relationship metadata and route grouping support**

At the top of `app/adapters/backend_request_validator.py`, add this import before `typing`:

```python
from collections import defaultdict
```

Add this constant after `_RECORD_KEY_FIELDS`:

```python
_RELATIONSHIPS = (
    ("machine_realtime", "machine_code", "machine_master", "machine_code"),
    ("machine_realtime", "order_code", "orders", "order_code"),
    ("orders", "product_code", "products", "product_code"),
    ("orders", "workshop_code", "workshops", "workshop_code"),
    (
        "machine_process_times",
        "machine_code",
        "machine_master",
        "machine_code",
    ),
    (
        "machine_process_times",
        "product_code",
        "products",
        "product_code",
    ),
    ("buffer_realtime", "buffer_code", "buffer_master", "buffer_code"),
)
```

Replace `BackendRequestCompletenessValidator.validate` with this complete method so rule order remains deterministic:

```python
    def validate(
        self,
        request: BackendAlgorithmRequest,
    ) -> BackendRequestValidationResult:
        issues: list[BackendValidationIssue] = []
        self._validate_empty_datasets(request, issues)
        self._validate_required_nulls(request, issues)
        self._validate_empty_codes(request, issues)
        self._validate_references(request, issues)
        self._validate_routes(request, issues)
        self._validate_served_processes(request, issues)
        self._validate_capacity(request, issues)
        return BackendRequestValidationResult(valid=not issues, issues=issues)
```

- [ ] **Step 4: Add the exact reference and route rule methods**

Insert these methods in `BackendRequestCompletenessValidator` immediately before `_is_running`:

```python
    def _validate_references(
        self,
        request: BackendAlgorithmRequest,
        issues: list[BackendValidationIssue],
    ) -> None:
        for source_dataset, source_field, target_dataset, target_field in _RELATIONSHIPS:
            targets = {
                value
                for record in getattr(request, target_dataset)
                if (value := getattr(record, target_field)) not in (None, "")
            }
            for index, record in enumerate(getattr(request, source_dataset)):
                value = getattr(record, source_field)
                if value in (None, ""):
                    continue
                if value not in targets:
                    issues.append(
                        self._issue(
                            code="missing_reference",
                            dataset=source_dataset,
                            field=source_field,
                            record_key=self._record_key(
                                source_dataset,
                                record,
                                index,
                            ),
                            message=(
                                f"{source_dataset}.{source_field}={value!r} "
                                f"was not found in {target_dataset}.{target_field}"
                            ),
                        )
                    )

    def _validate_routes(
        self,
        request: BackendAlgorithmRequest,
        issues: list[BackendValidationIssue],
    ) -> None:
        grouped: dict[tuple[str, str], list[tuple[int, Any]]] = defaultdict(list)
        for index, route in enumerate(request.process_routes):
            grouped[(route.workshop_code, route.loop_code)].append((index, route))

        for (workshop_code, loop_code), indexed_routes in grouped.items():
            by_sequence: dict[int, list[Any]] = defaultdict(list)
            for _, route in indexed_routes:
                by_sequence[route.sequence].append(route)

            for sequence, duplicates in by_sequence.items():
                if len(duplicates) > 1:
                    issues.append(
                        self._issue(
                            code="duplicate_sequence",
                            dataset="process_routes",
                            field="sequence",
                            record_key=(
                                f"{workshop_code}|{loop_code}|sequence:{sequence}"
                            ),
                            message=(
                                "process_routes.sequence must be unique within "
                                f"({workshop_code}, {loop_code})"
                            ),
                        )
                    )

            min_sequence = min(by_sequence)
            max_sequence = max(by_sequence)
            route_codes = {
                route.process_code
                for _, route in indexed_routes
                if route.process_code not in (None, "")
            }

            for index, route in indexed_routes:
                if route.sequence != min_sequence:
                    self._require_route_fields(
                        route,
                        index,
                        ("upstream_process_code", "upstream_process_name"),
                        issues,
                    )
                if route.sequence != max_sequence:
                    self._require_route_fields(
                        route,
                        index,
                        ("downstream_process_code", "downstream_process_name"),
                        issues,
                    )

                for field in (
                    "upstream_process_code",
                    "downstream_process_code",
                ):
                    value = getattr(route, field)
                    if value in (None, ""):
                        continue
                    if value not in route_codes:
                        issues.append(
                            self._issue(
                                code="missing_reference",
                                dataset="process_routes",
                                field=field,
                                record_key=self._record_key(
                                    "process_routes",
                                    route,
                                    index,
                                ),
                                message=(
                                    f"process_routes.{field}={value!r} was not "
                                    "found in the same workshop and loop"
                                ),
                            )
                        )

    def _require_route_fields(
        self,
        route: Any,
        index: int,
        fields: tuple[str, str],
        issues: list[BackendValidationIssue],
    ) -> None:
        for field in fields:
            if getattr(route, field) is None:
                issues.append(
                    self._issue(
                        code="null_field",
                        dataset="process_routes",
                        field=field,
                        record_key=self._record_key(
                            "process_routes",
                            route,
                            index,
                        ),
                        message=f"process_routes.{field} must not be null here",
                    )
                )

    def _validate_served_processes(
        self,
        request: BackendAlgorithmRequest,
        issues: list[BackendValidationIssue],
    ) -> None:
        route_codes = {
            (route.loop_code, route.process_code)
            for route in request.process_routes
            if route.loop_code != "" and route.process_code != ""
        }
        for index, buffer in enumerate(request.buffer_master):
            for code_index, process_code in enumerate(buffer.served_process_codes):
                if process_code == "":
                    continue
                if (buffer.loop_code, process_code) not in route_codes:
                    field = f"served_process_codes[{code_index}]"
                    issues.append(
                        self._issue(
                            code="missing_reference",
                            dataset="buffer_master",
                            field=field,
                            record_key=self._record_key(
                                "buffer_master",
                                buffer,
                                index,
                            ),
                            message=(
                                f"buffer_master.{field}={process_code!r} was not "
                                f"found in loop {buffer.loop_code!r}"
                            ),
                        )
                    )

    def _validate_capacity(
        self,
        request: BackendAlgorithmRequest,
        issues: list[BackendValidationIssue],
    ) -> None:
        for index, buffer in enumerate(request.buffer_master):
            if buffer.max_capacity <= 0:
                issues.append(
                    self._issue(
                        code="invalid_value",
                        dataset="buffer_master",
                        field="max_capacity",
                        record_key=self._record_key(
                            "buffer_master",
                            buffer,
                            index,
                        ),
                        message="buffer_master.max_capacity must be greater than 0",
                    )
                )
```

- [ ] **Step 5: Run all validator tests and confirm green**

Run:

```powershell
pytest tests/adapters/test_backend_request_validator.py -q
```

Expected: all basic, reference, route-group, de-duplication, served-process, and defensive-capacity tests pass.

- [ ] **Step 6: Record the relationship-rule checkpoint**

Run:

```powershell
rg -n "missing_reference|duplicate_sequence|workshop_code, route.loop_code|_is_running" app/adapters/backend_request_validator.py
```

Expected: relationship skips for `None`/`""`, route grouping by both keys, and the state predicate are all visible; there is no call into `app/core`, `app/service`, or `SnapshotAdapter`.

### Task 5: Lock the transition contract, incomplete-request behavior, and package exports

**Files:**
- Modify: `tests/schemas/test_backend_request_schema.py`
- Modify: `tests/adapters/test_backend_request_validator.py`
- Modify: `app/schemas/__init__.py`
- Modify: `app/adapters/__init__.py`

- [ ] **Step 1: Add direct-Schema rejection tests for the transitional fields**

Append this test to `tests/schemas/test_backend_request_schema.py`:

```python
@pytest.mark.parametrize("field", ["period_quantity", "out_time"])
def test_transitional_machine_fields_are_not_in_the_formal_schema(field: str):
    payload = sample_payload()
    payload["machine_realtime"][0][field] = 0

    with pytest.raises(ValidationError) as error:
        BackendAlgorithmRequest.model_validate(payload)

    assert error.value.errors()[0]["loc"] == ("machine_realtime", 0, field)
    assert error.value.errors()[0]["type"] == "extra_forbidden"
```

This complements the Loader tests: direct formal validation rejects both fields, while the Loader temporarily removes them from a deep copy.

- [ ] **Step 2: Add a compact mirror of the current incomplete request and export tests**

Add `import json` as the first standard-library import in `tests/adapters/test_backend_request_validator.py`, then append:

```python
def test_compact_current_request_shape_loads_but_is_incomplete():
    payload = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    payload["machine_realtime"][0].update(
        {
            "status": "运行",
            "order_code": "",
            "period_quantity": 0,
            "out_time": "2026-07-14T08:30:00+08:00",
        }
    )
    for dataset in (
        "machine_master",
        "machine_process_times",
        "orders",
        "products",
        "process_routes",
        "buffer_master",
    ):
        payload[dataset] = []
    payload["workshops"][0]["workshop_name"] = None
    payload["buffer_realtime"][0]["main_id"] = None
    for field in (
        "buffer_code",
        "line_name",
        "last_line_code",
        "last_line_name",
        "process_code",
        "process_name",
    ):
        payload["agv_relations"][0][field] = None

    request = BackendRequestLoader().load_dict(payload)
    result = BackendRequestCompletenessValidator().validate(request)

    counts = {
        code: sum(issue.code == code for issue in result.issues)
        for code in {
            "empty_dataset",
            "null_field",
            "empty_code",
            "missing_reference",
        }
    }
    assert result.valid is False
    assert counts == {
        "empty_dataset": 6,
        "null_field": 8,
        "empty_code": 1,
        "missing_reference": 2,
    }


def test_backend_request_symbols_are_available_from_package_exports():
    from app.adapters import (
        BackendRequestCompletenessValidator as ExportedValidator,
    )
    from app.adapters import BackendRequestLoader as ExportedLoader
    from app.schemas import BackendAlgorithmRequest as ExportedRequest

    assert ExportedLoader is BackendRequestLoader
    assert ExportedValidator is BackendRequestCompletenessValidator
    assert ExportedRequest.__name__ == "BackendAlgorithmRequest"
```

- [ ] **Step 3: Run the new tests and confirm the export red state**

Run:

```powershell
pytest tests/schemas/test_backend_request_schema.py tests/adapters/test_backend_request_validator.py -q
```

Expected: transition and incomplete-shape tests pass; the package-export test fails with `ImportError` because the package `__init__.py` files are still empty.

- [ ] **Step 4: Export all fourteen schema models**

Replace the empty `app/schemas/__init__.py` with:

```python
from app.schemas.backend_request_schema import (
    BackendAgvRelation,
    BackendAlgorithmRequest,
    BackendBufferMaster,
    BackendBufferRealtime,
    BackendLine,
    BackendMachineLine,
    BackendMachineMaster,
    BackendMachineProcessTime,
    BackendMachineRealtime,
    BackendOrder,
    BackendProcessRoute,
    BackendProduct,
    BackendSnapshotMeta,
    BackendWorkshop,
)


__all__ = [
    "BackendAgvRelation",
    "BackendAlgorithmRequest",
    "BackendBufferMaster",
    "BackendBufferRealtime",
    "BackendLine",
    "BackendMachineLine",
    "BackendMachineMaster",
    "BackendMachineProcessTime",
    "BackendMachineRealtime",
    "BackendOrder",
    "BackendProcessRoute",
    "BackendProduct",
    "BackendSnapshotMeta",
    "BackendWorkshop",
]
```

- [ ] **Step 5: Export the Loader and completeness types**

Replace the empty `app/adapters/__init__.py` with:

```python
from app.adapters.backend_request_loader import (
    BackendRequestLoadError,
    BackendRequestLoader,
)
from app.adapters.backend_request_validator import (
    BackendRequestCompletenessValidator,
    BackendRequestValidationResult,
    BackendValidationIssue,
)


__all__ = [
    "BackendRequestCompletenessValidator",
    "BackendRequestLoadError",
    "BackendRequestLoader",
    "BackendRequestValidationResult",
    "BackendValidationIssue",
]
```

- [ ] **Step 6: Run all new test modules together**

Run:

```powershell
pytest tests/schemas/test_backend_request_schema.py tests/adapters/test_backend_request_loader.py tests/adapters/test_backend_request_validator.py -q
```

Expected: every new schema, Loader, validator, transition, incomplete-shape, and export test passes.

- [ ] **Step 7: Record the public-boundary checkpoint**

Run:

```powershell
git status --short
```

Expected: the only task-created paths are the three implementation files, two package initializers, three test files, the small example, and the already-reviewed design/plan documents.

### Task 6: Verify the real request, full regression suite, and scope boundary

**Files:**
- Verify: `D:\微信聊天信息\xwechat_files\wxid_61bjsjeueygp22_f6e7\msg\file\2026-07\algo-request.json`
- Verify: all planned implementation and test files
- Do not modify any additional file

- [ ] **Step 1: Run the three focused test modules once more**

Run:

```powershell
pytest tests/schemas/test_backend_request_schema.py tests/adapters/test_backend_request_loader.py tests/adapters/test_backend_request_validator.py -q
```

Expected: 92 new test cases pass.

- [ ] **Step 2: Validate the current 145 KB real request without modifying it**

Run this PowerShell block from the repository root:

```powershell
$path = 'D:\微信聊天信息\xwechat_files\wxid_61bjsjeueygp22_f6e7\msg\file\2026-07\algo-request.json'
$before = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash
python -c "from collections import Counter; from app.adapters.backend_request_loader import BackendRequestLoader; from app.adapters.backend_request_validator import BackendRequestCompletenessValidator; path = r'D:\微信聊天信息\xwechat_files\wxid_61bjsjeueygp22_f6e7\msg\file\2026-07\algo-request.json'; request = BackendRequestLoader().load_json_file(path); result = BackendRequestCompletenessValidator().validate(request); counts = Counter(issue.code for issue in result.issues); print(f'machine_realtime={len(request.machine_realtime)} valid={result.valid} counts={dict(counts)}'); assert len(request.machine_realtime) == 439; assert result.valid is False; assert counts == {'empty_dataset': 6, 'null_field': 458, 'empty_code': 137, 'missing_reference': 441}"
$after = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash
if ($before -ne $after) { throw 'The real request file changed during read-only verification' }
```

Expected output:

```text
machine_realtime=439 valid=False counts={'empty_dataset': 6, 'null_field': 458, 'empty_code': 137, 'missing_reference': 441}
```

The hash comparison must complete without throwing. The 137 `empty_code` issues correspond only to running machines; the 301 abnormal machines with empty orders are intentionally allowed.

- [ ] **Step 3: Run the full regression suite required by the request**

Run:

```powershell
pytest -q
```

Expected: 205 tests pass: the existing 113-test baseline plus 92 new tests.

- [ ] **Step 4: Prove that the new production modules do not cross into algorithm code**

Run:

```powershell
$matches = rg -n "CutlineSnapshot|SnapshotAdapter|app\.core|app\.service" app/schemas/backend_request_schema.py app/adapters/backend_request_loader.py app/adapters/backend_request_validator.py
if ($LASTEXITCODE -eq 1) { 'NO_ALGORITHM_DEPENDENCIES' } else { $matches }
```

Expected:

```text
NO_ALGORITHM_DEPENDENCIES
```

- [ ] **Step 5: Check final scope and whitespace**

Run:

```powershell
git diff --check
git status --short
```

Expected task paths:

```text
app/adapters/__init__.py
app/adapters/backend_request_loader.py
app/adapters/backend_request_validator.py
app/schemas/__init__.py
app/schemas/backend_request_schema.py
docs/superpowers/plans/2026-07-14-backend-request-ingestion-plan.md
docs/superpowers/specs/2026-07-14-backend-request-ingestion-design.md
examples/backend_request_sample.json
tests/adapters/test_backend_request_loader.py
tests/adapters/test_backend_request_validator.py
tests/schemas/test_backend_request_schema.py
```

The previously existing dirty files may also appear. No new path under `app/core`, `app/service`, `app/api`, and no modification to `snapshot_adapter.py` or existing schema modules is allowed.

- [ ] **Step 6: Prepare the completion report from verified evidence**

Report exactly these facts after the commands pass:

1. The added/modified files from Step 5.
2. All fourteen external request model names.
3. The seven retained `BackendMachineRealtime` fields.
4. `period_quantity`/`out_time` as deep-copy-only transitional cleanup with a removal condition once the backend stops sending them.
5. Every required-but-nullable field and which nulls are semantically valid versus completeness failures.
6. All completeness relationships and the `(workshop_code, loop_code)` route grouping rule.
7. Real request result: 439 machine records, `valid=false`, and the verified issue counts.
8. The exact final `pytest -q` pass count.

Do not claim completion from expected values in this plan; use only the fresh outputs produced during execution.

## Plan self-review result

- **Spec coverage:** Every design section maps to Tasks 1-6: strict models, required nullable fields, transitional cleanup, state-aware `order_code`, grouped routes, issue de-duplication, exports, compact incomplete data, real request, and full regression.
- **Placeholder scan:** The plan contains no unresolved markers, deferred implementation, or undefined code symbols.
- **Type consistency:** Public names, paths, signatures, field names, and issue codes match the approved design document throughout.
- **Scope check:** The work is one cohesive ingress subsystem with three sequential layers; splitting it into separate plans would prevent the final valid/incomplete end-to-end tests.
