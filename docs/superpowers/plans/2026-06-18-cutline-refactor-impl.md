# 切线算法服务重构（数据封装 + 设计模式）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把四个过程式、吃裸 dict 的算法模块改造成吃 Pydantic 对象、吐结果对象的组件，并补齐 Adapter / Strategy / Pipeline / Facade 四个空壳，实现真正的数据来源/数据结构/算法/对外契约解耦。

**Architecture:** 数据流为 `examples JSON → MockAdapter/SnapshotAdapter → CutlineSnapshot(Pydantic) → CutlinePipeline(净速率→耗尽→预警→候选) → CutlineService 门面映射 → CutlineEvaluateResponse`。裸 dict 只存在于适配器之前；过了适配器全程是对象。速率取数三级链显式化为 Strategy（构造注入），主算法不再碰 dict，也不再有 `_get_value`。

**Tech Stack:** Python 3.13、Pydantic 2.11、pytest。

**对设计 spec 的两点细化（执行者须知）：**
1. spec 第6节写 `NetRateCalculator.calculate(snapshot, rate_strategy)`；本计划改为**构造注入**策略（`NetRateCalculator(strategy).calculate(snapshot)`），因为 Pipeline 只构建一次组件、复用更自然。`StockoutCandidateFinder` 同样构造注入策略。
2. spec 第3节图里写 `CutlineSnapshot(已有 common_schema)`，**实际它在 `app/schemas/request_schema.py`**，import 一律从 `app.schemas.request_schema` 取。

**两个现状坑（已核实，本计划已处理）：**
- `CutlineSnapshot.current_time` 是必填，但 examples JSON 没有该字段 → `SnapshotAdapter` 缺省注入 `datetime.now()`。
- `MachineRuntimeStatus` 没有 `equipment_name` 字段，但候选机台逻辑要用、且 examples 的 `machine_statuses` 里带了它 → Task 2 给该模型补 `equipment_name: Optional[str]`。

**基线：** 重构前 `python -m pytest -q` 为 23 passed。这是行为回归基线，复杂场景净速率 6000/4000/3600/2500、耗尽 10/15/20/120、触发 [HG210R,HG182N,HG182T]、候选 [True,False,True] 全部不变。

---

## 任务依赖顺序

1. Task 1 — 锁定开发依赖（requirements.txt）
2. Task 2 — `result_schema.py` + 给 `MachineRuntimeStatus` 补 `equipment_name`
3. Task 3 — `safe_float` 收敛到 `app/utils/numeric.py`
4. Task 4 — `SnapshotAdapter` + `MockAdapter`（让后续测试能用 examples → snapshot）
5. Task 5 — `rate_strategy.py`（RateStrategy + RealtimeFirstRateStrategy）
6. Task 6 — `NetRateCalculator` 重构 + 测试改写
7. Task 7 — `DepletionTimeCalculator` 重构 + 测试改写
8. Task 8 — `StockoutWarningEvaluator` 重构 + 测试改写
9. Task 9 — `StockoutCandidateFinder` 重构 + 测试改写
10. Task 10 — `CutlinePipeline` + `CutlineService` 门面 + 全链路测试
11. Task 11 — 清理：删 `rate_utils.py`、删所有 `_get_value`、删重复 `safe_float`，跑全量

---

### Task 1: 锁定开发依赖

**Files:**
- Create: `requirements.txt`（当前为空）

- [ ] **Step 1: 写入 requirements.txt**

```
pydantic>=2.11,<3
pydantic-settings>=2.6
fastapi>=0.135
uvicorn>=0.44
pytest>=8
```

- [ ] **Step 2: 安装并自检**

Run: `python -m pip install -r requirements.txt -q && python -m pytest -q`
Expected: 末行 `23 passed`（基线仍绿）

- [ ] **Step 3: 提交**

```bash
git add requirements.txt
git commit -m "锁定算法服务运行与测试依赖"
```

---

### Task 2: 新增结果对象 schema，并给机台状态补 equipment_name

**Files:**
- Create: `app/schemas/result_schema.py`
- Modify: `app/schemas/common_schema.py`（`MachineRuntimeStatus` 增加 `equipment_name`）
- Test: `tests/schemas/test_result_schema.py`（新建，含 `tests/schemas/__init__.py`）

- [ ] **Step 1: 写失败测试**

新建空文件 `tests/schemas/__init__.py`，并写 `tests/schemas/test_result_schema.py`：

```python
from app.schemas.common_schema import MachineRuntimeStatus
from app.schemas.result_schema import (
    CandidateMachine,
    CandidateResult,
    DepletionResult,
    NetRateResult,
    StockoutWarningResult,
)


def test_machine_runtime_status_has_equipment_name():
    machine = MachineRuntimeStatus(
        equipment_code="zr01",
        equipment_name="ZR 01",
        process_code="ZR",
        status="running",
    )
    assert machine.equipment_name == "ZR 01"


def test_net_rate_result_field_names_match_dict_contract():
    result = NetRateResult(
        buffer_code="BUF",
        product_code="P",
        process_from="ZR",
        process_to="PK",
        upstream_output_per_hour=1.0,
        downstream_input_per_hour=2.0,
        net_rate_per_hour=1.0,
        upstream_equipment_codes=["a"],
        downstream_equipment_codes=["b"],
    )
    assert set(result.model_dump()) == {
        "buffer_code",
        "product_code",
        "process_from",
        "process_to",
        "upstream_output_per_hour",
        "downstream_input_per_hour",
        "net_rate_per_hour",
        "upstream_equipment_codes",
        "downstream_equipment_codes",
    }


def test_stockout_warning_result_has_twelve_contract_fields():
    result = StockoutWarningResult(
        buffer_code="BUF",
        product_code="P",
        process_from="ZR",
        process_to="PK",
        warning_type="stockout",
        warning_triggered=True,
        reason="depletion_time_within_lead_time",
        inventory_quantity=1.0,
        net_rate_per_hour=1.0,
        depletion_minutes=10.0,
        depletion_status="decreasing",
        cutline_lead_minutes=30.0,
    )
    assert set(result.model_dump()) == {
        "buffer_code",
        "product_code",
        "process_from",
        "process_to",
        "warning_type",
        "warning_triggered",
        "reason",
        "inventory_quantity",
        "net_rate_per_hour",
        "depletion_minutes",
        "depletion_status",
        "cutline_lead_minutes",
    }


def test_candidate_result_holds_candidate_machines():
    machine = CandidateMachine(
        equipment_code="zr03",
        equipment_name="ZR 03",
        process_code="ZR",
        current_product_code="HG182R",
        target_product_code="HG182T",
        wafer_size="182",
        shape_code="R",
        current_output_rate_per_hour=8000.0,
        contribution_capacity_per_hour=None,
        reason="same_process_size_shape_running_machine",
    )
    result = CandidateResult(
        buffer_code="BUF",
        product_code="HG182T",
        process_from="ZR",
        process_to="PK",
        candidate_found=True,
        candidate_status="candidate_found",
        reason=None,
        candidates=[machine],
    )
    assert result.candidates[0].equipment_code == "zr03"
    assert "priority_rank" not in result.model_dump()


def test_depletion_result_allows_none_minutes():
    result = DepletionResult(
        buffer_code="BUF",
        product_code="P",
        process_from="ZR",
        process_to="PK",
        inventory_quantity=0.0,
        net_rate_per_hour=0.0,
        depletion_minutes=None,
        depletion_status="stable",
    )
    assert result.depletion_minutes is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/schemas/test_result_schema.py -q`
Expected: FAIL（`ModuleNotFoundError: app.schemas.result_schema` 或 `equipment_name` 校验报错）

- [ ] **Step 3: 实现 — 给 MachineRuntimeStatus 补 equipment_name**

在 `app/schemas/common_schema.py` 的 `MachineRuntimeStatus` 中，`equipment_code` 字段下一行插入：

```python
    equipment_name: Optional[str] = Field(default=None, description="机台名称")
```

- [ ] **Step 4: 实现 — 新建 result_schema.py**

```python
# 算法管道四步各自的中间产物对象（内部模型，字段沿用原 dict 契约）

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class NetRateResult(BaseModel):
    """净速率计算结果。"""

    buffer_code: str
    product_code: str
    process_from: str
    process_to: Optional[str] = None
    upstream_output_per_hour: float
    downstream_input_per_hour: float
    net_rate_per_hour: float
    upstream_equipment_codes: List[str] = Field(default_factory=list)
    downstream_equipment_codes: List[str] = Field(default_factory=list)


class DepletionResult(BaseModel):
    """耗尽时间计算结果。"""

    buffer_code: str
    product_code: str
    process_from: str
    process_to: Optional[str] = None
    inventory_quantity: float
    net_rate_per_hour: float
    depletion_minutes: Optional[float] = None
    depletion_status: str


class StockoutWarningResult(BaseModel):
    """断料预警评估结果。"""

    buffer_code: str
    product_code: str
    process_from: str
    process_to: Optional[str] = None
    warning_type: str
    warning_triggered: bool
    reason: str
    inventory_quantity: float
    net_rate_per_hour: float
    depletion_minutes: Optional[float] = None
    depletion_status: str
    cutline_lead_minutes: float


class CandidateMachine(BaseModel):
    """候选机台明细。"""

    equipment_code: str
    equipment_name: Optional[str] = None
    process_code: str
    current_product_code: Optional[str] = None
    target_product_code: str
    wafer_size: Optional[str] = None
    shape_code: Optional[str] = None
    current_output_rate_per_hour: float
    contribution_capacity_per_hour: Optional[float] = None
    reason: str


class CandidateResult(BaseModel):
    """单个预警的候选机台查找结果。"""

    buffer_code: str
    product_code: str
    process_from: str
    process_to: Optional[str] = None
    candidate_found: bool
    candidate_status: str
    reason: Optional[str] = None
    candidates: List[CandidateMachine] = Field(default_factory=list)
```

- [ ] **Step 5: 跑测试确认通过 + 不回归**

Run: `python -m pytest tests/schemas/test_result_schema.py -q && python -m pytest -q`
Expected: 新测试 PASS；全量末行从 `23 passed` 变 `28 passed`

- [ ] **Step 6: 提交**

```bash
git add app/schemas/result_schema.py app/schemas/common_schema.py tests/schemas/__init__.py tests/schemas/test_result_schema.py
git commit -m "新增算法结果对象 schema，机台状态补 equipment_name"
```

---

### Task 3: safe_float 收敛到 app/utils/numeric.py

**Files:**
- Create: `app/utils/numeric.py`
- Test: `tests/utils/test_numeric.py`（新建，含 `tests/utils/__init__.py`）

注：本任务只新增统一实现并加测试；删除三处重复定义放在 Task 11 清理，避免本任务牵动算法文件。

- [ ] **Step 1: 写失败测试**

新建空文件 `tests/utils/__init__.py`，并写 `tests/utils/test_numeric.py`：

```python
from app.utils.numeric import safe_float


def test_safe_float_converts_numeric_string():
    assert safe_float("12.5") == 12.5


def test_safe_float_returns_default_for_none():
    assert safe_float(None) == 0.0
    assert safe_float(None, default=None) is None


def test_safe_float_returns_default_for_invalid():
    assert safe_float("abc") == 0.0


def test_safe_float_rejects_non_finite():
    assert safe_float(float("inf")) == 0.0
    assert safe_float(float("nan")) == 0.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/utils/test_numeric.py -q`
Expected: FAIL（`ModuleNotFoundError: app.utils.numeric`）

- [ ] **Step 3: 实现 numeric.py**

```python
# 数值安全转换工具（全项目唯一实现）

import math


def safe_float(value, default=0.0):
    """转 float；None/非数字/非有限值一律返回 default。"""
    try:
        if value is None:
            return default

        converted = float(value)
        if not math.isfinite(converted):
            return default

        return converted
    except (TypeError, ValueError, OverflowError):
        return default
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/utils/test_numeric.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add app/utils/numeric.py tests/utils/__init__.py tests/utils/test_numeric.py
git commit -m "新增统一 safe_float 数值工具"
```

---

### Task 4: SnapshotAdapter + MockAdapter（dict/JSON → CutlineSnapshot）

**Files:**
- Modify: `app/adapters/snapshot_adapter.py`（当前只有注释）
- Modify: `app/adapters/mock_adapter.py`（当前只有注释）
- Test: `tests/adapters/test_adapters.py`（新建，含 `tests/adapters/__init__.py`）

- [ ] **Step 1: 写失败测试**

新建空文件 `tests/adapters/__init__.py`，并写 `tests/adapters/test_adapters.py`：

```python
from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.adapters.snapshot_adapter import SnapshotAdapter
from app.schemas.request_schema import CutlineSnapshot


EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
COMPLEX_INPUT_PATH = EXAMPLES / "cutline_complex_input.json"
SAMPLE_INPUT_PATH = EXAMPLES / "cutline_sample_input.json"


def test_mock_adapter_loads_complex_example_into_snapshot():
    snapshot = MockAdapter().load(COMPLEX_INPUT_PATH)

    assert isinstance(snapshot, CutlineSnapshot)
    assert len(snapshot.machine_statuses) == 14
    assert len(snapshot.buffer_inventories) == 4
    assert snapshot.config.cutline_lead_minutes == 30


def test_mock_adapter_preserves_equipment_name():
    snapshot = MockAdapter().load(COMPLEX_INPUT_PATH)

    target = next(
        machine
        for machine in snapshot.machine_statuses
        if machine.equipment_code == "zr_hg182t_target"
    )
    assert target.equipment_name == "ZR HG182T Target"


def test_mock_adapter_ignores_extra_top_level_keys():
    # sample 输入带 expected_result 顶层键，应被忽略而非报错
    snapshot = MockAdapter().load(SAMPLE_INPUT_PATH)

    assert isinstance(snapshot, CutlineSnapshot)
    assert len(snapshot.capacity_records) == 7


def test_snapshot_adapter_injects_default_current_time_when_missing():
    snapshot = SnapshotAdapter().to_snapshot({"machine_statuses": []})

    assert snapshot.current_time is not None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/adapters/test_adapters.py -q`
Expected: FAIL（`ImportError: cannot import name 'SnapshotAdapter'`）

- [ ] **Step 3: 实现 snapshot_adapter.py**

整文件替换为：

```python
# 把后端/甲方传来的现场快照 dict 转成标准 CutlineSnapshot 对象

from datetime import datetime

from app.schemas.request_schema import CutlineSnapshot


class SnapshotAdapter:
    """dict/JSON → CutlineSnapshot。换数据源时只动适配器，不动算法。"""

    def to_snapshot(self, payload: dict) -> CutlineSnapshot:
        data = dict(payload)
        data.setdefault("current_time", datetime.now())
        return CutlineSnapshot.model_validate(data)
```

- [ ] **Step 4: 实现 mock_adapter.py**

整文件替换为：

```python
# 本地测试用：读取 examples 下的假数据 JSON，复用 SnapshotAdapter 产出快照

import json
from pathlib import Path
from typing import Optional, Union

from app.adapters.snapshot_adapter import SnapshotAdapter
from app.schemas.request_schema import CutlineSnapshot


class MockAdapter:
    """examples JSON 文件 → CutlineSnapshot。"""

    def __init__(self, snapshot_adapter: Optional[SnapshotAdapter] = None):
        self._snapshot_adapter = snapshot_adapter or SnapshotAdapter()

    def load(self, path: Union[str, Path]) -> CutlineSnapshot:
        with Path(path).open(encoding="utf-8") as file:
            payload = json.load(file)
        return self._snapshot_adapter.to_snapshot(payload)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/adapters/test_adapters.py -q`
Expected: PASS（4 passed）

- [ ] **Step 6: 提交**

```bash
git add app/adapters/snapshot_adapter.py app/adapters/mock_adapter.py tests/adapters/__init__.py tests/adapters/test_adapters.py
git commit -m "实现 Snapshot/Mock 适配器：dict/JSON 转 CutlineSnapshot"
```

---

### Task 5: 速率策略 rate_strategy.py（Strategy 模式）

**Files:**
- Create: `app/core/net_rate/rate_strategy.py`
- Test: `tests/core/test_rate_strategy.py`（新建，含 `tests/core/__init__.py`）

策略吃 `MachineRuntimeStatus` 对象（非 dict），三级取数链：实时速率 → 近30min量×2 → 静态产能兜底 → 0.0。

- [ ] **Step 1: 写失败测试**

新建空文件 `tests/core/__init__.py`，并写 `tests/core/test_rate_strategy.py`：

```python
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.schemas.common_schema import MachineRuntimeStatus


def machine(**overrides):
    base = {"equipment_code": "m1", "process_code": "ZR", "status": "running"}
    base.update(overrides)
    return MachineRuntimeStatus(**base)


def test_prefers_realtime_rate():
    strategy = RealtimeFirstRateStrategy()
    m = machine(
        input_rate_per_hour=100,
        output_rate_per_hour=120,
        input_quantity_30min=999,
        out_quantity_30min=999,
        actual_capacity_per_hour=999,
    )
    assert strategy.input_rate(m) == 100
    assert strategy.output_rate(m) == 120


def test_falls_back_to_30min_quantity_times_two():
    strategy = RealtimeFirstRateStrategy()
    m = machine(
        input_quantity_30min=50,
        out_quantity_30min=60,
        actual_capacity_per_hour=999,
    )
    assert strategy.input_rate(m) == 100
    assert strategy.output_rate(m) == 120


def test_falls_back_to_static_capacity():
    strategy = RealtimeFirstRateStrategy()
    m = machine(actual_capacity_per_hour=80)
    assert strategy.input_rate(m) == 80
    assert strategy.output_rate(m) == 80


def test_returns_zero_when_no_source():
    strategy = RealtimeFirstRateStrategy()
    m = machine()
    assert strategy.input_rate(m) == 0.0
    assert strategy.output_rate(m) == 0.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/core/test_rate_strategy.py -q`
Expected: FAIL（`ModuleNotFoundError: app.core.net_rate.rate_strategy`）

- [ ] **Step 3: 实现 rate_strategy.py**

```python
# 速率取数策略：把"实时速率→近30min量×2→静态产能"三级链显式化为可替换策略

from abc import ABC, abstractmethod

from app.schemas.common_schema import MachineRuntimeStatus
from app.utils.numeric import safe_float


class RateStrategy(ABC):
    """机台吞入/产出速率取数策略。"""

    @abstractmethod
    def input_rate(self, machine: MachineRuntimeStatus) -> float:
        ...

    @abstractmethod
    def output_rate(self, machine: MachineRuntimeStatus) -> float:
        ...


class RealtimeFirstRateStrategy(RateStrategy):
    """默认口径：实时速率优先，其次近30min量×2，再次静态产能，最后 0.0。"""

    def input_rate(self, machine: MachineRuntimeStatus) -> float:
        if machine.input_rate_per_hour is not None:
            return safe_float(machine.input_rate_per_hour)
        if machine.input_quantity_30min is not None:
            return safe_float(machine.input_quantity_30min) * 2
        if machine.actual_capacity_per_hour is not None:
            return safe_float(machine.actual_capacity_per_hour)
        return 0.0

    def output_rate(self, machine: MachineRuntimeStatus) -> float:
        if machine.output_rate_per_hour is not None:
            return safe_float(machine.output_rate_per_hour)
        if machine.out_quantity_30min is not None:
            return safe_float(machine.out_quantity_30min) * 2
        if machine.actual_capacity_per_hour is not None:
            return safe_float(machine.actual_capacity_per_hour)
        return 0.0
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/core/test_rate_strategy.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add app/core/net_rate/rate_strategy.py tests/core/__init__.py tests/core/test_rate_strategy.py
git commit -m "新增速率取数策略 RealtimeFirstRateStrategy"
```

---

### Task 6: 重构 NetRateCalculator（吃 snapshot 吐 list[NetRateResult]）

**Files:**
- Modify: `app/core/net_rate/net_rate_calculator.py`（整体替换为类，删本文件内 `_get_value`）
- Modify: `tests/cutline_sample_input/test_net_rate_calculator.py`（改对象 API + 属性断言）
- Modify: `tests/cutline_complex_input/test_net_rate_calculator.py`（同上）

- [ ] **Step 1: 改写两个净速率测试为对象 API（先让其失败）**

整体替换 `tests/cutline_sample_input/test_net_rate_calculator.py`：

```python
from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy


SAMPLE_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_sample_input.json"


def load_sample_snapshot():
    return MockAdapter().load(SAMPLE_INPUT_PATH)


def calculate(snapshot):
    return NetRateCalculator(RealtimeFirstRateStrategy()).calculate(snapshot)


def by_segment(results):
    return {
        (r.buffer_code, r.product_code, r.process_from, r.process_to): r
        for r in results
    }


def test_calculates_hg182t_stockout_net_rate():
    result = by_segment(calculate(load_sample_snapshot()))[
        ("BUF_ZR_PK", "HG182T", "ZR", "PK")
    ]

    assert result.upstream_output_per_hour == 16000
    assert result.downstream_input_per_hour == 19200
    assert result.net_rate_per_hour == 3200
    assert set(result.upstream_equipment_codes) == {"zr01", "zr02"}
    assert set(result.downstream_equipment_codes) == {"pk01", "pk02"}


def test_calculates_hg182r_net_rate_without_excluding_zr03():
    result = by_segment(calculate(load_sample_snapshot()))[
        ("BUF_ZR_PK", "HG182R", "ZR", "PK")
    ]

    assert result.upstream_output_per_hour == 8000
    assert result.downstream_input_per_hour == 9600
    assert result.net_rate_per_hour == 1600
    assert set(result.upstream_equipment_codes) == {"zr03"}
    assert set(result.downstream_equipment_codes) == {"pk03"}


def test_calculate_all_net_rates_uses_buffer_inventories():
    segments = by_segment(calculate(load_sample_snapshot()))

    assert segments[("BUF_ZR_PK", "HG182T", "ZR", "PK")].net_rate_per_hour == 3200
    assert segments[("BUF_ZR_PK", "HG182R", "ZR", "PK")].net_rate_per_hour == 1600
```

整体替换 `tests/cutline_complex_input/test_net_rate_calculator.py`：

```python
from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy


COMPLEX_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_complex_input.json"


def load_complex_snapshot():
    return MockAdapter().load(COMPLEX_INPUT_PATH)


def calculate(snapshot):
    return NetRateCalculator(RealtimeFirstRateStrategy()).calculate(snapshot)


def by_segment(results):
    return {
        (r.buffer_code, r.product_code, r.process_from, r.process_to): r
        for r in results
    }


def test_calculate_all_net_rates_handles_multiple_buffers_and_products():
    segments = by_segment(calculate(load_complex_snapshot()))

    assert len(segments) == 4
    assert {
        ("BUF_PK_OX", "HG210R", "PK", "OX"),
        ("BUF_ZR_PK", "HG182N", "ZR", "PK"),
        ("BUF_ZR_PK", "HG182T", "ZR", "PK"),
        ("BUF_ZR_PK", "HG182R", "ZR", "PK"),
    } == set(segments)


def test_calculate_all_net_rates_matches_complex_input_design():
    segments = by_segment(calculate(load_complex_snapshot()))

    assert segments[("BUF_PK_OX", "HG210R", "PK", "OX")].net_rate_per_hour == 6000
    assert segments[("BUF_ZR_PK", "HG182N", "ZR", "PK")].net_rate_per_hour == 4000
    assert segments[("BUF_ZR_PK", "HG182T", "ZR", "PK")].net_rate_per_hour == 3600
    assert segments[("BUF_ZR_PK", "HG182R", "ZR", "PK")].net_rate_per_hour == 2500
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/cutline_sample_input/test_net_rate_calculator.py tests/cutline_complex_input/test_net_rate_calculator.py -q`
Expected: FAIL（`ImportError: cannot import name 'NetRateCalculator'`）

- [ ] **Step 3: 实现 — 整体替换 net_rate_calculator.py**

```python
# 净速率计算组件：吃 CutlineSnapshot，吐 list[NetRateResult]

from app.core.net_rate.rate_strategy import RateStrategy
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import NetRateResult


class NetRateCalculator:
    """按 buffer 区间(段)聚合上游产出与下游吞入，得到净消耗速率。"""

    def __init__(self, rate_strategy: RateStrategy):
        self._rate_strategy = rate_strategy

    def calculate(self, snapshot: CutlineSnapshot) -> list[NetRateResult]:
        results = []
        seen_segments = set()

        for inventory in snapshot.buffer_inventories:
            segment_key = (
                inventory.buffer_code,
                inventory.product_code,
                inventory.process_from,
                inventory.process_to,
            )
            if segment_key in seen_segments:
                continue

            seen_segments.add(segment_key)
            results.append(self._calculate_segment(snapshot, *segment_key))

        return results

    def _calculate_segment(
        self,
        snapshot: CutlineSnapshot,
        buffer_code,
        product_code,
        process_from,
        process_to,
    ) -> NetRateResult:
        upstream_output_per_hour = 0.0
        downstream_input_per_hour = 0.0
        upstream_equipment_codes = []
        downstream_equipment_codes = []

        for machine in snapshot.machine_statuses:
            if machine.status != "running":
                continue
            if machine.product_code != product_code:
                continue

            if machine.process_code == process_from:
                upstream_output_per_hour += self._rate_strategy.output_rate(machine)
                upstream_equipment_codes.append(machine.equipment_code)
            elif machine.process_code == process_to:
                downstream_input_per_hour += self._rate_strategy.input_rate(machine)
                downstream_equipment_codes.append(machine.equipment_code)

        return NetRateResult(
            buffer_code=buffer_code,
            product_code=product_code,
            process_from=process_from,
            process_to=process_to,
            upstream_output_per_hour=upstream_output_per_hour,
            downstream_input_per_hour=downstream_input_per_hour,
            net_rate_per_hour=downstream_input_per_hour - upstream_output_per_hour,
            upstream_equipment_codes=upstream_equipment_codes,
            downstream_equipment_codes=downstream_equipment_codes,
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/cutline_sample_input/test_net_rate_calculator.py tests/cutline_complex_input/test_net_rate_calculator.py -q`
Expected: PASS（5 passed）

注：此时 depletion/warning/candidate/full_flow 旧测试仍 import 老函数会红，属预期，Task 7–10 逐个修。本步只验证净速率两个文件。

- [ ] **Step 5: 提交**

```bash
git add app/core/net_rate/net_rate_calculator.py tests/cutline_sample_input/test_net_rate_calculator.py tests/cutline_complex_input/test_net_rate_calculator.py
git commit -m "重构 NetRateCalculator 为吃对象吐结果对象的组件"
```

---

### Task 7: 重构 DepletionTimeCalculator

**Files:**
- Modify: `app/core/prediction_time/depletion_time/depletion_time_calculator.py`（整体替换为类，删本文件 `_get_value`/`safe_float`）
- Modify: `tests/cutline_sample_input/test_depletion_time_calculator.py`
- Modify: `tests/cutline_complex_input/test_depletion_time_calculator.py`

- [ ] **Step 1: 改写两个耗尽测试为对象 API（先让其失败）**

整体替换 `tests/cutline_sample_input/test_depletion_time_calculator.py`：

```python
from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)


SAMPLE_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_sample_input.json"


def load_sample_snapshot():
    return MockAdapter().load(SAMPLE_INPUT_PATH)


def build_depletions(snapshot):
    net_rates = NetRateCalculator(RealtimeFirstRateStrategy()).calculate(snapshot)
    return DepletionTimeCalculator().calculate(snapshot, net_rates)


def by_segment(results):
    return {
        (r.buffer_code, r.product_code, r.process_from, r.process_to): r
        for r in results
    }


def test_inventory_quantity_matches_buffer_product_and_process_segment():
    segments = by_segment(build_depletions(load_sample_snapshot()))

    assert segments[("BUF_ZR_PK", "HG182T", "ZR", "PK")].inventory_quantity == 1600
    assert segments[("BUF_ZR_PK", "HG182R", "ZR", "PK")].inventory_quantity == 20000


def test_depletion_time_for_hg182t_stockout_segment():
    result = by_segment(build_depletions(load_sample_snapshot()))[
        ("BUF_ZR_PK", "HG182T", "ZR", "PK")
    ]

    assert result.inventory_quantity == 1600
    assert result.net_rate_per_hour == 3200
    assert result.depletion_minutes == 30
    assert result.depletion_status == "decreasing"


def test_depletion_time_for_hg182r_stockout_segment():
    result = by_segment(build_depletions(load_sample_snapshot()))[
        ("BUF_ZR_PK", "HG182R", "ZR", "PK")
    ]

    assert result.inventory_quantity == 20000
    assert result.net_rate_per_hour == 1600
    assert result.depletion_minutes == 750
    assert result.depletion_status == "decreasing"
```

整体替换 `tests/cutline_complex_input/test_depletion_time_calculator.py`：

```python
from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)


COMPLEX_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_complex_input.json"


def load_complex_snapshot():
    return MockAdapter().load(COMPLEX_INPUT_PATH)


def build_depletions(snapshot):
    net_rates = NetRateCalculator(RealtimeFirstRateStrategy()).calculate(snapshot)
    return DepletionTimeCalculator().calculate(snapshot, net_rates)


def by_segment(results):
    return {
        (r.buffer_code, r.product_code, r.process_from, r.process_to): r
        for r in results
    }


def test_depletion_times_match_complex_input_design():
    segments = by_segment(build_depletions(load_complex_snapshot()))

    assert segments[("BUF_PK_OX", "HG210R", "PK", "OX")].depletion_minutes == 10
    assert segments[("BUF_ZR_PK", "HG182N", "ZR", "PK")].depletion_minutes == 15
    assert segments[("BUF_ZR_PK", "HG182T", "ZR", "PK")].depletion_minutes == 20
    assert segments[("BUF_ZR_PK", "HG182R", "ZR", "PK")].depletion_minutes == 120


def test_complex_depletion_results_are_all_decreasing_inventory_cases():
    results = build_depletions(load_complex_snapshot())

    assert {r.depletion_status for r in results} == {"decreasing"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/cutline_sample_input/test_depletion_time_calculator.py tests/cutline_complex_input/test_depletion_time_calculator.py -q`
Expected: FAIL（`ImportError: cannot import name 'DepletionTimeCalculator'`）

- [ ] **Step 3: 实现 — 整体替换 depletion_time_calculator.py**

```python
# 耗尽时间计算组件：吃 snapshot + list[NetRateResult]，吐 list[DepletionResult]

from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import DepletionResult, NetRateResult
from app.utils.numeric import safe_float


class DepletionTimeCalculator:
    """按净速率与区间库存推算耗尽时间（分钟）。"""

    def calculate(
        self,
        snapshot: CutlineSnapshot,
        net_rates: list[NetRateResult],
    ) -> list[DepletionResult]:
        return [self._for_segment(snapshot, net_rate) for net_rate in net_rates]

    def _for_segment(
        self,
        snapshot: CutlineSnapshot,
        net_rate: NetRateResult,
    ) -> DepletionResult:
        inventory_quantity = self._inventory_quantity(
            snapshot,
            net_rate.buffer_code,
            net_rate.product_code,
            net_rate.process_from,
            net_rate.process_to,
        )
        net_rate_per_hour = safe_float(net_rate.net_rate_per_hour)

        depletion_minutes = None
        if net_rate_per_hour > 0:
            depletion_minutes = inventory_quantity / net_rate_per_hour * 60
            depletion_status = "decreasing"
        elif net_rate_per_hour == 0:
            depletion_status = "stable"
        else:
            depletion_status = "increasing"

        return DepletionResult(
            buffer_code=net_rate.buffer_code,
            product_code=net_rate.product_code,
            process_from=net_rate.process_from,
            process_to=net_rate.process_to,
            inventory_quantity=inventory_quantity,
            net_rate_per_hour=net_rate_per_hour,
            depletion_minutes=depletion_minutes,
            depletion_status=depletion_status,
        )

    def _inventory_quantity(
        self,
        snapshot: CutlineSnapshot,
        buffer_code,
        product_code,
        process_from,
        process_to,
    ) -> float:
        total = 0.0
        for inventory in snapshot.buffer_inventories:
            if (
                inventory.buffer_code == buffer_code
                and inventory.product_code == product_code
                and inventory.process_from == process_from
                and inventory.process_to == process_to
            ):
                total += safe_float(inventory.inventory_quantity)
        return total
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/cutline_sample_input/test_depletion_time_calculator.py tests/cutline_complex_input/test_depletion_time_calculator.py -q`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add app/core/prediction_time/depletion_time/depletion_time_calculator.py tests/cutline_sample_input/test_depletion_time_calculator.py tests/cutline_complex_input/test_depletion_time_calculator.py
git commit -m "重构 DepletionTimeCalculator 为对象化组件"
```

---

### Task 8: 重构 StockoutWarningEvaluator

**Files:**
- Modify: `app/core/warning/stockout_warning.py`（整体替换为类，删本文件 `_get_value`/`safe_float`）
- Modify: `tests/cutline_sample_input/test_stockout_warning.py`
- Modify: `tests/cutline_complex_input/test_stockout_warning.py`

- [ ] **Step 1: 改写两个预警测试为对象 API（先让其失败）**

整体替换 `tests/cutline_sample_input/test_stockout_warning.py`：

```python
from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)
from app.core.warning.stockout_warning import StockoutWarningEvaluator


SAMPLE_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_sample_input.json"


def load_sample_snapshot():
    return MockAdapter().load(SAMPLE_INPUT_PATH)


def build_warnings(snapshot):
    net_rates = NetRateCalculator(RealtimeFirstRateStrategy()).calculate(snapshot)
    depletions = DepletionTimeCalculator().calculate(snapshot, net_rates)
    return StockoutWarningEvaluator().evaluate(snapshot, depletions)


def find(warnings, buffer_code, product_code, process_from, process_to):
    for warning in warnings:
        if (
            warning.buffer_code == buffer_code
            and warning.product_code == product_code
            and warning.process_from == process_from
            and warning.process_to == process_to
        ):
            return warning
    raise AssertionError("Expected warning result was not found")


def test_config_cutline_lead_minutes_is_thirty():
    assert load_sample_snapshot().config.cutline_lead_minutes == 30


def test_returns_one_result_per_depletion_result():
    snapshot = load_sample_snapshot()
    net_rates = NetRateCalculator(RealtimeFirstRateStrategy()).calculate(snapshot)
    depletions = DepletionTimeCalculator().calculate(snapshot, net_rates)

    warnings = StockoutWarningEvaluator().evaluate(snapshot, depletions)

    assert len(warnings) == len(depletions)


def test_hg182t_triggers_stockout_warning_within_lead_time():
    hg182t = find(build_warnings(load_sample_snapshot()), "BUF_ZR_PK", "HG182T", "ZR", "PK")

    assert hg182t.warning_triggered is True
    assert hg182t.reason == "depletion_time_within_lead_time"
    assert hg182t.depletion_minutes == 30
    assert hg182t.cutline_lead_minutes == 30


def test_hg182r_does_not_trigger_stockout_warning_beyond_lead_time():
    hg182r = find(build_warnings(load_sample_snapshot()), "BUF_ZR_PK", "HG182R", "ZR", "PK")

    assert hg182r.warning_triggered is False
    assert hg182r.reason == "depletion_time_beyond_lead_time"
    assert hg182r.depletion_minutes == 750
    assert hg182r.cutline_lead_minutes == 30


def test_warning_result_exposes_all_contract_fields():
    result = build_warnings(load_sample_snapshot())[0]

    assert set(result.model_dump()) == {
        "buffer_code",
        "product_code",
        "process_from",
        "process_to",
        "warning_type",
        "warning_triggered",
        "reason",
        "inventory_quantity",
        "net_rate_per_hour",
        "depletion_minutes",
        "depletion_status",
        "cutline_lead_minutes",
    }
    assert result.warning_type == "stockout"
```

整体替换 `tests/cutline_complex_input/test_stockout_warning.py`：

```python
from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)
from app.core.warning.stockout_warning import StockoutWarningEvaluator


COMPLEX_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_complex_input.json"


def load_complex_snapshot():
    return MockAdapter().load(COMPLEX_INPUT_PATH)


def build_warnings(snapshot):
    net_rates = NetRateCalculator(RealtimeFirstRateStrategy()).calculate(snapshot)
    depletions = DepletionTimeCalculator().calculate(snapshot, net_rates)
    return StockoutWarningEvaluator().evaluate(snapshot, depletions)


def by_product(warnings):
    return {warning.product_code: warning for warning in warnings}


def test_complex_stockout_warnings_match_expected_trigger_states():
    warnings = by_product(build_warnings(load_complex_snapshot()))

    assert warnings["HG210R"].warning_triggered is True
    assert warnings["HG182N"].warning_triggered is True
    assert warnings["HG182T"].warning_triggered is True
    assert warnings["HG182R"].warning_triggered is False


def test_complex_stockout_warning_reasons_follow_depletion_time_threshold():
    warnings = by_product(build_warnings(load_complex_snapshot()))

    assert warnings["HG210R"].reason == "depletion_time_within_lead_time"
    assert warnings["HG182N"].reason == "depletion_time_within_lead_time"
    assert warnings["HG182T"].reason == "depletion_time_within_lead_time"
    assert warnings["HG182R"].reason == "depletion_time_beyond_lead_time"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/cutline_sample_input/test_stockout_warning.py tests/cutline_complex_input/test_stockout_warning.py -q`
Expected: FAIL（`ImportError: cannot import name 'StockoutWarningEvaluator'`）

- [ ] **Step 3: 实现 — 整体替换 stockout_warning.py**

```python
# 断料预警评估组件：吃 snapshot + list[DepletionResult]，吐 list[StockoutWarningResult]

from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import DepletionResult, StockoutWarningResult
from app.utils.numeric import safe_float


class StockoutWarningEvaluator:
    """耗尽时间 ≤ 切线提前量则触发断料预警。"""

    def evaluate(
        self,
        snapshot: CutlineSnapshot,
        depletions: list[DepletionResult],
    ) -> list[StockoutWarningResult]:
        cutline_lead_minutes = safe_float(snapshot.config.cutline_lead_minutes)
        return [
            self._for_segment(depletion, cutline_lead_minutes)
            for depletion in depletions
        ]

    def _for_segment(
        self,
        depletion: DepletionResult,
        cutline_lead_minutes: float,
    ) -> StockoutWarningResult:
        warning_triggered = False
        if depletion.depletion_status != "decreasing":
            reason = "inventory_not_decreasing"
        elif depletion.depletion_minutes is None:
            reason = "depletion_time_not_available"
        elif depletion.depletion_minutes <= cutline_lead_minutes:
            warning_triggered = True
            reason = "depletion_time_within_lead_time"
        else:
            reason = "depletion_time_beyond_lead_time"

        return StockoutWarningResult(
            buffer_code=depletion.buffer_code,
            product_code=depletion.product_code,
            process_from=depletion.process_from,
            process_to=depletion.process_to,
            warning_type="stockout",
            warning_triggered=warning_triggered,
            reason=reason,
            inventory_quantity=depletion.inventory_quantity,
            net_rate_per_hour=depletion.net_rate_per_hour,
            depletion_minutes=depletion.depletion_minutes,
            depletion_status=depletion.depletion_status,
            cutline_lead_minutes=cutline_lead_minutes,
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/cutline_sample_input/test_stockout_warning.py tests/cutline_complex_input/test_stockout_warning.py -q`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add app/core/warning/stockout_warning.py tests/cutline_sample_input/test_stockout_warning.py tests/cutline_complex_input/test_stockout_warning.py
git commit -m "重构 StockoutWarningEvaluator 为对象化组件"
```

---

### Task 9: 重构 StockoutCandidateFinder

**Files:**
- Modify: `app/core/candidate_machine/stockout_candidate_finder.py`（整体替换为类，删本文件 `_get_value`；产出速率改用注入的策略）
- Modify: `tests/cutline_complex_input/test_stockout_candidate_finder.py`

保留原"按 `depletion_minutes` 升序处理多个预警"的全局排序逻辑；候选明细的 `wafer_size`/`shape_code` 取自机台当前型号的 ProductModel（与原行为一致）。

- [ ] **Step 1: 改写候选测试为对象 API（先让其失败）**

整体替换 `tests/cutline_complex_input/test_stockout_candidate_finder.py`：

```python
from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.candidate_machine.stockout_candidate_finder import StockoutCandidateFinder
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)
from app.core.warning.stockout_warning import StockoutWarningEvaluator


COMPLEX_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_complex_input.json"


def load_complex_snapshot():
    return MockAdapter().load(COMPLEX_INPUT_PATH)


def build_candidates(snapshot):
    strategy = RealtimeFirstRateStrategy()
    net_rates = NetRateCalculator(strategy).calculate(snapshot)
    depletions = DepletionTimeCalculator().calculate(snapshot, net_rates)
    warnings = StockoutWarningEvaluator().evaluate(snapshot, depletions)
    return StockoutCandidateFinder(strategy).find(snapshot, warnings)


def by_product(results, product_code):
    for result in results:
        if result.product_code == product_code:
            return result
    raise AssertionError(f"Expected result for {product_code} was not found")


def codes(candidate_result):
    return {candidate.equipment_code for candidate in candidate_result.candidates}


def test_returns_results_in_global_depletion_urgency_order():
    results = build_candidates(load_complex_snapshot())

    assert [result.product_code for result in results] == [
        "HG210R",
        "HG182N",
        "HG182T",
    ]
    assert all("priority_rank" not in result.model_dump() for result in results)
    assert all(
        "priority_rank" not in candidate.model_dump()
        for result in results
        for candidate in result.candidates
    )


def test_hg210r_finds_compatible_pk_candidate_and_excludes_invalid_machines():
    hg210r = by_product(build_candidates(load_complex_snapshot()), "HG210R")

    assert hg210r.candidate_found is True
    assert hg210r.candidate_status == "candidate_found"
    assert "pk_hg210t_candidate" in codes(hg210r)
    assert "pk_hg210r_target" not in codes(hg210r)
    assert "pk_hg210t_stopped" not in codes(hg210r)
    assert "pk_hg182r_size_mismatch" not in codes(hg210r)


def test_hg182n_requires_manual_intervention_when_no_compatible_machine_exists():
    hg182n = by_product(build_candidates(load_complex_snapshot()), "HG182N")

    assert hg182n.candidate_found is False
    assert hg182n.candidate_status == "manual_intervention_required"
    assert hg182n.reason == "no_compatible_running_upstream_machine"
    assert hg182n.candidates == []


def test_hg182t_finds_compatible_zr_candidate_and_excludes_invalid_machines():
    hg182t = by_product(build_candidates(load_complex_snapshot()), "HG182T")

    assert hg182t.candidate_found is True
    assert hg182t.candidate_status == "candidate_found"
    assert len(hg182t.candidates) >= 2
    assert "zr_hg182r_candidate" in codes(hg182t)
    assert "zr_hg182r_candidate_2" in codes(hg182t)
    assert "zr_hg182t_target" not in codes(hg182t)
    assert "zr_hg182r_stopped" not in codes(hg182t)
    assert "zr_hg210r_size_mismatch" not in codes(hg182t)
    assert "zr_hg182n_target" not in codes(hg182t)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/cutline_complex_input/test_stockout_candidate_finder.py -q`
Expected: FAIL（`ImportError: cannot import name 'StockoutCandidateFinder'`）

- [ ] **Step 3: 实现 — 整体替换 stockout_candidate_finder.py**

```python
# 候选机台查找组件：吃 snapshot + list[StockoutWarningResult]，吐 list[CandidateResult]

from app.core.net_rate.rate_strategy import RateStrategy
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import (
    CandidateMachine,
    CandidateResult,
    StockoutWarningResult,
)


class StockoutCandidateFinder:
    """为触发的断料预警，按全局耗尽紧迫度顺序查找同工序同尺寸同形状的在产机台。"""

    def __init__(self, rate_strategy: RateStrategy):
        self._rate_strategy = rate_strategy

    def find(
        self,
        snapshot: CutlineSnapshot,
        warnings: list[StockoutWarningResult],
    ) -> list[CandidateResult]:
        triggered = [
            warning
            for warning in warnings
            if warning.warning_triggered and warning.warning_type == "stockout"
        ]
        triggered.sort(key=self._depletion_sort_key)

        product_model_map = {
            product_model.product_code: product_model
            for product_model in snapshot.product_models
        }

        return [
            self._for_warning(snapshot, warning, product_model_map)
            for warning in triggered
        ]

    def _depletion_sort_key(self, warning: StockoutWarningResult) -> float:
        if warning.depletion_minutes is None:
            return float("inf")
        return warning.depletion_minutes

    def _for_warning(
        self,
        snapshot: CutlineSnapshot,
        warning: StockoutWarningResult,
        product_model_map,
    ) -> CandidateResult:
        target_model = product_model_map.get(warning.product_code)
        candidates = []

        for machine in snapshot.machine_statuses:
            if machine.status != "running":
                continue
            if machine.process_code != warning.process_from:
                continue
            if machine.product_code == warning.product_code:
                continue

            current_model = product_model_map.get(machine.product_code)
            if not self._same_size_and_shape(current_model, target_model):
                continue

            candidates.append(
                CandidateMachine(
                    equipment_code=machine.equipment_code,
                    equipment_name=machine.equipment_name,
                    process_code=machine.process_code,
                    current_product_code=machine.product_code,
                    target_product_code=warning.product_code,
                    wafer_size=current_model.wafer_size if current_model else None,
                    shape_code=current_model.shape_code if current_model else None,
                    current_output_rate_per_hour=self._rate_strategy.output_rate(machine),
                    contribution_capacity_per_hour=self._actual_capacity(
                        snapshot, machine.equipment_code, warning.product_code
                    ),
                    reason="same_process_size_shape_running_machine",
                )
            )

        if candidates:
            return CandidateResult(
                buffer_code=warning.buffer_code,
                product_code=warning.product_code,
                process_from=warning.process_from,
                process_to=warning.process_to,
                candidate_found=True,
                candidate_status="candidate_found",
                reason=None,
                candidates=candidates,
            )

        return CandidateResult(
            buffer_code=warning.buffer_code,
            product_code=warning.product_code,
            process_from=warning.process_from,
            process_to=warning.process_to,
            candidate_found=False,
            candidate_status="manual_intervention_required",
            reason="no_compatible_running_upstream_machine",
            candidates=[],
        )

    def _same_size_and_shape(self, current_model, target_model) -> bool:
        if current_model is None or target_model is None:
            return False
        return (
            current_model.wafer_size == target_model.wafer_size
            and current_model.shape_code == target_model.shape_code
        )

    def _actual_capacity(self, snapshot: CutlineSnapshot, equipment_code, product_code):
        for record in snapshot.capacity_records:
            if (
                record.equipment_code == equipment_code
                and record.product_code == product_code
            ):
                return record.actual_capacity_per_hour
        return None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/cutline_complex_input/test_stockout_candidate_finder.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add app/core/candidate_machine/stockout_candidate_finder.py tests/cutline_complex_input/test_stockout_candidate_finder.py
git commit -m "重构 StockoutCandidateFinder 为对象化组件并复用速率策略"
```

---

### Task 10: CutlinePipeline 编排 + CutlineService 门面 + 全链路测试

**Files:**
- Create: `app/service/cutline_pipeline.py`
- Modify: `app/service/cutline_service.py`（当前只有注释）
- Modify: `tests/cutline_complex_input/test_full_flow.py`（改为经由 `CutlineService.evaluate` 走通，断言对外契约）

门面输出范围（本期）：`warnings`（触发的断料预警，映射为 `WarningResult`）+ 候选机台放入 `manual_interventions`。`plans`/`return_suggestions` 不编造，留空列表。
对外字段映射：`process_from→upstream_process_code`、`process_to→downstream_process_code`、`net_rate_per_hour→net_rate`、`depletion_minutes→prediction_minutes`、`warning_time←snapshot.current_time`。

- [ ] **Step 1: 写全链路失败测试**

整体替换 `tests/cutline_complex_input/test_full_flow.py`：

```python
from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.schemas.response_schema import CutlineEvaluateResponse
from app.service.cutline_service import CutlineService


COMPLEX_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_complex_input.json"


def evaluate_complex():
    snapshot = MockAdapter().load(COMPLEX_INPUT_PATH)
    return CutlineService().evaluate(snapshot)


def test_service_returns_cutline_evaluate_response():
    response = evaluate_complex()

    assert isinstance(response, CutlineEvaluateResponse)
    assert response.success is True
    assert response.plans == []
    assert response.return_suggestions == []


def test_service_maps_three_triggered_stockout_warnings():
    response = evaluate_complex()

    assert len(response.warnings) == 3
    assert {warning.product_code for warning in response.warnings} == {
        "HG210R",
        "HG182N",
        "HG182T",
    }
    hg210r = next(w for w in response.warnings if w.product_code == "HG210R")
    assert hg210r.warning_type == "stockout"
    assert hg210r.upstream_process_code == "PK"
    assert hg210r.downstream_process_code == "OX"
    assert hg210r.net_rate == 6000
    assert hg210r.prediction_minutes == 10


def test_service_surfaces_candidates_as_manual_interventions_in_urgency_order():
    response = evaluate_complex()

    assert [
        intervention.warning.product_code
        for intervention in response.manual_interventions
    ] == ["HG210R", "HG182N", "HG182T"]

    hg182t = next(
        intervention
        for intervention in response.manual_interventions
        if intervention.warning.product_code == "HG182T"
    )
    codes = {machine.equipment_code for machine in hg182t.candidate_machines}
    assert {"zr_hg182r_candidate", "zr_hg182r_candidate_2"}.issubset(codes)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/cutline_complex_input/test_full_flow.py -q`
Expected: FAIL（`ImportError: cannot import name 'CutlineService'` 或其 evaluate 未实现）

- [ ] **Step 3: 实现 cutline_pipeline.py**

```python
# 算法管道：按序串联净速率→耗尽→预警→候选，持有同一 snapshot 上下文

from dataclasses import dataclass
from typing import List, Optional

from app.core.candidate_machine.stockout_candidate_finder import StockoutCandidateFinder
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RateStrategy, RealtimeFirstRateStrategy
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)
from app.core.warning.stockout_warning import StockoutWarningEvaluator
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import (
    CandidateResult,
    DepletionResult,
    NetRateResult,
    StockoutWarningResult,
)


@dataclass
class PipelineResult:
    net_rates: List[NetRateResult]
    depletions: List[DepletionResult]
    warnings: List[StockoutWarningResult]
    candidates: List[CandidateResult]


class CutlinePipeline:
    """轻量编排：构建一次组件，run 时按序流转结果。"""

    def __init__(self, rate_strategy: Optional[RateStrategy] = None):
        strategy = rate_strategy or RealtimeFirstRateStrategy()
        self._net_rate = NetRateCalculator(strategy)
        self._depletion = DepletionTimeCalculator()
        self._warning = StockoutWarningEvaluator()
        self._candidate = StockoutCandidateFinder(strategy)

    def run(self, snapshot: CutlineSnapshot) -> PipelineResult:
        net_rates = self._net_rate.calculate(snapshot)
        depletions = self._depletion.calculate(snapshot, net_rates)
        warnings = self._warning.evaluate(snapshot, depletions)
        candidates = self._candidate.find(snapshot, warnings)
        return PipelineResult(net_rates, depletions, warnings, candidates)
```

- [ ] **Step 4: 实现 cutline_service.py（门面 + 映射）**

整体替换为：

```python
# 切线评估门面：调用管道，把内部结果对象映射为对外 CutlineEvaluateResponse

from typing import Optional

from app.schemas.request_schema import CutlineSnapshot
from app.schemas.response_schema import (
    CutlineEvaluateResponse,
    ManualIntervention,
    SelectedMachine,
    WarningResult,
)
from app.schemas.result_schema import CandidateResult, StockoutWarningResult
from app.service.cutline_pipeline import CutlinePipeline


class CutlineService:
    """对外统一入口：evaluate(snapshot) -> CutlineEvaluateResponse。"""

    def __init__(self, pipeline: Optional[CutlinePipeline] = None):
        self._pipeline = pipeline or CutlinePipeline()

    def evaluate(self, snapshot: CutlineSnapshot) -> CutlineEvaluateResponse:
        result = self._pipeline.run(snapshot)

        warning_by_segment = {}
        warnings_out = []
        for warning in result.warnings:
            if not warning.warning_triggered:
                continue
            warning_result = self._to_warning_result(snapshot, warning)
            warnings_out.append(warning_result)
            warning_by_segment[self._segment_key(warning)] = warning_result

        interventions = []
        for candidate in result.candidates:
            warning_result = warning_by_segment.get(self._segment_key(candidate))
            if warning_result is None:
                continue
            interventions.append(
                self._to_manual_intervention(warning_result, candidate)
            )

        return CutlineEvaluateResponse(
            success=True,
            message="",
            warnings=warnings_out,
            plans=[],
            manual_interventions=interventions,
            return_suggestions=[],
        )

    def _segment_key(self, item):
        return (item.buffer_code, item.product_code, item.process_from, item.process_to)

    def _to_warning_result(
        self,
        snapshot: CutlineSnapshot,
        warning: StockoutWarningResult,
    ) -> WarningResult:
        return WarningResult(
            warning_time=snapshot.current_time,
            warning_type=warning.warning_type,
            buffer_code=warning.buffer_code,
            upstream_process_code=warning.process_from,
            downstream_process_code=warning.process_to,
            product_code=warning.product_code,
            inventory_quantity=warning.inventory_quantity,
            net_rate=warning.net_rate_per_hour,
            prediction_minutes=warning.depletion_minutes,
            cutline_lead_minutes=warning.cutline_lead_minutes,
        )

    def _to_manual_intervention(
        self,
        warning_result: WarningResult,
        candidate: CandidateResult,
    ) -> ManualIntervention:
        candidate_machines = [
            SelectedMachine(
                equipment_code=machine.equipment_code,
                current_product_code=machine.current_product_code,
                target_product_code=machine.target_product_code,
                wafer_size=machine.wafer_size,
                shape_code=machine.shape_code,
                process_code=machine.process_code,
                contribution_capacity=machine.contribution_capacity_per_hour,
            )
            for machine in candidate.candidates
        ]
        return ManualIntervention(
            warning=warning_result,
            reason=candidate.reason or candidate.candidate_status,
            candidate_machines=candidate_machines,
        )
```

注：`WarningResult.downstream_process_code` 必填 `str`，而 `process_to` 源头是 `Optional[str]`；examples 中始终有值，故安全。若将来甲方数据可能缺 `process_to`，再在此处兜底（本期不做，YAGNI）。

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/cutline_complex_input/test_full_flow.py -q`
Expected: PASS（3 passed）

- [ ] **Step 6: 全量回归**

Run: `python -m pytest -q`
Expected: 末行 `all passed`（约 40 passed），无 ERROR

- [ ] **Step 7: 提交**

```bash
git add app/service/cutline_pipeline.py app/service/cutline_service.py tests/cutline_complex_input/test_full_flow.py
git commit -m "新增 CutlinePipeline 编排与 CutlineService 门面，全链路打通"
```

---

### Task 11: 清理 — 删 rate_utils.py、删所有 _get_value、删重复 safe_float

**Files:**
- Delete: `app/core/net_rate/rate_utils.py`
- 确认无残留：`_get_value`、重复 `safe_float`、对 `rate_utils` 的 import

- [ ] **Step 1: 全局搜索残留引用**

Run: `python -m pytest -q` 之前先搜索：
```bash
grep -rn "_get_value\|rate_utils\|def safe_float" app/ ; echo "exit: $?"
```
Expected: 仅可能命中 `app/core/net_rate/rate_utils.py` 自身（待删）与 `app/utils/numeric.py` 的 `def safe_float`（唯一保留实现）。算法四模块、candidate、net_rate 内不应再有 `_get_value` 或 `rate_utils` import（前序任务整体替换时已移除）。

若发现任一算法模块仍 import `rate_utils` 或仍定义 `_get_value`/`safe_float`，说明前序任务整体替换不彻底 — 回到对应模块用 `app.utils.numeric.safe_float` 替换并删掉本地副本。

- [ ] **Step 2: 删除 rate_utils.py**

```bash
git rm app/core/net_rate/rate_utils.py
```

- [ ] **Step 3: 跑全量确认无回归**

Run: `python -m pytest -q`
Expected: 末行 `all passed`（约 40 passed），无 ImportError/ERROR

- [ ] **Step 4: 复查 _get_value 彻底清除**

Run:
```bash
grep -rn "_get_value" app/ ; echo "matches above (expect none)"
```
Expected: 无输出（0 命中）

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "清理重复 _get_value/safe_float 与废弃 rate_utils"
```

---

## 验收标准（全部满足才算完成）

- [ ] `python -m pytest -q` 全绿，无 ERROR/skip。
- [ ] 复杂场景行为不变：净速率 6000/4000/3600/2500；耗尽 10/15/20/120；触发 {HG210R,HG182N,HG182T}；候选 HG210R/HG182T 为 found、HG182N 为 manual_intervention_required。
- [ ] 算法四模块、pipeline、service 内 **0 处** `dict` 取值、**0 处** `_get_value`、**0 处** 本地 `safe_float`。
- [ ] `rate_utils.py` 已删除；`safe_float` 仅存于 `app/utils/numeric.py`。
- [ ] `CutlineService.evaluate(snapshot)` 返回 `CutlineEvaluateResponse`，`plans`/`return_suggestions` 为空列表（不编造）。

