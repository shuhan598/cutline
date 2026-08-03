# 切线主链剩余模块实施计划（3.3 逐台选取 / 溢满 / 切回 / 丝网）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 `CutlinePipeline` 上补齐 3.3 断料逐台选取、段级溢满预警与切走选取、切回判断、丝网特殊处理，并把内部结果映射进 `CutlineEvaluateResponse`。

**Architecture:** 沿用"组件吃 Pydantic 对象、吐内部结果对象 → 门面映射对外响应"。新增组件挂进 `CutlinePipeline.run()` 串行链；`PipelineResult` 扩字段；`CutlineService` 门面把 `PlanResult/ManualInterventionResult/OverflowWarningResult/ReturnResult` 映射为 `plans/manual_interventions/warnings/return_suggestions/tracked_events`。切回用无状态回吐（`CutlineEvent.negative_start_time` 进出）。

**Tech Stack:** Python 3.13、Pydantic 2.11、pytest。

**基线：** 起步 `python -m pytest -q` 为 41 passed。本计划新增测试，复杂/示例场景既有数值断言不得变。规格依据 `docs/superpowers/specs/2026-06-20-cutline-remaining-modules-design.md`。

---

## 任务依赖顺序

1. Task 1 — 契约与内部结果对象 schema
2. Task 2 — `StockoutCandidateFinder` 填充 idle_rate/utilization_rate
3. Task 3 — `CutlinePlanBuilder` 断料逐台选取
4. Task 4 — `OverflowWarningEvaluator` + 溢满 fixture
5. Task 5 — `OverflowCandidateFinder` 切走候选池
6. Task 6 — `CutlinePlanBuilder` 溢满切走选取
7. Task 7 — `ReturnEvaluator` 切回 + 切回 fixture
8. Task 8 — `SilkScreenHandler` 丝网 + 丝网 fixture
9. Task 9 — `CutlinePipeline` 扩展接线
10. Task 10 — `CutlineService` 门面映射 + 全链路测试 + 全量回归

---

### Task 1: 契约与内部结果对象 schema

**Files:**
- Modify: `app/schemas/common_schema.py`（`CutlineEvent` 增 `negative_start_time`）
- Modify: `app/schemas/result_schema.py`（`CandidateMachine` 增两字段；新增 4 个结果对象）
- Modify: `app/schemas/response_schema.py`（`CutlineEvaluateResponse` 增 `tracked_events`）
- Test: `tests/schemas/test_remaining_schema.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `tests/schemas/test_remaining_schema.py`：

```python
from datetime import datetime

from app.schemas.common_schema import CutlineEvent
from app.schemas.response_schema import CutlineEvaluateResponse
from app.schemas.result_schema import (
    CandidateMachine,
    ManualInterventionResult,
    OverflowWarningResult,
    PlanResult,
    ReturnResult,
)


def test_cutline_event_has_negative_start_time_default_none():
    event = CutlineEvent(
        equipment_code="zr03",
        cut_time=datetime(2026, 6, 20, 10, 0, 0),
        previous_product_code="HG182R",
        next_product_code="HG182T",
    )
    assert event.negative_start_time is None


def test_candidate_machine_has_idle_and_utilization_defaults():
    machine = CandidateMachine(
        equipment_code="zr03",
        process_code="ZR",
        target_product_code="HG182T",
        current_output_rate_per_hour=8000.0,
        reason="x",
    )
    assert machine.idle_rate is None
    assert machine.utilization_rate is None


def test_overflow_warning_result_fields():
    result = OverflowWarningResult(
        buffer_code="BUF",
        product_code="HG182T",
        process_from="ZR",
        process_to="PK",
        warning_type="overflow",
        warning_triggered=True,
        reason="overflow_time_within_lead_time",
        segment_inventory=18000.0,
        segment_capacity=20000.0,
        net_rate_per_hour=-4000.0,
        overflow_minutes=30.0,
        cutline_lead_minutes=30.0,
    )
    assert result.warning_type == "overflow"
    assert result.overflow_minutes == 30.0


def test_plan_result_holds_selected_machines():
    machine = CandidateMachine(
        equipment_code="zr03",
        process_code="ZR",
        target_product_code="HG182T",
        current_output_rate_per_hour=8000.0,
        contribution_capacity_per_hour=8000.0,
        reason="x",
    )
    plan = PlanResult(
        buffer_code="BUF",
        product_code="HG182T",
        process_from="ZR",
        process_to="PK",
        warning_type="stockout",
        selected_machines=[machine],
        total_contribution_capacity=8000.0,
        remaining_capacity_gap=-4800.0,
    )
    assert plan.selected_machines[0].equipment_code == "zr03"
    assert plan.requires_silk_screen_clear is False


def test_manual_intervention_result_required_capacity():
    result = ManualInterventionResult(
        buffer_code="BUF",
        product_code="HG182N",
        process_from="ZR",
        process_to="PK",
        warning_type="stockout",
        required_capacity=4000.0,
        reason="no_compatible_running_upstream_machine",
        candidates=[],
    )
    assert result.required_capacity == 4000.0


def test_return_result_triggered_flag():
    result = ReturnResult(
        equipment_code="zr03",
        product_code="HG182T",
        original_product_code="HG182R",
        buffer_code="BUF",
        process_from="ZR",
        process_to="PK",
        net_rate_per_hour=-4800.0,
        inventory_quantity=3200.0,
        negative_start_time=datetime(2026, 6, 20, 9, 35, 0),
        negative_duration_minutes=25.0,
        safety_inventory_quantity=2400.0,
        triggered=True,
    )
    assert result.triggered is True


def test_response_has_tracked_events_default_empty():
    response = CutlineEvaluateResponse()
    assert response.tracked_events == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/schemas/test_remaining_schema.py -q`
Expected: FAIL（`ImportError: cannot import name 'OverflowWarningResult'` 等）

- [ ] **Step 3: 实现 — `common_schema.py` 给 `CutlineEvent` 增字段**

在 `CutlineEvent` 的 `next_product_code` 字段下一行插入：

```python
    negative_start_time: Optional[datetime] = Field(
        default=None,
        description="净消耗速率首次转负时间，由后端跨周期持久化并回吐",
    )
```

- [ ] **Step 4: 实现 — `result_schema.py` 增字段与结果对象**

在 `CandidateMachine` 的 `contribution_capacity_per_hour` 字段下一行插入：

```python
    utilization_rate: Optional[float] = None
    idle_rate: Optional[float] = None
```

在文件末尾追加：

```python
class OverflowWarningResult(BaseModel):
    """段级溢满预警评估结果。"""

    buffer_code: str
    product_code: str
    process_from: str
    process_to: Optional[str] = None
    warning_type: str = "overflow"
    warning_triggered: bool
    reason: str
    segment_inventory: float
    segment_capacity: float
    net_rate_per_hour: float
    overflow_minutes: Optional[float] = None
    cutline_lead_minutes: float


class PlanResult(BaseModel):
    """切线方案（断料/溢满共用）。"""

    buffer_code: str
    product_code: str
    process_from: str
    process_to: Optional[str] = None
    warning_type: str
    selected_machines: List[CandidateMachine] = Field(default_factory=list)
    total_contribution_capacity: float = 0.0
    remaining_capacity_gap: Optional[float] = None
    requires_silk_screen_clear: bool = False
    silk_screen_clear_minutes: Optional[float] = None


class ManualInterventionResult(BaseModel):
    """未补足/无候选的人工介入结果。"""

    buffer_code: str
    product_code: str
    process_from: str
    process_to: Optional[str] = None
    warning_type: str
    required_capacity: float
    reason: str
    candidates: List[CandidateMachine] = Field(default_factory=list)


class ReturnResult(BaseModel):
    """单个被跟踪切线事件的切回判断结果。"""

    equipment_code: str
    product_code: str
    original_product_code: Optional[str] = None
    buffer_code: Optional[str] = None
    process_from: Optional[str] = None
    process_to: Optional[str] = None
    net_rate_per_hour: Optional[float] = None
    inventory_quantity: Optional[float] = None
    negative_start_time: Optional[datetime] = None
    negative_duration_minutes: Optional[float] = None
    safety_inventory_quantity: Optional[float] = None
    triggered: bool = False
```

在 `result_schema.py` 顶部 import 区把 `datetime` 引入（`from datetime import datetime`，加在 `from typing import` 上一行）。

- [ ] **Step 5: 实现 — `response_schema.py` 增 `tracked_events`**

在 `CutlineEvaluateResponse` 的 `return_suggestions` 字段下一行插入：

```python
    tracked_events: List["CutlineEvent"] = Field(
        default_factory=list,
        description="回吐给后端续存的被跟踪切线事件（含最新 negative_start_time）",
    )
```

并在 `response_schema.py` 顶部 import 区加：

```python
from app.schemas.common_schema import CutlineEvent
```

（若产生前向引用问题，在文件末尾追加 `CutlineEvaluateResponse.model_rebuild()`。）

- [ ] **Step 6: 跑测试确认通过 + 不回归**

Run: `python -m pytest tests/schemas/test_remaining_schema.py -q && python -m pytest -q`
Expected: 新测试 PASS；全量从 41 passed 增至 48 passed

- [ ] **Step 7: 提交**

```bash
git add app/schemas/common_schema.py app/schemas/result_schema.py app/schemas/response_schema.py tests/schemas/test_remaining_schema.py
git commit -m "新增切线主链契约与内部结果对象 schema"
```

---

### Task 2: StockoutCandidateFinder 填充 idle_rate/utilization_rate

**Files:**
- Modify: `app/core/candidate_machine/stockout_candidate_finder.py`
- Test: `tests/cutline_sample_input/test_candidate_idle_rate.py`（新建）

利用率 = 当前产出 / 当前型号静态产能；空闲度 = 1 − 利用率；静态产能缺失或 ≤0 时两者均为 None。

- [ ] **Step 1: 写失败测试**

新建 `tests/cutline_sample_input/test_candidate_idle_rate.py`：

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


SAMPLE_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_sample_input.json"


def build_candidates():
    snapshot = MockAdapter().load(SAMPLE_INPUT_PATH)
    strategy = RealtimeFirstRateStrategy()
    net_rates = NetRateCalculator(strategy).calculate(snapshot)
    depletions = DepletionTimeCalculator().calculate(snapshot, net_rates)
    warnings = StockoutWarningEvaluator().evaluate(snapshot, depletions)
    return StockoutCandidateFinder(strategy).find(snapshot, warnings)


def test_candidate_zr03_idle_rate_is_zero_at_full_utilization():
    results = build_candidates()
    hg182t = next(r for r in results if r.product_code == "HG182T")
    zr03 = next(c for c in hg182t.candidates if c.equipment_code == "zr03")
    # zr03 产出 8000 / 静态产能 8000 = 利用率 1.0，空闲度 0.0
    assert zr03.utilization_rate == 1.0
    assert zr03.idle_rate == 0.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/cutline_sample_input/test_candidate_idle_rate.py -q`
Expected: FAIL（`idle_rate` 为 None，断言不等）

- [ ] **Step 3: 实现 — 在 finder 内计算并填充**

在 `stockout_candidate_finder.py` 的 `_for_warning` 构造 `CandidateMachine` 处，先算出利用率/空闲度。把 `CandidateMachine(...)` 调用替换为如下（新增两参数前先计算）：

在 `for machine in snapshot.machine_statuses:` 循环体内、`candidates.append(` 之前插入：

```python
            current_output = self._rate_strategy.output_rate(machine)
            current_capacity = self._actual_capacity(
                snapshot, machine.equipment_code, machine.product_code
            )
            if current_capacity and current_capacity > 0:
                utilization_rate = current_output / current_capacity
                idle_rate = 1.0 - utilization_rate
            else:
                utilization_rate = None
                idle_rate = None
```

并把该 `CandidateMachine(...)` 中 `current_output_rate_per_hour=self._rate_strategy.output_rate(machine),` 改为 `current_output_rate_per_hour=current_output,`，再在 `contribution_capacity_per_hour=...` 行下方插入：

```python
                    utilization_rate=utilization_rate,
                    idle_rate=idle_rate,
```

- [ ] **Step 4: 跑测试确认通过 + 不回归**

Run: `python -m pytest tests/cutline_sample_input/test_candidate_idle_rate.py -q && python -m pytest -q`
Expected: 新测试 PASS；全量 49 passed

- [ ] **Step 5: 提交**

```bash
git add app/core/candidate_machine/stockout_candidate_finder.py tests/cutline_sample_input/test_candidate_idle_rate.py
git commit -m "候选机台补充利用率/空闲度字段"
```

---

### Task 3: CutlinePlanBuilder 断料逐台选取

**Files:**
- Create: `app/core/cutline_plan/__init__.py`（空文件）
- Create: `app/core/cutline_plan/plan_builder.py`
- Test: `tests/cutline_sample_input/test_plan_builder.py`（新建）

逐台选取 + 借出影响校验。借出校验用 `net_rates`（区间速率）+ `depletions`（区间库存）模拟重算。贡献产能直接用 `candidate.contribution_capacity_per_hour`（= 静态表7[M, 预警型号X]）。

- [ ] **Step 1: 写失败测试**

新建 `tests/cutline_sample_input/test_plan_builder.py`：

```python
from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.candidate_machine.stockout_candidate_finder import StockoutCandidateFinder
from app.core.cutline_plan.plan_builder import CutlinePlanBuilder
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)
from app.core.warning.stockout_warning import StockoutWarningEvaluator
from app.schemas.result_schema import ManualInterventionResult, PlanResult


SAMPLE_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_sample_input.json"


def build():
    snapshot = MockAdapter().load(SAMPLE_INPUT_PATH)
    strategy = RealtimeFirstRateStrategy()
    net_rates = NetRateCalculator(strategy).calculate(snapshot)
    depletions = DepletionTimeCalculator().calculate(snapshot, net_rates)
    warnings = StockoutWarningEvaluator().evaluate(snapshot, depletions)
    candidates = StockoutCandidateFinder(strategy).find(snapshot, warnings)
    plans, interventions = CutlinePlanBuilder().build_stockout(
        warnings, candidates, net_rates, depletions
    )
    return plans, interventions


def test_hg182t_plan_selects_zr03_and_closes_gap():
    plans, interventions = build()
    assert len(plans) == 1
    plan = plans[0]
    assert isinstance(plan, PlanResult)
    assert plan.product_code == "HG182T"
    assert plan.warning_type == "stockout"
    assert [m.equipment_code for m in plan.selected_machines] == ["zr03"]
    assert plan.total_contribution_capacity == 8000
    assert plan.remaining_capacity_gap == -4800  # 缺口 3200 - 贡献 8000
    assert interventions == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/cutline_sample_input/test_plan_builder.py -q`
Expected: FAIL（`ModuleNotFoundError: app.core.cutline_plan.plan_builder`）

- [ ] **Step 3: 实现 — 新建 `app/core/cutline_plan/__init__.py`（空）与 `plan_builder.py`**

```python
# 切线方案构建：断料逐台选取（含借出影响校验）+ 后续溢满切走（Task 6 追加）

from typing import List, Optional, Tuple

from app.schemas.result_schema import (
    CandidateResult,
    DepletionResult,
    ManualInterventionResult,
    NetRateResult,
    PlanResult,
    StockoutWarningResult,
)


class CutlinePlanBuilder:
    """从候选池逐台选取，产出切线方案或人工介入。"""

    def build_stockout(
        self,
        warnings: List[StockoutWarningResult],
        candidate_results: List[CandidateResult],
        net_rates: List[NetRateResult],
        depletions: List[DepletionResult],
        silk_screen_process_codes: Optional[set] = None,
    ) -> Tuple[List[PlanResult], List[ManualInterventionResult]]:
        silk = silk_screen_process_codes or set()
        warning_map = {self._key(w): w for w in warnings}
        net_map = {self._key(n): n for n in net_rates}
        dep_map = {self._key(d): d for d in depletions}

        plans: List[PlanResult] = []
        interventions: List[ManualInterventionResult] = []

        for cr in candidate_results:
            warning = warning_map.get(self._key(cr))
            if warning is None:
                continue
            gap = warning.net_rate_per_hour

            if not cr.candidate_found or not cr.candidates:
                interventions.append(
                    self._intervention(cr, warning, gap, cr.candidates)
                )
                continue

            pool = sorted(cr.candidates, key=self._idle_sort_key, reverse=True)
            selected = []
            for machine in pool:
                if gap <= 0:
                    break
                contribution = machine.contribution_capacity_per_hour
                if not contribution or contribution <= 0:
                    continue
                if self._borrow_harms_origin(machine, warning, net_map, dep_map):
                    continue
                selected.append(machine)
                gap -= contribution

            if gap <= 0 and selected:
                requires_clear = any(m.process_code in silk for m in selected)
                plans.append(
                    PlanResult(
                        buffer_code=warning.buffer_code,
                        product_code=warning.product_code,
                        process_from=warning.process_from,
                        process_to=warning.process_to,
                        warning_type="stockout",
                        selected_machines=selected,
                        total_contribution_capacity=sum(
                            m.contribution_capacity_per_hour for m in selected
                        ),
                        remaining_capacity_gap=gap,
                        requires_silk_screen_clear=requires_clear,
                    )
                )
            else:
                interventions.append(
                    self._intervention(cr, warning, gap, cr.candidates)
                )

        return plans, interventions

    def _borrow_harms_origin(self, machine, warning, net_map, dep_map) -> bool:
        origin_key = (
            warning.buffer_code,
            machine.current_product_code,
            warning.process_from,
            warning.process_to,
        )
        origin_net = net_map.get(origin_key)
        if origin_net is None:
            return False
        new_upstream = origin_net.upstream_output_per_hour - machine.current_output_rate_per_hour
        new_net = origin_net.downstream_input_per_hour - new_upstream
        if new_net <= 0:
            return False
        origin_dep = dep_map.get(origin_key)
        inventory = origin_dep.inventory_quantity if origin_dep else 0.0
        new_depletion_minutes = inventory / new_net * 60
        return new_depletion_minutes <= warning.cutline_lead_minutes

    def _intervention(self, cr, warning, gap, candidates) -> ManualInterventionResult:
        reason = (
            cr.reason
            if cr.reason
            else "capacity_gap_not_closed_by_candidate_pool"
        )
        return ManualInterventionResult(
            buffer_code=warning.buffer_code,
            product_code=warning.product_code,
            process_from=warning.process_from,
            process_to=warning.process_to,
            warning_type="stockout",
            required_capacity=max(gap, 0.0),
            reason=reason,
            candidates=candidates,
        )

    def _idle_sort_key(self, machine) -> float:
        return machine.idle_rate if machine.idle_rate is not None else -1.0

    def _key(self, item):
        return (item.buffer_code, item.product_code, item.process_from, item.process_to)
```

- [ ] **Step 4: 跑测试确认通过 + 不回归**

Run: `python -m pytest tests/cutline_sample_input/test_plan_builder.py -q && python -m pytest -q`
Expected: 新测试 PASS；全量 50 passed

- [ ] **Step 5: 提交**

```bash
git add app/core/cutline_plan/__init__.py app/core/cutline_plan/plan_builder.py tests/cutline_sample_input/test_plan_builder.py
git commit -m "新增 CutlinePlanBuilder 断料逐台选取与借出校验"
```

---

### Task 4: OverflowWarningEvaluator + 溢满 fixture

**Files:**
- Create: `examples/cutline_overflow_input.json`
- Create: `app/core/warning/overflow_warning.py`
- Test: `tests/cutline_overflow_input/__init__.py`（空）、`tests/cutline_overflow_input/test_overflow_warning.py`（新建）

段级溢满：净速率<0 时，溢满预测 = (max_capacity − Σ段库存) / |净速率| × 60。Σ段库存按 buffer_code 跨型号跨区间求和。

- [ ] **Step 1: 新建 fixture `examples/cutline_overflow_input.json`**

```json
{
  "config": { "cutline_lead_minutes": 30 },
  "product_models": [
    { "product_code": "HG182T", "wafer_size": "182", "shape_code": "R" },
    { "product_code": "HG182R", "wafer_size": "182", "shape_code": "R" }
  ],
  "buffer_segments": [
    {
      "buffer_code": "BUF_ZR_PK",
      "service_process_codes": ["ZR", "PK"],
      "max_capacity": 20000
    }
  ],
  "buffer_inventories": [
    { "buffer_code": "BUF_ZR_PK", "product_code": "HG182T", "process_from": "ZR", "process_to": "PK", "inventory_quantity": 13000 },
    { "buffer_code": "BUF_ZR_PK", "product_code": "HG182R", "process_from": "ZR", "process_to": "PK", "inventory_quantity": 5000 }
  ],
  "machine_statuses": [
    { "equipment_code": "zr_t1", "process_code": "ZR", "status": "running", "product_code": "HG182T", "input_rate_per_hour": 8000, "output_rate_per_hour": 8000 },
    { "equipment_code": "pk_t1", "process_code": "PK", "status": "running", "product_code": "HG182T", "input_rate_per_hour": 4000, "output_rate_per_hour": 4000 },
    { "equipment_code": "zr_r1", "process_code": "ZR", "status": "running", "product_code": "HG182R", "input_rate_per_hour": 2000, "output_rate_per_hour": 2000 },
    { "equipment_code": "pk_r1", "process_code": "PK", "status": "running", "product_code": "HG182R", "input_rate_per_hour": 10000, "output_rate_per_hour": 10000 }
  ],
  "capacity_records": [
    { "equipment_code": "zr_t1", "product_code": "HG182T", "actual_capacity_per_hour": 8000, "process_time_minutes": 40 },
    { "equipment_code": "zr_t1", "product_code": "HG182R", "actual_capacity_per_hour": 4000, "process_time_minutes": 40 },
    { "equipment_code": "zr_r1", "product_code": "HG182R", "actual_capacity_per_hour": 2000, "process_time_minutes": 40 },
    { "equipment_code": "pk_t1", "product_code": "HG182T", "actual_capacity_per_hour": 4000, "process_time_minutes": 60 },
    { "equipment_code": "pk_r1", "product_code": "HG182R", "actual_capacity_per_hour": 10000, "process_time_minutes": 60 }
  ]
}
```

口径自检：HG182T 区间净速率 = 下游吞入 4000 − 上游产出 8000 = −4000（积累）；Σ段库存 = 13000+5000 = 18000；溢满预测 = (20000−18000)/4000×60 = 30min ≤ 30 → 触发。HG182R 区间净速率 = 10000−2000 = +8000（断料向，不出溢满）。

- [ ] **Step 2: 写失败测试**

新建空文件 `tests/cutline_overflow_input/__init__.py`，并写 `tests/cutline_overflow_input/test_overflow_warning.py`：

```python
from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.warning.overflow_warning import OverflowWarningEvaluator


OVERFLOW_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_overflow_input.json"


def build_overflow_warnings():
    snapshot = MockAdapter().load(OVERFLOW_INPUT_PATH)
    net_rates = NetRateCalculator(RealtimeFirstRateStrategy()).calculate(snapshot)
    return OverflowWarningEvaluator().evaluate(snapshot, net_rates), snapshot


def by_product(results):
    return {r.product_code: r for r in results}


def test_only_negative_net_rate_segments_produce_overflow_results():
    results, _ = build_overflow_warnings()
    products = {r.product_code for r in results}
    assert products == {"HG182T"}


def test_hg182t_overflow_triggers_at_thirty_minutes():
    result = by_product(build_overflow_warnings()[0])["HG182T"]
    assert result.warning_type == "overflow"
    assert result.warning_triggered is True
    assert result.reason == "overflow_time_within_lead_time"
    assert result.segment_inventory == 18000
    assert result.segment_capacity == 20000
    assert result.net_rate_per_hour == -4000
    assert result.overflow_minutes == 30
```

- [ ] **Step 3: 跑测试确认失败**

Run: `python -m pytest tests/cutline_overflow_input/test_overflow_warning.py -q`
Expected: FAIL（`ModuleNotFoundError: app.core.warning.overflow_warning`）

- [ ] **Step 4: 实现 — `app/core/warning/overflow_warning.py`**

```python
# 段级溢满预警：净速率<0 时按段总容量与段库存预测溢满时间

from typing import List

from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import NetRateResult, OverflowWarningResult
from app.utils.numeric import safe_float


class OverflowWarningEvaluator:
    """净速率为负（积累）的区间，按物理池段容量预测溢满。"""

    def evaluate(
        self,
        snapshot: CutlineSnapshot,
        net_rates: List[NetRateResult],
    ) -> List[OverflowWarningResult]:
        lead = safe_float(snapshot.config.cutline_lead_minutes)
        capacity_map = {
            segment.buffer_code: safe_float(segment.max_capacity)
            for segment in snapshot.buffer_segments
        }
        segment_inventory = self._segment_inventory(snapshot)

        results = []
        for net_rate in net_rates:
            if net_rate.net_rate_per_hour >= 0:
                continue
            capacity = capacity_map.get(net_rate.buffer_code, 0.0)
            inventory = segment_inventory.get(net_rate.buffer_code, 0.0)
            consume = abs(net_rate.net_rate_per_hour)
            overflow_minutes = (capacity - inventory) / consume * 60 if consume > 0 else None

            if overflow_minutes is not None and overflow_minutes <= lead:
                triggered = True
                reason = "overflow_time_within_lead_time"
            else:
                triggered = False
                reason = "overflow_time_beyond_lead_time"

            results.append(
                OverflowWarningResult(
                    buffer_code=net_rate.buffer_code,
                    product_code=net_rate.product_code,
                    process_from=net_rate.process_from,
                    process_to=net_rate.process_to,
                    warning_type="overflow",
                    warning_triggered=triggered,
                    reason=reason,
                    segment_inventory=inventory,
                    segment_capacity=capacity,
                    net_rate_per_hour=net_rate.net_rate_per_hour,
                    overflow_minutes=overflow_minutes,
                    cutline_lead_minutes=lead,
                )
            )
        return results

    def _segment_inventory(self, snapshot: CutlineSnapshot) -> dict:
        totals: dict = {}
        for inventory in snapshot.buffer_inventories:
            totals[inventory.buffer_code] = totals.get(inventory.buffer_code, 0.0) + safe_float(
                inventory.inventory_quantity
            )
        return totals
```

- [ ] **Step 5: 跑测试确认通过 + 不回归**

Run: `python -m pytest tests/cutline_overflow_input/test_overflow_warning.py -q && python -m pytest -q`
Expected: 新测试 PASS（2 passed）；全量 52 passed

- [ ] **Step 6: 提交**

```bash
git add examples/cutline_overflow_input.json app/core/warning/overflow_warning.py tests/cutline_overflow_input/__init__.py tests/cutline_overflow_input/test_overflow_warning.py
git commit -m "新增 OverflowWarningEvaluator 段级溢满预警"
```

---

### Task 5: OverflowCandidateFinder 切走候选池

**Files:**
- Create: `app/core/candidate_machine/overflow_candidate_finder.py`
- Test: `tests/cutline_overflow_input/test_overflow_candidate_finder.py`（新建）

切走候选条件：工序i 产出预警型号X、运行中、存在目标型号Y（同尺寸同形状、Y 区间净速率>0 有缺口）。

- [ ] **Step 1: 写失败测试**

新建 `tests/cutline_overflow_input/test_overflow_candidate_finder.py`：

```python
from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.candidate_machine.overflow_candidate_finder import OverflowCandidateFinder
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.warning.overflow_warning import OverflowWarningEvaluator


OVERFLOW_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_overflow_input.json"


def build():
    snapshot = MockAdapter().load(OVERFLOW_INPUT_PATH)
    strategy = RealtimeFirstRateStrategy()
    net_rates = NetRateCalculator(strategy).calculate(snapshot)
    warnings = OverflowWarningEvaluator().evaluate(snapshot, net_rates)
    return OverflowCandidateFinder(strategy).find(snapshot, warnings, net_rates)


def test_hg182t_overflow_candidate_is_zr_t1_with_target_hg182r():
    results = build()
    assert len(results) == 1
    result = results[0]
    assert result.product_code == "HG182T"
    assert result.candidate_found is True
    codes = {c.equipment_code for c in result.candidates}
    assert codes == {"zr_t1"}
    zr_t1 = result.candidates[0]
    assert zr_t1.current_product_code == "HG182T"
    assert zr_t1.target_product_code == "HG182R"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/cutline_overflow_input/test_overflow_candidate_finder.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 — `overflow_candidate_finder.py`**

```python
# 溢满切走候选池：在产工序i、生产预警型号X、存在同尺寸同形状且有缺口的目标型号Y

from typing import List

from app.core.net_rate.rate_strategy import RateStrategy
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import (
    CandidateMachine,
    CandidateResult,
    NetRateResult,
    OverflowWarningResult,
)


class OverflowCandidateFinder:
    """为触发的溢满预警查找可切走的在产机台及其目标型号Y。"""

    def __init__(self, rate_strategy: RateStrategy):
        self._rate_strategy = rate_strategy

    def find(
        self,
        snapshot: CutlineSnapshot,
        warnings: List[OverflowWarningResult],
        net_rates: List[NetRateResult],
    ) -> List[CandidateResult]:
        triggered = [w for w in warnings if w.warning_triggered]
        model_map = {m.product_code: m for m in snapshot.product_models}
        gap_map = {
            (n.buffer_code, n.product_code, n.process_from, n.process_to): n.net_rate_per_hour
            for n in net_rates
        }

        results = []
        for warning in triggered:
            target_y = self._first_target_with_gap(warning, model_map, gap_map)
            candidates = []
            if target_y is not None:
                for machine in snapshot.machine_statuses:
                    if machine.status != "running":
                        continue
                    if machine.process_code != warning.process_from:
                        continue
                    if machine.product_code != warning.product_code:
                        continue
                    y_model = model_map.get(target_y)
                    candidates.append(
                        CandidateMachine(
                            equipment_code=machine.equipment_code,
                            equipment_name=machine.equipment_name,
                            process_code=machine.process_code,
                            current_product_code=machine.product_code,
                            target_product_code=target_y,
                            wafer_size=y_model.wafer_size if y_model else None,
                            shape_code=y_model.shape_code if y_model else None,
                            current_output_rate_per_hour=self._rate_strategy.output_rate(machine),
                            contribution_capacity_per_hour=self._actual_capacity(
                                snapshot, machine.equipment_code, target_y
                            ),
                            reason="overflow_switch_away_to_target_with_gap",
                        )
                    )

            if candidates:
                results.append(
                    CandidateResult(
                        buffer_code=warning.buffer_code,
                        product_code=warning.product_code,
                        process_from=warning.process_from,
                        process_to=warning.process_to,
                        candidate_found=True,
                        candidate_status="candidate_found",
                        reason=None,
                        candidates=candidates,
                    )
                )
            else:
                results.append(
                    CandidateResult(
                        buffer_code=warning.buffer_code,
                        product_code=warning.product_code,
                        process_from=warning.process_from,
                        process_to=warning.process_to,
                        candidate_found=False,
                        candidate_status="manual_intervention_required",
                        reason="no_target_model_with_capacity_gap",
                        candidates=[],
                    )
                )
        return results

    def _first_target_with_gap(self, warning, model_map, gap_map):
        source_model = model_map.get(warning.product_code)
        if source_model is None:
            return None
        for product_code, model in model_map.items():
            if product_code == warning.product_code:
                continue
            if (model.wafer_size, model.shape_code) != (
                source_model.wafer_size,
                source_model.shape_code,
            ):
                continue
            net = gap_map.get(
                (warning.buffer_code, product_code, warning.process_from, warning.process_to)
            )
            if net is not None and net > 0:
                return product_code
        return None

    def _actual_capacity(self, snapshot: CutlineSnapshot, equipment_code, product_code):
        for record in snapshot.capacity_records:
            if record.equipment_code == equipment_code and record.product_code == product_code:
                return record.actual_capacity_per_hour
        return None
```

- [ ] **Step 4: 跑测试确认通过 + 不回归**

Run: `python -m pytest tests/cutline_overflow_input/test_overflow_candidate_finder.py -q && python -m pytest -q`
Expected: 新测试 PASS；全量 53 passed

- [ ] **Step 5: 提交**

```bash
git add app/core/candidate_machine/overflow_candidate_finder.py tests/cutline_overflow_input/test_overflow_candidate_finder.py
git commit -m "新增 OverflowCandidateFinder 溢满切走候选池"
```

---

### Task 6: CutlinePlanBuilder 溢满切走选取

**Files:**
- Modify: `app/core/cutline_plan/plan_builder.py`（增 `build_overflow` 方法）
- Test: `tests/cutline_overflow_input/test_overflow_plan.py`（新建）

按利用率降序逐台，对目标Y做切入影响校验（切过去不能让Y溢满），选中直到原区间净速率≥0（风险消解）。

- [ ] **Step 1: 写失败测试**

新建 `tests/cutline_overflow_input/test_overflow_plan.py`：

```python
from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.candidate_machine.overflow_candidate_finder import OverflowCandidateFinder
from app.core.cutline_plan.plan_builder import CutlinePlanBuilder
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.warning.overflow_warning import OverflowWarningEvaluator


OVERFLOW_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_overflow_input.json"


def build():
    snapshot = MockAdapter().load(OVERFLOW_INPUT_PATH)
    strategy = RealtimeFirstRateStrategy()
    net_rates = NetRateCalculator(strategy).calculate(snapshot)
    warnings = OverflowWarningEvaluator().evaluate(snapshot, net_rates)
    candidates = OverflowCandidateFinder(strategy).find(snapshot, warnings, net_rates)
    return CutlinePlanBuilder().build_overflow(snapshot, warnings, candidates, net_rates)


def test_overflow_plan_moves_zr_t1_to_hg182r_and_resolves_risk():
    plans, interventions = build()
    assert len(plans) == 1
    plan = plans[0]
    assert plan.warning_type == "overflow"
    assert plan.product_code == "HG182T"
    assert [m.equipment_code for m in plan.selected_machines] == ["zr_t1"]
    assert plan.selected_machines[0].target_product_code == "HG182R"
    assert interventions == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/cutline_overflow_input/test_overflow_plan.py -q`
Expected: FAIL（`AttributeError: 'CutlinePlanBuilder' object has no attribute 'build_overflow'`）

- [ ] **Step 3: 实现 — 在 `plan_builder.py` 顶部 import 增补，并加 `build_overflow`**

把 `plan_builder.py` 的 import 段替换为：

```python
from typing import List, Optional, Tuple

from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import (
    CandidateResult,
    DepletionResult,
    ManualInterventionResult,
    NetRateResult,
    OverflowWarningResult,
    PlanResult,
    StockoutWarningResult,
)
```

在 `CutlinePlanBuilder` 类内（`build_stockout` 之后）追加：

```python
    def build_overflow(
        self,
        snapshot: CutlineSnapshot,
        warnings: List[OverflowWarningResult],
        candidate_results: List[CandidateResult],
        net_rates: List[NetRateResult],
    ) -> Tuple[List[PlanResult], List[ManualInterventionResult]]:
        warning_map = {self._key(w): w for w in warnings if w.warning_triggered}
        net_map = {self._key(n): n for n in net_rates}
        capacity_map = {
            segment.buffer_code: segment.max_capacity
            for segment in snapshot.buffer_segments
        }
        segment_inventory = {}
        for inventory in snapshot.buffer_inventories:
            segment_inventory[inventory.buffer_code] = segment_inventory.get(
                inventory.buffer_code, 0.0
            ) + inventory.inventory_quantity

        plans: List[PlanResult] = []
        interventions: List[ManualInterventionResult] = []

        for cr in candidate_results:
            warning = warning_map.get(self._key(cr))
            if warning is None:
                continue

            source_net = net_map.get(self._key(cr))
            remaining = abs(source_net.net_rate_per_hour) if source_net else 0.0

            if not cr.candidate_found or not cr.candidates:
                interventions.append(
                    self._overflow_intervention(warning, remaining, cr.candidates)
                )
                continue

            pool = sorted(cr.candidates, key=self._utilization_sort_key, reverse=True)
            selected = []
            current_source_upstream = (
                source_net.upstream_output_per_hour if source_net else 0.0
            )
            source_downstream = source_net.downstream_input_per_hour if source_net else 0.0

            for machine in pool:
                target_net = net_map.get(
                    (
                        warning.buffer_code,
                        machine.target_product_code,
                        warning.process_from,
                        warning.process_to,
                    )
                )
                contribution = machine.contribution_capacity_per_hour or 0.0
                if self._switch_in_overflows_target(
                    warning, target_net, contribution, capacity_map, segment_inventory
                ):
                    continue
                selected.append(machine)
                current_source_upstream -= machine.current_output_rate_per_hour
                if source_downstream - current_source_upstream >= 0:
                    break

            new_source_net = source_downstream - current_source_upstream
            if selected and new_source_net >= 0:
                plans.append(
                    PlanResult(
                        buffer_code=warning.buffer_code,
                        product_code=warning.product_code,
                        process_from=warning.process_from,
                        process_to=warning.process_to,
                        warning_type="overflow",
                        selected_machines=selected,
                        total_contribution_capacity=sum(
                            m.contribution_capacity_per_hour or 0.0 for m in selected
                        ),
                        remaining_capacity_gap=new_source_net,
                    )
                )
            else:
                interventions.append(
                    self._overflow_intervention(warning, max(new_source_net, 0.0), cr.candidates)
                )

        return plans, interventions

    def _switch_in_overflows_target(
        self, warning, target_net, contribution, capacity_map, segment_inventory
    ) -> bool:
        if target_net is None:
            return True
        new_target_net = target_net.net_rate_per_hour - contribution
        if new_target_net >= 0:
            return False
        capacity = capacity_map.get(warning.buffer_code, 0.0)
        inventory = segment_inventory.get(warning.buffer_code, 0.0)
        overflow_minutes = (capacity - inventory) / abs(new_target_net) * 60
        return overflow_minutes <= warning.cutline_lead_minutes

    def _overflow_intervention(self, warning, remaining, candidates) -> ManualInterventionResult:
        return ManualInterventionResult(
            buffer_code=warning.buffer_code,
            product_code=warning.product_code,
            process_from=warning.process_from,
            process_to=warning.process_to,
            warning_type="overflow",
            required_capacity=remaining,
            reason="overflow_risk_not_resolved_by_candidate_pool",
            candidates=candidates,
        )

    def _utilization_sort_key(self, machine) -> float:
        return machine.utilization_rate if machine.utilization_rate is not None else -1.0
```

切入校验自检：zr_t1 切到 HG182R，HG182R 区间原净速率 +8000，贡献 4000 → new = 8000−4000 = +4000 ≥0 → 不溢满，通过。选中后 HG182T 上游 8000−8000=0，new 源净速率 = 4000−0 = +4000 ≥0 → 风险消解。

- [ ] **Step 4: 跑测试确认通过 + 不回归**

Run: `python -m pytest tests/cutline_overflow_input/test_overflow_plan.py -q && python -m pytest -q`
Expected: 新测试 PASS；全量 54 passed

- [ ] **Step 5: 提交**

```bash
git add app/core/cutline_plan/plan_builder.py tests/cutline_overflow_input/test_overflow_plan.py
git commit -m "CutlinePlanBuilder 增溢满切走逐台选取"
```

---

### Task 7: ReturnEvaluator 切回判断 + 切回 fixture

**Files:**
- Create: `examples/cutline_return_input.json`
- Create: `app/core/return_judge/__init__.py`（空）、`app/core/return_judge/return_evaluator.py`
- Test: `tests/cutline_return_input/__init__.py`（空）、`tests/cutline_return_input/test_return_evaluator.py`（新建）

无状态回吐：净速率<0 时若 `negative_start_time` 为空则置当前时间；持续时长>稳定窗口 且 库存>安全水位 → 触发。净速率≥0 → 清零。

- [ ] **Step 1: 新建 fixture `examples/cutline_return_input.json`**

```json
{
  "current_time": "2026-06-20T10:00:00",
  "config": { "cutline_lead_minutes": 30, "stability_window_minutes": 20 },
  "product_models": [
    { "product_code": "HG182T", "wafer_size": "182", "shape_code": "R" },
    { "product_code": "HG182R", "wafer_size": "182", "shape_code": "R" }
  ],
  "buffer_segments": [
    { "buffer_code": "BUF_ZR_PK", "service_process_codes": ["ZR", "PK"], "max_capacity": 156000 }
  ],
  "buffer_inventories": [
    { "buffer_code": "BUF_ZR_PK", "product_code": "HG182T", "process_from": "ZR", "process_to": "PK", "inventory_quantity": 5000 },
    { "buffer_code": "BUF_ZR_PK", "product_code": "HG182R", "process_from": "ZR", "process_to": "PK", "inventory_quantity": 1000 }
  ],
  "machine_statuses": [
    { "equipment_code": "zr01", "process_code": "ZR", "status": "running", "product_code": "HG182T", "input_rate_per_hour": 8000, "output_rate_per_hour": 8000 },
    { "equipment_code": "zr03", "process_code": "ZR", "status": "running", "product_code": "HG182T", "input_rate_per_hour": 8000, "output_rate_per_hour": 8000 },
    { "equipment_code": "pk01", "process_code": "PK", "status": "running", "product_code": "HG182T", "input_rate_per_hour": 9600, "output_rate_per_hour": 9600 },
    { "equipment_code": "zr_r", "process_code": "ZR", "status": "running", "product_code": "HG182R", "input_rate_per_hour": 4000, "output_rate_per_hour": 4000 },
    { "equipment_code": "pk_r", "process_code": "PK", "status": "running", "product_code": "HG182R", "input_rate_per_hour": 4000, "output_rate_per_hour": 4000 }
  ],
  "active_cutline_events": [
    { "equipment_code": "zr03", "cut_time": "2026-06-20T09:30:00", "previous_product_code": "HG182R", "next_product_code": "HG182T", "negative_start_time": "2026-06-20T09:35:00" },
    { "equipment_code": "zr_r", "cut_time": "2026-06-20T09:40:00", "previous_product_code": "HG182T", "next_product_code": "HG182R", "negative_start_time": "2026-06-20T09:50:00" }
  ]
}
```

口径自检：HG182T 区间 净速率 = 下游 9600 − 上游(8000+8000)16000 = −6400（积累）；安全水位 = 30/60×6400 = 3200；库存 5000 > 3200；持续 = 10:00−09:35 = 25min > 20 → zr03 触发。HG182R 区间 净速率 = 4000 − 4000 = 0 ≥0 → zr_r 清零、不触发。

- [ ] **Step 2: 写失败测试**

新建空文件 `tests/cutline_return_input/__init__.py`，并写 `tests/cutline_return_input/test_return_evaluator.py`：

```python
from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RealtimeFirstRateStrategy
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)
from app.core.return_judge.return_evaluator import ReturnEvaluator


RETURN_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_return_input.json"


def build():
    snapshot = MockAdapter().load(RETURN_INPUT_PATH)
    net_rates = NetRateCalculator(RealtimeFirstRateStrategy()).calculate(snapshot)
    depletions = DepletionTimeCalculator().calculate(snapshot, net_rates)
    return ReturnEvaluator().evaluate(snapshot, net_rates, depletions)


def by_equipment(results):
    return {r.equipment_code: r for r in results}


def test_returns_one_result_per_tracked_event():
    results = build()
    assert len(results) == 2


def test_zr03_triggers_return_when_three_conditions_met():
    zr03 = by_equipment(build())["zr03"]
    assert zr03.net_rate_per_hour == -6400
    assert zr03.inventory_quantity == 5000
    assert zr03.negative_duration_minutes == 25
    assert zr03.safety_inventory_quantity == 3200
    assert zr03.triggered is True


def test_zr_r_clears_negative_start_time_when_net_rate_non_negative():
    zr_r = by_equipment(build())["zr_r"]
    assert zr_r.net_rate_per_hour == 0
    assert zr_r.negative_start_time is None
    assert zr_r.triggered is False
```

- [ ] **Step 3: 跑测试确认失败**

Run: `python -m pytest tests/cutline_return_input/test_return_evaluator.py -q`
Expected: FAIL（`ModuleNotFoundError: app.core.return_judge.return_evaluator`）

- [ ] **Step 4: 实现 — 新建 `app/core/return_judge/__init__.py`（空）与 `return_evaluator.py`**

```python
# 切回判断：遍历被跟踪切线事件，按净速率/持续时长/安全水位三条件判定，并回吐 negative_start_time

from typing import List, Optional

from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import DepletionResult, NetRateResult, ReturnResult
from app.utils.numeric import safe_float


class ReturnEvaluator:
    """对每个被跟踪切线事件产出一条切回判断结果（含更新后的 negative_start_time）。"""

    def evaluate(
        self,
        snapshot: CutlineSnapshot,
        net_rates: List[NetRateResult],
        depletions: List[DepletionResult],
    ) -> List[ReturnResult]:
        lead = safe_float(snapshot.config.cutline_lead_minutes)
        window = safe_float(snapshot.config.stability_window_minutes)
        current = snapshot.current_time
        machine_map = {m.equipment_code: m for m in snapshot.machine_statuses}

        results = []
        for event in snapshot.active_cutline_events:
            machine = machine_map.get(event.equipment_code)
            process_from = machine.process_code if machine else None
            net = self._find(net_rates, event.next_product_code, process_from)
            inventory = self._inventory(depletions, event.next_product_code, process_from)

            negative_start = event.negative_start_time
            duration = None
            safety = None
            triggered = False
            net_rate = net.net_rate_per_hour if net else None

            if net is not None and net.net_rate_per_hour < 0:
                if negative_start is None:
                    negative_start = current
                duration = (current - negative_start).total_seconds() / 60
                safety = lead / 60 * abs(net.net_rate_per_hour)
                triggered = (
                    duration > window
                    and inventory is not None
                    and inventory > safety
                )
            else:
                negative_start = None

            results.append(
                ReturnResult(
                    equipment_code=event.equipment_code,
                    product_code=event.next_product_code,
                    original_product_code=event.previous_product_code,
                    buffer_code=net.buffer_code if net else None,
                    process_from=process_from,
                    process_to=net.process_to if net else None,
                    net_rate_per_hour=net_rate,
                    inventory_quantity=inventory,
                    negative_start_time=negative_start,
                    negative_duration_minutes=duration,
                    safety_inventory_quantity=safety,
                    triggered=triggered,
                )
            )
        return results

    def _find(self, net_rates, product_code, process_from) -> Optional[NetRateResult]:
        for net in net_rates:
            if net.product_code == product_code and net.process_from == process_from:
                return net
        return None

    def _inventory(self, depletions, product_code, process_from):
        for depletion in depletions:
            if depletion.product_code == product_code and depletion.process_from == process_from:
                return depletion.inventory_quantity
        return None
```

- [ ] **Step 5: 跑测试确认通过 + 不回归**

Run: `python -m pytest tests/cutline_return_input/test_return_evaluator.py -q && python -m pytest -q`
Expected: 新测试 PASS（3 passed）；全量 57 passed

- [ ] **Step 6: 提交**

```bash
git add examples/cutline_return_input.json app/core/return_judge/__init__.py app/core/return_judge/return_evaluator.py tests/cutline_return_input/__init__.py tests/cutline_return_input/test_return_evaluator.py
git commit -m "新增 ReturnEvaluator 切回判断与状态回吐"
```

---

### Task 8: SilkScreenHandler 丝网处理 + 丝网 fixture

**Files:**
- Modify: `app/schemas/result_schema.py`（新增 `SilkScreenOrderResult`）
- Create: `examples/cutline_silk_screen_input.json`
- Create: `app/core/silk_screen/__init__.py`（空）、`app/core/silk_screen/silk_screen_handler.py`
- Test: `tests/cutline_silk_screen_input/__init__.py`（空）、`tests/cutline_silk_screen_input/test_silk_screen_handler.py`（新建）

丝网工序自动识别为 buffer 链全局终端出口工序；订单进度触发独立预警。

- [ ] **Step 1: 在 `result_schema.py` 末尾追加 `SilkScreenOrderResult`**

```python
class SilkScreenOrderResult(BaseModel):
    """丝网订单进度触发的清台准备预警。"""

    equipment_code: str
    process_code: str
    product_code: Optional[str] = None
    order_code: Optional[str] = None
    warning_type: str = "silk_screen_order"
    remaining_quantity: float
    completion_time: datetime
    preparation_time: datetime
    silk_screen_clear_minutes: float
    triggered: bool
```

- [ ] **Step 2: 新建 fixture `examples/cutline_silk_screen_input.json`**

```json
{
  "current_time": "2026-06-20T10:00:00",
  "config": { "cutline_lead_minutes": 30, "silk_screen_clear_minutes": 30 },
  "product_models": [
    { "product_code": "HG182T", "wafer_size": "182", "shape_code": "R" }
  ],
  "buffer_segments": [
    { "buffer_code": "BUF_ALD_SW", "service_process_codes": ["ALD", "SW"], "max_capacity": 278400 },
    { "buffer_code": "BUF_OX_ALD", "service_process_codes": ["OX", "ALD"], "max_capacity": 160800 }
  ],
  "machine_statuses": [
    { "equipment_code": "sw01", "process_code": "SW", "status": "running", "product_code": "HG182T", "order_code": "O1", "input_rate_per_hour": 6000, "output_rate_per_hour": 6000 }
  ],
  "orders": [
    { "order_code": "O1", "product_code": "HG182T", "total_quantity": 9000, "produced_quantity": 8000 }
  ]
}
```

口径自检：exit={SW, ALD}，upstream(非末位)={ALD, OX}，丝网=SW（不在 upstream）。剩余 = 9000−8000 = 1000；完工 = 10:00 + 1000/6000×60min = 10:10；准备 = 10:10 − 30min = 09:40；当前 10:00 ≥ 09:40 → 触发。

- [ ] **Step 3: 写失败测试**

新建空文件 `tests/cutline_silk_screen_input/__init__.py`，并写 `tests/cutline_silk_screen_input/test_silk_screen_handler.py`：

```python
from datetime import datetime
from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.core.silk_screen.silk_screen_handler import SilkScreenHandler


SILK_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_silk_screen_input.json"


def load_snapshot():
    return MockAdapter().load(SILK_INPUT_PATH)


def test_identifies_terminal_exit_process_as_silk_screen():
    codes = SilkScreenHandler().identify_silk_screen_processes(load_snapshot())
    assert codes == {"SW"}


def test_order_trigger_emits_preparation_warning():
    results = SilkScreenHandler().evaluate_order_triggers(load_snapshot())
    assert len(results) == 1
    result = results[0]
    assert result.equipment_code == "sw01"
    assert result.process_code == "SW"
    assert result.remaining_quantity == 1000
    assert result.completion_time == datetime(2026, 6, 20, 10, 10, 0)
    assert result.preparation_time == datetime(2026, 6, 20, 9, 40, 0)
    assert result.triggered is True
```

- [ ] **Step 4: 跑测试确认失败**

Run: `python -m pytest tests/cutline_silk_screen_input/test_silk_screen_handler.py -q`
Expected: FAIL（`ModuleNotFoundError: app.core.silk_screen.silk_screen_handler`）

- [ ] **Step 5: 实现 — 新建 `app/core/silk_screen/__init__.py`（空）与 `silk_screen_handler.py`**

```python
# 丝网处理：自动识别 buffer 链终端出口工序；按订单进度触发清台准备预警

from datetime import timedelta
from typing import List, Set

from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import SilkScreenOrderResult
from app.utils.numeric import safe_float


class SilkScreenHandler:
    """识别丝网工序并产出订单进度触发的清台准备预警。"""

    def identify_silk_screen_processes(self, snapshot: CutlineSnapshot) -> Set[str]:
        exits = set()
        upstreams = set()
        for segment in snapshot.buffer_segments:
            codes = segment.service_process_codes
            if not codes:
                continue
            exits.add(codes[-1])
            upstreams.update(codes[:-1])
        return {code for code in exits if code not in upstreams}

    def evaluate_order_triggers(self, snapshot: CutlineSnapshot) -> List[SilkScreenOrderResult]:
        silk_codes = self.identify_silk_screen_processes(snapshot)
        clear_minutes = safe_float(snapshot.config.silk_screen_clear_minutes)
        order_map = {order.order_code: order for order in snapshot.orders}
        current = snapshot.current_time

        results = []
        for machine in snapshot.machine_statuses:
            if machine.process_code not in silk_codes:
                continue
            if machine.status != "running":
                continue
            order = order_map.get(machine.order_code)
            if order is None:
                continue
            capacity = safe_float(machine.output_rate_per_hour)
            if capacity <= 0:
                continue
            remaining = safe_float(order.total_quantity) - safe_float(order.produced_quantity)
            if remaining <= 0:
                continue
            completion_time = current + timedelta(minutes=remaining / capacity * 60)
            preparation_time = completion_time - timedelta(minutes=clear_minutes)
            results.append(
                SilkScreenOrderResult(
                    equipment_code=machine.equipment_code,
                    process_code=machine.process_code,
                    product_code=machine.product_code,
                    order_code=machine.order_code,
                    remaining_quantity=remaining,
                    completion_time=completion_time,
                    preparation_time=preparation_time,
                    silk_screen_clear_minutes=clear_minutes,
                    triggered=current >= preparation_time,
                )
            )
        return results
```

- [ ] **Step 6: 跑测试确认通过 + 不回归**

Run: `python -m pytest tests/cutline_silk_screen_input/test_silk_screen_handler.py -q && python -m pytest -q`
Expected: 新测试 PASS（2 passed）；全量 59 passed

- [ ] **Step 7: 提交**

```bash
git add app/schemas/result_schema.py examples/cutline_silk_screen_input.json app/core/silk_screen/__init__.py app/core/silk_screen/silk_screen_handler.py tests/cutline_silk_screen_input/__init__.py tests/cutline_silk_screen_input/test_silk_screen_handler.py
git commit -m "新增 SilkScreenHandler 丝网识别与订单触发"
```

---

### Task 9: CutlinePipeline 扩展接线

**Files:**
- Modify: `app/service/cutline_pipeline.py`（`PipelineResult` 扩字段，`run()` 串联新组件）
- Test: `tests/cutline_overflow_input/test_pipeline_overflow.py`（新建）

`run()` 在原断料链后追加：溢满预警 → 溢满候选 → 断料/溢满逐台选取 → 丝网订单 → 切回。`build_stockout` 传入丝网工序集合。

- [ ] **Step 1: 写失败测试**

新建 `tests/cutline_overflow_input/test_pipeline_overflow.py`：

```python
from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.service.cutline_pipeline import CutlinePipeline


OVERFLOW_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_overflow_input.json"


def test_pipeline_produces_overflow_warning_and_plan():
    snapshot = MockAdapter().load(OVERFLOW_INPUT_PATH)
    result = CutlinePipeline().run(snapshot)

    triggered = [w for w in result.overflow_warnings if w.warning_triggered]
    assert [w.product_code for w in triggered] == ["HG182T"]

    overflow_plans = [p for p in result.plans if p.warning_type == "overflow"]
    assert len(overflow_plans) == 1
    assert overflow_plans[0].selected_machines[0].equipment_code == "zr_t1"
    assert result.manual_interventions == []
    assert result.return_results == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/cutline_overflow_input/test_pipeline_overflow.py -q`
Expected: FAIL（`AttributeError: 'PipelineResult' object has no attribute 'overflow_warnings'`）

- [ ] **Step 3: 实现 — 整体替换 `app/service/cutline_pipeline.py`**

```python
# 算法管道：按序串联净速率→耗尽→断料/溢满预警→候选→逐台选取→丝网→切回

from dataclasses import dataclass, field
from typing import List, Optional

from app.core.candidate_machine.stockout_candidate_finder import StockoutCandidateFinder
from app.core.candidate_machine.overflow_candidate_finder import OverflowCandidateFinder
from app.core.cutline_plan.plan_builder import CutlinePlanBuilder
from app.core.net_rate.net_rate_calculator import NetRateCalculator
from app.core.net_rate.rate_strategy import RateStrategy, RealtimeFirstRateStrategy
from app.core.prediction_time.depletion_time.depletion_time_calculator import (
    DepletionTimeCalculator,
)
from app.core.return_judge.return_evaluator import ReturnEvaluator
from app.core.silk_screen.silk_screen_handler import SilkScreenHandler
from app.core.warning.overflow_warning import OverflowWarningEvaluator
from app.core.warning.stockout_warning import StockoutWarningEvaluator
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.result_schema import (
    CandidateResult,
    DepletionResult,
    ManualInterventionResult,
    NetRateResult,
    OverflowWarningResult,
    PlanResult,
    ReturnResult,
    SilkScreenOrderResult,
    StockoutWarningResult,
)


@dataclass
class PipelineResult:
    net_rates: List[NetRateResult]
    depletions: List[DepletionResult]
    warnings: List[StockoutWarningResult]
    candidates: List[CandidateResult]
    overflow_warnings: List[OverflowWarningResult] = field(default_factory=list)
    plans: List[PlanResult] = field(default_factory=list)
    manual_interventions: List[ManualInterventionResult] = field(default_factory=list)
    silk_orders: List[SilkScreenOrderResult] = field(default_factory=list)
    return_results: List[ReturnResult] = field(default_factory=list)


class CutlinePipeline:
    """轻量编排：构建一次组件，run 时按序流转结果。"""

    def __init__(self, rate_strategy: Optional[RateStrategy] = None):
        strategy = rate_strategy or RealtimeFirstRateStrategy()
        self._net_rate = NetRateCalculator(strategy)
        self._depletion = DepletionTimeCalculator()
        self._stockout = StockoutWarningEvaluator()
        self._candidate = StockoutCandidateFinder(strategy)
        self._overflow = OverflowWarningEvaluator()
        self._overflow_candidate = OverflowCandidateFinder(strategy)
        self._plan_builder = CutlinePlanBuilder()
        self._silk = SilkScreenHandler()
        self._return = ReturnEvaluator()

    def run(self, snapshot: CutlineSnapshot) -> PipelineResult:
        net_rates = self._net_rate.calculate(snapshot)
        depletions = self._depletion.calculate(snapshot, net_rates)

        warnings = self._stockout.evaluate(snapshot, depletions)
        candidates = self._candidate.find(snapshot, warnings)

        overflow_warnings = self._overflow.evaluate(snapshot, net_rates)
        overflow_candidates = self._overflow_candidate.find(
            snapshot, overflow_warnings, net_rates
        )

        silk_codes = self._silk.identify_silk_screen_processes(snapshot)
        stockout_plans, stockout_interventions = self._plan_builder.build_stockout(
            warnings, candidates, net_rates, depletions, silk_codes
        )
        overflow_plans, overflow_interventions = self._plan_builder.build_overflow(
            snapshot, overflow_warnings, overflow_candidates, net_rates
        )

        silk_orders = self._silk.evaluate_order_triggers(snapshot)
        return_results = self._return.evaluate(snapshot, net_rates, depletions)

        return PipelineResult(
            net_rates=net_rates,
            depletions=depletions,
            warnings=warnings,
            candidates=candidates,
            overflow_warnings=overflow_warnings,
            plans=stockout_plans + overflow_plans,
            manual_interventions=stockout_interventions + overflow_interventions,
            silk_orders=silk_orders,
            return_results=return_results,
        )
```

- [ ] **Step 4: 跑测试确认通过 + 不回归**

Run: `python -m pytest tests/cutline_overflow_input/test_pipeline_overflow.py -q && python -m pytest -q`
Expected: 新测试 PASS；全量 60 passed（旧 `test_full_flow.py` 仍绿——旧 service 仍读 `warnings/candidates`）

- [ ] **Step 5: 提交**

```bash
git add app/service/cutline_pipeline.py tests/cutline_overflow_input/test_pipeline_overflow.py
git commit -m "CutlinePipeline 串联溢满/逐台选取/丝网/切回"
```

---

### Task 10: CutlineService 门面映射 + 全链路测试 + 全量回归

**Files:**
- Modify: `app/service/cutline_service.py`（整体替换：映射 plans/溢满预警/丝网/切回/tracked_events）
- Test: `tests/cutline_overflow_input/test_overflow_service_flow.py`（新建）
- Test: `tests/cutline_return_input/test_return_service_flow.py`（新建）
- 既有 `tests/cutline_complex_input/test_full_flow.py` 保持不变（回归）

- [ ] **Step 1: 写失败测试（溢满与切回的服务级全链路）**

新建 `tests/cutline_overflow_input/test_overflow_service_flow.py`：

```python
from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.service.cutline_service import CutlineService


OVERFLOW_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_overflow_input.json"


def evaluate():
    snapshot = MockAdapter().load(OVERFLOW_INPUT_PATH)
    return CutlineService().evaluate(snapshot)


def test_overflow_warning_surfaced_with_overflow_type():
    response = evaluate()
    overflow = [w for w in response.warnings if w.warning_type == "overflow"]
    assert len(overflow) == 1
    assert overflow[0].product_code == "HG182T"
    assert overflow[0].prediction_minutes == 30


def test_overflow_plan_surfaced():
    response = evaluate()
    overflow_plans = [p for p in response.plans if p.warning.warning_type == "overflow"]
    assert len(overflow_plans) == 1
    selected = overflow_plans[0].selected_machines
    assert selected[0].equipment_code == "zr_t1"
    assert selected[0].target_product_code == "HG182R"
```

新建 `tests/cutline_return_input/test_return_service_flow.py`：

```python
from datetime import datetime
from pathlib import Path

from app.adapters.mock_adapter import MockAdapter
from app.service.cutline_service import CutlineService


RETURN_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_return_input.json"


def evaluate():
    snapshot = MockAdapter().load(RETURN_INPUT_PATH)
    return CutlineService().evaluate(snapshot)


def test_triggered_return_surfaced_as_suggestion():
    response = evaluate()
    assert [s.equipment_code for s in response.return_suggestions] == ["zr03"]
    suggestion = response.return_suggestions[0]
    assert suggestion.product_code == "HG182T"
    assert suggestion.original_product_code == "HG182R"


def test_all_tracked_events_returned_with_updated_state():
    response = evaluate()
    by_equipment = {e.equipment_code: e for e in response.tracked_events}
    assert set(by_equipment) == {"zr03", "zr_r"}
    assert by_equipment["zr03"].negative_start_time == datetime(2026, 6, 20, 9, 35, 0)
    assert by_equipment["zr_r"].negative_start_time is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/cutline_overflow_input/test_overflow_service_flow.py tests/cutline_return_input/test_return_service_flow.py -q`
Expected: FAIL（旧 service 不产出 overflow 预警/plans/return_suggestions/tracked_events）

- [ ] **Step 3: 实现 — 整体替换 `app/service/cutline_service.py`**

```python
# 切线评估门面：调用管道，把内部结果对象映射为对外 CutlineEvaluateResponse

from typing import List, Optional

from app.schemas.common_schema import CutlineEvent
from app.schemas.request_schema import CutlineSnapshot
from app.schemas.response_schema import (
    CutlineEvaluateResponse,
    CutlinePlan,
    ManualIntervention,
    ReturnSuggestion,
    SelectedMachine,
    WarningResult,
)
from app.schemas.result_schema import (
    ManualInterventionResult,
    OverflowWarningResult,
    PlanResult,
    ReturnResult,
    SilkScreenOrderResult,
    StockoutWarningResult,
)
from app.service.cutline_pipeline import CutlinePipeline


class CutlineService:
    """对外统一入口：evaluate(snapshot) -> CutlineEvaluateResponse。"""

    def __init__(self, pipeline: Optional[CutlinePipeline] = None):
        self._pipeline = pipeline or CutlinePipeline()

    def evaluate(self, snapshot: CutlineSnapshot) -> CutlineEvaluateResponse:
        result = self._pipeline.run(snapshot)

        warnings_out: List[WarningResult] = []
        for warning in result.warnings:
            if warning.warning_triggered:
                warnings_out.append(self._stockout_warning(snapshot, warning))
        for overflow in result.overflow_warnings:
            if overflow.warning_triggered:
                warnings_out.append(self._overflow_warning(snapshot, overflow))
        for order in result.silk_orders:
            if order.triggered:
                warnings_out.append(self._silk_warning(order))

        plans_out = [self._plan(snapshot, plan) for plan in result.plans]
        interventions_out = [
            self._intervention(snapshot, item) for item in result.manual_interventions
        ]
        return_out = [
            self._return_suggestion(snapshot, item)
            for item in result.return_results
            if item.triggered
        ]
        tracked_out = [self._tracked_event(snapshot, item) for item in result.return_results]

        return CutlineEvaluateResponse(
            success=True,
            message="",
            warnings=warnings_out,
            plans=plans_out,
            manual_interventions=interventions_out,
            return_suggestions=return_out,
            tracked_events=tracked_out,
        )

    def _stockout_warning(self, snapshot, warning: StockoutWarningResult) -> WarningResult:
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

    def _overflow_warning(self, snapshot, warning: OverflowWarningResult) -> WarningResult:
        return WarningResult(
            warning_time=snapshot.current_time,
            warning_type=warning.warning_type,
            buffer_code=warning.buffer_code,
            upstream_process_code=warning.process_from,
            downstream_process_code=warning.process_to,
            product_code=warning.product_code,
            inventory_quantity=warning.segment_inventory,
            net_rate=warning.net_rate_per_hour,
            prediction_minutes=warning.overflow_minutes,
            cutline_lead_minutes=warning.cutline_lead_minutes,
        )

    def _silk_warning(self, order: SilkScreenOrderResult) -> WarningResult:
        return WarningResult(
            warning_time=order.preparation_time,
            warning_type=order.warning_type,
            buffer_code="",
            upstream_process_code=order.process_code,
            downstream_process_code=order.process_code,
            product_code=order.product_code or "",
            prediction_minutes=None,
            message="silk_screen_clear_preparation",
        )

    def _plan(self, snapshot, plan: PlanResult) -> CutlinePlan:
        warning = WarningResult(
            warning_time=snapshot.current_time,
            warning_type=plan.warning_type,
            buffer_code=plan.buffer_code,
            upstream_process_code=plan.process_from,
            downstream_process_code=plan.process_to,
            product_code=plan.product_code,
        )
        return CutlinePlan(
            warning=warning,
            selected_machines=[self._selected(m) for m in plan.selected_machines],
            total_contribution_capacity=plan.total_contribution_capacity,
            remaining_capacity_gap=plan.remaining_capacity_gap,
            requires_silk_screen_clear=plan.requires_silk_screen_clear,
            silk_screen_clear_minutes=plan.silk_screen_clear_minutes,
        )

    def _intervention(self, snapshot, item: ManualInterventionResult) -> ManualIntervention:
        warning = WarningResult(
            warning_time=snapshot.current_time,
            warning_type=item.warning_type,
            buffer_code=item.buffer_code,
            upstream_process_code=item.process_from,
            downstream_process_code=item.process_to,
            product_code=item.product_code,
        )
        return ManualIntervention(
            warning=warning,
            reason=item.reason,
            required_capacity=item.required_capacity,
            candidate_machines=[self._selected(m) for m in item.candidates],
        )

    def _return_suggestion(self, snapshot, item: ReturnResult) -> ReturnSuggestion:
        return ReturnSuggestion(
            suggestion_time=snapshot.current_time,
            equipment_code=item.equipment_code,
            product_code=item.product_code,
            original_product_code=item.original_product_code,
            buffer_code=item.buffer_code,
            upstream_process_code=item.process_from,
            downstream_process_code=item.process_to,
            negative_start_time=item.negative_start_time,
            negative_duration_minutes=item.negative_duration_minutes,
            inventory_quantity=item.inventory_quantity,
            safety_inventory_quantity=item.safety_inventory_quantity,
            net_rate=item.net_rate_per_hour,
        )

    def _tracked_event(self, snapshot, item: ReturnResult) -> CutlineEvent:
        return CutlineEvent(
            equipment_code=item.equipment_code,
            cut_time=snapshot.current_time,
            previous_product_code=item.original_product_code or "",
            next_product_code=item.product_code,
            negative_start_time=item.negative_start_time,
        )

    def _selected(self, machine) -> SelectedMachine:
        return SelectedMachine(
            equipment_code=machine.equipment_code,
            current_product_code=machine.current_product_code,
            target_product_code=machine.target_product_code,
            wafer_size=machine.wafer_size,
            shape_code=machine.shape_code,
            process_code=machine.process_code,
            utilization_rate=machine.utilization_rate,
            idle_rate=machine.idle_rate,
            contribution_capacity=machine.contribution_capacity_per_hour,
        )
```

注：`WarningResult.downstream_process_code` 必填 `str`，examples 区间均有 `process_to`，安全。丝网订单预警无区间，`buffer_code` 置空串、上下游工序填丝网工序码。

- [ ] **Step 4: 跑新测试确认通过**

Run: `python -m pytest tests/cutline_overflow_input/test_overflow_service_flow.py tests/cutline_return_input/test_return_service_flow.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 全量回归**

Run: `python -m pytest -q`
Expected: 末行 `64 passed`，无 ERROR；旧 `test_full_flow.py`（complex 无产能→plans=[]、无溢满、无切回）保持绿

- [ ] **Step 6: 提交**

```bash
git add app/service/cutline_service.py tests/cutline_overflow_input/test_overflow_service_flow.py tests/cutline_return_input/test_return_service_flow.py
git commit -m "CutlineService 映射方案/溢满/丝网/切回与事件回吐"
```

---

## 验收标准（全部满足才算完成）

- [ ] `python -m pytest -q` 全绿（约 64 passed），无 ERROR/skip。
- [ ] 复杂场景断料基线数值不变：净速率 6000/4000/3600/2500；耗尽 10/15/20/120；触发 {HG210R,HG182N,HG182T}。
- [ ] 3.3：sample 场景 HG182T 产出 plan，选中 zr03、`total_contribution_capacity=8000`、`remaining_capacity_gap=-4800`；借出校验对 HG182R 原区间通过（125min>30）。
- [ ] 溢满：overflow fixture 触发 overflow 预警（30min）并产出切走方案（zr_t1→HG182R）。
- [ ] 切回：return fixture 中 zr03 触发（持续25min>20、库存5000>安全3200），zr_r 清零；`tracked_events` 回吐两事件最新 `negative_start_time`。
- [ ] 丝网：识别终端出口工序 `SW`；订单触发产出 `silk_screen_order` 预警。
- [ ] 算法组件、pipeline、service 内 0 处裸 dict 取值、0 处本地 `safe_float`。

## 后续（计划二，本计划不含）

混料算法B（`MixTraceService` + `mix_trace_api` 端点 + `cutline_api` 端点）见独立计划。
