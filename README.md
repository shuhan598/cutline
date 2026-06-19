# 光伏车间切线算法服务

## 项目当前阶段说明

本项目当前处于算法测试阶段，重点是把切线算法的核心计算链路跑通，并已完成一次「数据封装 + 设计模式」重构（2026-06-18）。

- 目前不直接对接甲方真实接口，使用 `examples` 目录下的 JSON 假数据测试。
- 数据流：原始 dict/JSON → 适配器 → `CutlineSnapshot`（Pydantic 对象）→ 算法管道 → 对外响应对象。**裸 dict 只存在于适配器之前；过了适配器全程是对象，算法层不再直接读 dict。**
- 当前已跑通：净消耗速率计算、断料耗尽时间预测、断料预警判断、候选机台筛选，并由门面 `CutlineService` 统一对外。

## 架构与设计模式

| 模式 | 落点 | 作用 |
| --- | --- | --- |
| 适配器 Adapter | `app/adapters/snapshot_adapter.py`、`app/adapters/mock_adapter.py` | dict/JSON、examples 文件 → `CutlineSnapshot`；换数据源不动算法 |
| 策略 Strategy | `app/core/net_rate/rate_strategy.py`（`RealtimeFirstRateStrategy`） | 速率取数三级链（实时速率 → 近30min量×2 → 静态产能 → 0）；调口径不动主算法 |
| 管道 Pipeline | `app/service/cutline_pipeline.py`（`CutlinePipeline`） | 按序编排 净速率 → 耗尽 → 预警 → 候选 四步，持有同一 snapshot 上下文 |
| 门面 Facade | `app/service/cutline_service.py`（`CutlineService`） | 对外唯一入口 `evaluate(snapshot) -> CutlineEvaluateResponse` |

数据对象分三层：

- 输入领域对象：`app/schemas/request_schema.py` 的 `CutlineSnapshot`（基础对象在 `app/schemas/common_schema.py`）。
- 算法结果对象：`app/schemas/result_schema.py`（`NetRateResult` / `DepletionResult` / `StockoutWarningResult` / `CandidateResult` / `CandidateMachine`）。
- 对外响应对象：`app/schemas/response_schema.py` 的 `CutlineEvaluateResponse`。

公共工具：`safe_float` 统一在 `app/utils/numeric.py`（全项目唯一实现）。

## 当前已实现的算法模块

### 1. 区间净消耗速率计算

对应文件：`app/core/net_rate/net_rate_calculator.py`（`NetRateCalculator`）

计算逻辑：

- 以 `buffer_code + product_code + process_from + process_to` 为一个计算单元。
- 统计上游工序 `process_from` 中，当前产品型号对应的 `running` 机台产出速率。
- 统计下游工序 `process_to` 中，当前产品型号对应的 `running` 机台吞入速率。
- 速率取数由构造注入的 `RealtimeFirstRateStrategy` 提供（实时速率优先，缺失时退到近30min量×2，再退到静态产能）。
- 净消耗速率计算公式：

```text
net_rate_per_hour = downstream_input_per_hour - upstream_output_per_hour
```

含义：

- `net_rate_per_hour > 0`：Buffer 库存正在减少，存在断料风险。
- `net_rate_per_hour = 0`：Buffer 库存基本平衡。
- `net_rate_per_hour < 0`：Buffer 库存正在增加，后续可用于溢满风险判断（溢满预警尚未实现）。

### 2. 断料耗尽时间计算

对应文件：`app/core/prediction_time/depletion_time/depletion_time_calculator.py`（`DepletionTimeCalculator`）

计算逻辑：

- 根据当前 Buffer 区间库存和净消耗速率，计算库存还能支撑多久。
- 计算公式：

```text
depletion_minutes = inventory_quantity / net_rate_per_hour * 60
```

说明：

- 只有 `net_rate_per_hour > 0` 时才计算耗尽时间（状态 `decreasing`）。
- `net_rate_per_hour == 0` 状态为 `stable`、`< 0` 为 `increasing`，此时 `depletion_minutes` 为 `None`。
- `depletion_minutes` 越小，断料风险越紧急。

### 3. 断料预警判断

对应文件：`app/core/warning/stockout_warning.py`（`StockoutWarningEvaluator`）

判断逻辑：

- 从 `snapshot.config.cutline_lead_minutes` 读取切线提前量（对象属性，不再读 dict）。
- 当前规则：

```text
depletion_minutes <= cutline_lead_minutes 时触发断料预警
```

说明：

- 当前假数据中 `cutline_lead_minutes` 通常设置为 `30`。
- 耗尽时间 ≤ 30 分钟则 `warning_triggered = True`，否则不触发。

### 4. 候选机台筛选

对应文件：`app/core/candidate_machine/candidate_machine_finder.py`（`CandidateMachineFinder`）

筛选逻辑：

- 只对已触发的 `stockout` 预警进行候选机台筛选。
- 候选机台当前筛选条件：

1. 机台状态 `status == "running"`。
2. 机台所在工序 `process_code == 断料预警的 process_from`。
3. 机台当前生产型号 `product_code` 不等于目标断料型号。
4. 当前机台型号与目标型号 `wafer_size` 相同。
5. 当前机台型号与目标型号 `shape_code` 相同。

说明：

- 多台满足条件的机台会全部进入 `candidates`，并携带 `contribution_capacity_per_hour` 等产能字段（来自 `capacity_records`，缺记录时为 `None`）。
- 速率经由与净速率相同的 `RateStrategy` 计算，保证两处口径一致。
- 当前只生成候选机台池（静态资格过滤），**尚未实现**借出影响校验、切入量计算、候选机台打分、切回逻辑。

### 5. 多个断料预警的处理顺序

处理逻辑：

- 同时出现多个断料预警时，按 `depletion_minutes` 从小到大排序，越快断料优先级越高。
- 当前为全局排序，不按 Buffer 分组。
- 不新增 `priority_rank` 字段，输出顺序本身即优先级顺序。

## 当前算法主流程

推荐经由门面调用：

```text
examples JSON
↓ MockAdapter().load(path)
CutlineSnapshot（Pydantic 对象）
↓ CutlineService().evaluate(snapshot)
  内部 CutlinePipeline.run(snapshot)：
    NetRateCalculator.calculate(snapshot)
    → DepletionTimeCalculator.calculate(snapshot, net_rates)
    → StockoutWarningEvaluator.evaluate(snapshot, depletions)
    → CandidateMachineFinder.find(snapshot, warnings)
↓
CutlineEvaluateResponse
  ├─ warnings：断料预警（已触发）
  └─ manual_interventions：候选机台（供操作员查看）
```

> 本期门面只输出 `warnings` 与 `manual_interventions`；`plans`（切线方案）与 `return_suggestions`（切回建议）尚未实现，留空不编造。

## 测试数据与测试目录对应关系

| 假数据文件 | 对应测试目录 | 说明 |
| --- | --- | --- |
| `examples/cutline_sample_input.json` | `tests/cutline_sample_input/` | 基础样例：单 Buffer、少量机台、基础断料预警 |
| `examples/cutline_complex_input.json` | `tests/cutline_complex_input/` | 复杂场景：多 Buffer、多型号、多预警、无候选/多候选、全局紧急排序、全链路 |

重构新增的分层测试：

| 测试目录 | 覆盖范围 |
| --- | --- |
| `tests/schemas/` | 算法结果对象 schema |
| `tests/utils/` | `safe_float` 数值工具 |
| `tests/adapters/` | examples → `CutlineSnapshot` 适配器 |
| `tests/core/` | 速率策略三级取数 |

## 如何运行测试

```bash
python -m pytest -q                          # 全部（当前 41 passed）
python -m pytest tests/cutline_sample_input -q
python -m pytest tests/cutline_complex_input -q
```

## 如何查看计算结果

经由门面拿对外响应：

```python
from app.adapters.mock_adapter import MockAdapter
from app.service.cutline_service import CutlineService

snapshot = MockAdapter().load("examples/cutline_complex_input.json")
response = CutlineService().evaluate(snapshot)
print(response.model_dump())
```

想逐步查看四步中间结果（净速率 / 耗尽 / 预警 / 候选），用管道：

```python
from app.adapters.mock_adapter import MockAdapter
from app.service.cutline_pipeline import CutlinePipeline

snapshot = MockAdapter().load("examples/cutline_complex_input.json")
result = CutlinePipeline().run(snapshot)
print(result.net_rates)
print(result.depletions)
print(result.warnings)
print(result.candidates)
```
