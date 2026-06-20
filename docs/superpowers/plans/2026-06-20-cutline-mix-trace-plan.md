# 混料追溯算法 B 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `MixTraceService`，对一次切线事件计算混料起始时刻 `T_mix_start` 并产出一条混料通知（型号组成、估算片数、生命周期状态）。

**Architecture:** 轻量「组件 + 门面」。`MixStartCalculator`（纯算法，吃 `MixTraceRequest` 吐 `MixTraceNotification`，缺产能数据吐 `None`）；`MixTraceService` 门面把通知包装为 `MixTraceResponse`（缺数据→`success=False`+空）。schema 零改动，不造内部结果对象、不造 adapter（测试用 `MixTraceRequest.model_validate` 读 JSON）。

**Tech Stack:** Python 3.13、Pydantic 2.11、pytest。

**基线：** 起步 `python -m pytest -q` 为 64 passed。本计划新增测试，既有测试不得回归。规格依据 `docs/superpowers/specs/2026-06-20-cutline-mix-trace-design.md`。

---

## 任务依赖顺序

1. Task 1 — `MixStartCalculator` 纯算法 + 混料 fixture
2. Task 2 — `MixTraceService` 门面 + 服务级测试 + 全量回归

---

### Task 1: MixStartCalculator 纯算法 + 混料 fixture

**Files:**
- Create: `examples/cutline_mix_trace_input.json`
- Create: `app/core/mix_trace/__init__.py`（空）
- Create: `app/core/mix_trace/mix_start_calculator.py`
- Create: `tests/cutline_mix_trace_input/__init__.py`（空）
- Create: `tests/cutline_mix_trace_input/test_mix_start_calculator.py`

混料起始时刻 = `T_cut + 残留消耗时长 + AGV送料时长 + 工艺时长`；残留 = `max_feed_basket_count × basket_capacity / 实际产能 × 60`(分钟)。缺产能记录或产能≤0 → 返回 `None`。

- [ ] **Step 1: 新建 fixture `examples/cutline_mix_trace_input.json`**

```json
{
  "current_time": "2026-06-20T10:00:00",
  "cutline_event": {
    "equipment_code": "pk03",
    "cut_time": "2026-06-20T10:00:00",
    "previous_product_code": "HG210R",
    "next_product_code": "HG182T"
  },
  "capacity_records": [
    { "equipment_code": "pk03", "product_code": "HG210R", "actual_capacity_per_hour": 9600, "process_time_minutes": 60 }
  ],
  "config": { "agv_delivery_minutes": 5, "mix_basket_count": 2, "basket_capacity": 120, "max_feed_basket_count": 10 }
}
```

口径自检：残留 = 10×120/9600×60 = 7.5min；T_mix_start = 10:00 + 7.5 + 5 + 60 = 11:12:30；估算总片数 = 2×120 = 240；A/B 各 120；current_time 10:00 < 11:12:30 → status=pending。

- [ ] **Step 2: 写失败测试**

新建空文件 `tests/cutline_mix_trace_input/__init__.py`，并写 `tests/cutline_mix_trace_input/test_mix_start_calculator.py`：

```python
import json
from datetime import datetime
from pathlib import Path

from app.core.mix_trace.mix_start_calculator import MixStartCalculator
from app.schemas.request_schema import MixTraceRequest


MIX_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_mix_trace_input.json"


def load_request() -> MixTraceRequest:
    with MIX_INPUT_PATH.open(encoding="utf-8") as file:
        return MixTraceRequest.model_validate(json.load(file))


def test_pk03_mix_start_time_and_composition():
    notification = MixStartCalculator().calculate(load_request())
    assert notification is not None
    assert notification.source_equipment_code == "pk03"
    assert notification.cut_time == datetime(2026, 6, 20, 10, 0, 0)
    assert notification.previous_product_code == "HG210R"
    assert notification.next_product_code == "HG182T"
    assert notification.mix_start_time == datetime(2026, 6, 20, 11, 12, 30)
    assert notification.mix_basket_count == 2
    assert notification.estimated_total_quantity == 240
    assert notification.product_compositions == [
        {"product_code": "HG210R", "sequence_no": 1, "estimated_quantity": 120},
        {"product_code": "HG182T", "sequence_no": 2, "estimated_quantity": 120},
    ]


def test_status_pending_before_mix_start():
    notification = MixStartCalculator().calculate(load_request())
    assert notification.status == "pending"


def test_status_arrived_when_current_time_at_or_after_mix_start():
    request = load_request().model_copy(update={"current_time": datetime(2026, 6, 20, 11, 12, 30)})
    notification = MixStartCalculator().calculate(request)
    assert notification.status == "arrived"


def test_returns_none_when_capacity_record_missing():
    request = load_request().model_copy(update={"capacity_records": []})
    assert MixStartCalculator().calculate(request) is None


def test_returns_none_when_capacity_not_positive():
    request = load_request()
    zeroed = request.capacity_records[0].model_copy(update={"actual_capacity_per_hour": 0})
    request = request.model_copy(update={"capacity_records": [zeroed]})
    assert MixStartCalculator().calculate(request) is None
```

- [ ] **Step 3: 跑测试确认失败**

Run: `python -m pytest tests/cutline_mix_trace_input/test_mix_start_calculator.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.core.mix_trace'`）

- [ ] **Step 4: 实现 — 新建 `app/core/mix_trace/__init__.py`（空）与 `mix_start_calculator.py`**

```python
# 混料起始时刻计算：残留消耗 + AGV 送料 + 工艺时长 推算 T_mix_start，产出混料通知

from datetime import timedelta
from typing import List, Optional

from app.schemas.common_schema import MachineCapacityRecord
from app.schemas.request_schema import MixTraceRequest
from app.schemas.response_schema import MixTraceNotification
from app.utils.numeric import safe_float


class MixStartCalculator:
    """对一次切线事件计算混料起始时刻与型号组成；缺产能数据返回 None。"""

    def calculate(self, request: MixTraceRequest) -> Optional[MixTraceNotification]:
        event = request.cutline_event
        config = request.config
        record = self._capacity_record(
            request.capacity_records, event.equipment_code, event.previous_product_code
        )
        if record is None:
            return None
        capacity = safe_float(record.actual_capacity_per_hour)
        if capacity <= 0:
            return None

        basket_capacity = safe_float(config.basket_capacity)
        residual_minutes = (
            safe_float(config.max_feed_basket_count) * basket_capacity / capacity * 60
        )
        mix_start_time = event.cut_time + timedelta(
            minutes=residual_minutes
            + safe_float(config.agv_delivery_minutes)
            + safe_float(record.process_time_minutes)
        )

        basket_count = config.mix_basket_count
        half_quantity = basket_count / 2 * basket_capacity
        product_compositions = [
            {
                "product_code": event.previous_product_code,
                "sequence_no": 1,
                "estimated_quantity": half_quantity,
            },
            {
                "product_code": event.next_product_code,
                "sequence_no": 2,
                "estimated_quantity": half_quantity,
            },
        ]
        status = "arrived" if request.current_time >= mix_start_time else "pending"

        return MixTraceNotification(
            source_equipment_code=event.equipment_code,
            cut_time=event.cut_time,
            previous_product_code=event.previous_product_code,
            next_product_code=event.next_product_code,
            mix_start_time=mix_start_time,
            mix_basket_count=basket_count,
            estimated_total_quantity=basket_count * basket_capacity,
            product_compositions=product_compositions,
            status=status,
        )

    def _capacity_record(
        self,
        records: List[MachineCapacityRecord],
        equipment_code: str,
        product_code: str,
    ) -> Optional[MachineCapacityRecord]:
        for record in records:
            if record.equipment_code == equipment_code and record.product_code == product_code:
                return record
        return None
```

- [ ] **Step 5: 跑测试确认通过 + 不回归**

Run: `python -m pytest tests/cutline_mix_trace_input/test_mix_start_calculator.py -q && python -m pytest -q`
Expected: 新测试 PASS（5 passed）；全量从 64 增至 69 passed

- [ ] **Step 6: 提交**

```bash
git add examples/cutline_mix_trace_input.json app/core/mix_trace/__init__.py app/core/mix_trace/mix_start_calculator.py tests/cutline_mix_trace_input/__init__.py tests/cutline_mix_trace_input/test_mix_start_calculator.py
git commit -m "新增 MixStartCalculator 混料起始时刻计算"
```

提交信息为简洁中文单行，不加任何尾注（无 Co-Authored-By / Generated with）。

---

### Task 2: MixTraceService 门面 + 服务级测试 + 全量回归

**Files:**
- Modify（整体替换单行占位）: `app/service/mix_trace_service.py`
- Create: `tests/cutline_mix_trace_input/test_mix_trace_service.py`

门面调 `MixStartCalculator`：`None` → `success=False` + message（含机台编码与前型号）+ 空；否则 → `success=True` + `[notification]`。

- [ ] **Step 1: 写失败测试**

新建 `tests/cutline_mix_trace_input/test_mix_trace_service.py`：

```python
import json
from datetime import datetime
from pathlib import Path

from app.schemas.request_schema import MixTraceRequest
from app.service.mix_trace_service import MixTraceService


MIX_INPUT_PATH = Path(__file__).resolve().parents[2] / "examples" / "cutline_mix_trace_input.json"


def load_request() -> MixTraceRequest:
    with MIX_INPUT_PATH.open(encoding="utf-8") as file:
        return MixTraceRequest.model_validate(json.load(file))


def test_trace_success_returns_one_notification():
    response = MixTraceService().trace(load_request())
    assert response.success is True
    assert response.message == ""
    assert len(response.notifications) == 1
    notification = response.notifications[0]
    assert notification.source_equipment_code == "pk03"
    assert notification.mix_start_time == datetime(2026, 6, 20, 11, 12, 30)
    assert notification.status == "pending"


def test_trace_missing_capacity_returns_failure():
    request = load_request().model_copy(update={"capacity_records": []})
    response = MixTraceService().trace(request)
    assert response.success is False
    assert response.notifications == []
    assert "pk03" in response.message


def test_trace_status_arrived_after_mix_start():
    request = load_request().model_copy(update={"current_time": datetime(2026, 6, 20, 11, 30, 0)})
    response = MixTraceService().trace(request)
    assert response.success is True
    assert response.notifications[0].status == "arrived"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/cutline_mix_trace_input/test_mix_trace_service.py -q`
Expected: FAIL（`AttributeError: module 'app.service.mix_trace_service' has no attribute 'MixTraceService'` 或 `ImportError`）

- [ ] **Step 3: 实现 — 整体替换 `app/service/mix_trace_service.py`**

```python
# 混料追溯门面：调用 MixStartCalculator，把通知包装为 MixTraceResponse

from typing import Optional

from app.core.mix_trace.mix_start_calculator import MixStartCalculator
from app.schemas.request_schema import MixTraceRequest
from app.schemas.response_schema import MixTraceResponse


class MixTraceService:
    """对外统一入口：trace(request) -> MixTraceResponse。"""

    def __init__(self, calculator: Optional[MixStartCalculator] = None):
        self._calculator = calculator or MixStartCalculator()

    def trace(self, request: MixTraceRequest) -> MixTraceResponse:
        notification = self._calculator.calculate(request)
        if notification is None:
            event = request.cutline_event
            return MixTraceResponse(
                success=False,
                message=(
                    f"缺少机台 {event.equipment_code} / 型号 "
                    f"{event.previous_product_code} 的静态产能或工艺时长"
                ),
                notifications=[],
            )
        return MixTraceResponse(
            success=True,
            message="",
            notifications=[notification],
        )
```

- [ ] **Step 4: 跑测试确认通过 + 不回归**

Run: `python -m pytest tests/cutline_mix_trace_input/test_mix_trace_service.py -q && python -m pytest -q`
Expected: 新测试 PASS（3 passed）；全量从 69 增至 72 passed，无 ERROR

- [ ] **Step 5: 提交**

```bash
git add app/service/mix_trace_service.py tests/cutline_mix_trace_input/test_mix_trace_service.py
git commit -m "新增 MixTraceService 门面与混料通知映射"
```

提交信息为简洁中文单行，不加任何尾注。

---

## 验收标准（全部满足才算完成）

- [ ] `python -m pytest -q` 全绿（72 passed），无 ERROR/skip。
- [ ] pk03 例：`mix_start_time == 2026-06-20 11:12:30`、`estimated_total_quantity == 240`、组成 HG210R/HG182T 各 120、`mix_basket_count == 2`。
- [ ] 生命周期：`current_time < T_mix_start → status=="pending"`；`current_time >= T_mix_start → status=="arrived"`。
- [ ] 缺数据：无匹配产能记录或产能=0 → `calculate` 返回 `None`，门面 `success=False`、`notifications==[]`、message 含机台编码。
- [ ] 切线既有测试不回归；混料算法层 0 处裸 dict、0 处本地 `safe_float`；schema 未改动。

## 后续（不在本计划）

- HTTP API/入口层（`mix_trace_api`/`cutline_api`/`main`/`run`）。
- 已知小遗留 P7（库存去重口径）、P9（丝网前 R/P 视为同形状）及整体评审 3 项。
