# 切线算法服务：设计模式与数据封装重构设计

- 日期：2026-06-18
- 范围：含数据适配入口层的完整骨架（输入适配 → 数据封装 → 算法管道 → 输出封装）
- 取向：务实落地、真正解耦，不为模式而堆模式（甲方/生产交付要求）

## 1. 背景与目标

甲方/生产交付要求本项目"使用设计模式 + 对数据进行封装"。结合代码现状，这有真实抓手：

- **数据封装**：把各层之间传递的裸 `dict` 换成对象，字段不再靠字符串 key + 兜底访问。
- **设计模式**：把过程式函数链改造成职责清晰、可替换、可扩展的组件。

目标是让"数据来源、数据结构、算法逻辑、对外契约"四者解耦，换数据源/调口径/加预警类型时改动局部化。

## 2. 现状问题

1. `app/schemas/` 已有完整的 Pydantic 领域模型（`common_schema` / `request_schema` / `response_schema`），但**核心算法完全没用**。
2. 四个算法模块（`net_rate` / `prediction_time` / `warning` / `candidate_machine`）全是过程式函数，直接吃裸 `dict`、吐裸 `dict`，靠 `_get_value(source, field)`（dict 与对象都能取）兜底访问字段。
3. `_get_value` 在 4 个文件、`safe_float` 在 3 个文件**重复定义**。
4. `cutline_service.py`（主流程编排）、`snapshot_adapter.py`、`mock_adapter.py`、`api/cutline_api.py`、`main.py` 目前**只有注释，是空壳**。
5. 现有单元测试直接断言返回 dict 的字段（如 `result["net_rate_per_hour"]`）。

## 3. 整体架构与数据流

```
 数据来源              适配器层(Adapter)          数据封装层(Pydantic)
 examples JSON  ─────▶ MockAdapter         ┐
 甲方 dict/JSON ─────▶ SnapshotAdapter      ├──▶ CutlineSnapshot(已有 common_schema)
                                            ┘            │ 对象
                                                         ▼
   门面 Facade                        算法管道 Pipeline(轻量编排)
 CutlineService.evaluate(snapshot) ─▶ ① 净速率 →(速率策略Strategy)
                                      ② 耗尽时间 → ③ 断料预警 → ④ 候选机台
        │ 组装/映射                                    │ 每步输出结果对象
        ▼                                              ▼
 CutlineEvaluateResponse(已有 response_schema) ◀── NetRate/Depletion/Warning/Candidate Result
```

关键原则：**裸 dict 只存在于"适配器之前"。过了适配器，全程是 Pydantic 对象。** 算法层与管道层一行都不碰 dict。

## 4. 设计模式落点（均对应真实可变点，非硬套）

| 模式 | 落点 | 真实理由 |
|---|---|---|
| 适配器 Adapter | `snapshot_adapter`（甲方 dict/JSON→快照）、`mock_adapter`（examples→快照） | 测试用假数据、将来切甲方真实接口，换数据源不动算法。 |
| 策略 Strategy | 速率取数三级链（实时速率→30min×2→产能兜底） | 代码里已存在的取数逻辑，显式化为可替换策略，调口径不动主算法。 |
| 管道 Pipeline | 净速率→耗尽→预警→候选 四步链（轻量编排） | 现在每步重复接收 `data` 并各自捞 `machine_statuses`，管道统一持有上下文按序流转。 |
| 门面 Facade | `cutline_service` 统一对外入口 | 调用方只跟 `evaluate(snapshot)` 打交道，四步细节封在管道内。 |
| 工厂 Factory（扩展点，本期不做） | 预警类型→处理器（stockout / 未来 overflow） | 当前仅 stockout，先留扩展点，等 overflow 真要做再引入。 |

## 5. 数据封装设计

三类对象各司其职（标准的"内部模型 vs 对外契约"分离）：

| 对象类别 | 文件 | 角色 | 状态 |
|---|---|---|---|
| 输入领域对象 | `schemas/common_schema.py` | 适配器产出、算法消费 | 已有，复用 |
| 算法结果对象 | `schemas/result_schema.py` | 四步算法各自的中间产物 | **新增** |
| 对外响应对象 | `schemas/response_schema.py` | 门面组装后返回 | 已有，复用 |

### 5.1 新增 `result_schema.py` 字段契约（严格沿用现有 dict 字段名，全 snake_case）

- `NetRateResult`：`buffer_code / product_code / process_from / process_to / upstream_output_per_hour / downstream_input_per_hour / net_rate_per_hour / upstream_equipment_codes / downstream_equipment_codes`
- `DepletionResult`：`buffer_code / product_code / process_from / process_to / inventory_quantity / net_rate_per_hour / depletion_minutes / depletion_status`
- `StockoutWarningResult`：`buffer_code / product_code / process_from / process_to / warning_type / warning_triggered / reason / inventory_quantity / net_rate_per_hour / depletion_minutes / depletion_status / cutline_lead_minutes`
- `CandidateResult`：`buffer_code / product_code / process_from / process_to / candidate_found / candidate_status / reason / candidates: list[CandidateMachine]`
- `CandidateMachine`：`equipment_code / equipment_name / process_code / current_product_code / target_product_code / wafer_size / shape_code / current_output_rate_per_hour / contribution_capacity_per_hour / reason`

### 5.2 约束

1. **字段契约不变**：结果对象字段名 100% 沿用现有 dict 名字，封装只"换容器"不改字段。
2. **内部 result 与对外 response 分两层**：对外字段（`upstream_process_code`/`prediction_minutes`/`net_rate`）与算法内部字段（`process_from`/`depletion_minutes`/`net_rate_per_hour`）故意不同，由**门面负责映射**，避免对外契约与内部计算耦死。

## 6. 算法组件接口（函数 → 组件，吃对象吐结果对象）

```
NetRateCalculator.calculate(snapshot, rate_strategy)    -> list[NetRateResult]
DepletionTimeCalculator.calculate(snapshot, net_rates)  -> list[DepletionResult]
StockoutWarningEvaluator.evaluate(snapshot, depletions) -> list[StockoutWarningResult]
StockoutCandidateFinder.find(snapshot, warnings)         -> list[CandidateResult]
```

各组件只认自己的输入/输出对象，内部不再重复从 `data` 捞数据。`StockoutCandidateFinder` 内部保留"按 `depletion_minutes` 升序处理多个预警"的全局排序逻辑。

## 7. 速率策略 Strategy

文件：`core/net_rate/rate_strategy.py`

```
RateStrategy(抽象)
  ├─ input_rate(machine: MachineRuntimeStatus)  -> float
  └─ output_rate(machine: MachineRuntimeStatus) -> float
RealtimeFirstRateStrategy(默认)  # 实时速率 → 近30min量×2 → 静态产能兜底 → 0.0
```

`NetRateCalculator` 默认注入 `RealtimeFirstRateStrategy`；换口径只需传入别的策略实现，主算法不动。口径保持"实时速率优先"。

## 8. 管道 Pipeline（轻量编排）

`CutlinePipeline` 内部按序调用四个组件、传递上一步结果，持有同一个 `CutlineSnapshot` 作为共享上下文。不引入统一 `Step` 接口抽象（YAGNI）。

```
pipeline.run(snapshot) -> 累积四步结果（net_rates / depletions / warnings / candidates）
```

## 9. 门面 Facade（输出范围）

`CutlineService.evaluate(snapshot: CutlineSnapshot) -> CutlineEvaluateResponse`

- 内部：调用 `CutlinePipeline` → 拿四步结果 → 映射成对外响应。
- **本期输出范围**：`warnings`（断料预警）+ 候选机台（放入 `manual_interventions` 供操作员查看）。
- `plans` 的打分/切入量、`return_suggestions` 切回逻辑 README 明确尚未实现，**留成门面扩展点，不编造数据**。

## 10. 公共工具与错误处理

- `safe_float` 统一收敛到 `app/utils/`（删除 3 处重复定义）。
- `_get_value` 对象化后**删除**（不再需要 dict/对象兼容兜底）。
- 输入校验交给 **Pydantic**（适配器构造 `CutlineSnapshot` 时自动校验类型/必填/`ge≥0`）。
- 脏数据（None、非数字速率）由 `safe_float` 兜底。
- 算法内部信任已校验对象，不再到处防御性取值。

## 11. 测试策略

- 现有断言由 `result["net_rate_per_hour"]` 改为属性断言 `result.net_rate_per_hour`（体现已对象化）。
- 现有用例的**期望数值与场景不变**（如 complex 输入四段净速率 6000/4000/3600/2500），仅改取值方式。
- 新增：`MockAdapter` 加载 examples → `CutlineSnapshot` 的适配器测试；`RealtimeFirstRateStrategy` 三级取数的策略测试。
- 全链路测试改为经由 `CutlineService.evaluate` 走通。

## 12. 非目标（YAGNI / 本期不做）

- 切线方案打分、切入量计算、借出影响校验、切回逻辑。
- overflow（溢满）预警与对应的 Factory 分发（仅留扩展点）。
- HTTP 接口落地（`api/cutline_api.py`、`main.py` 本期仍可不接通，聚焦算法骨架）。

## 13. 涉及文件清单

新增：
- `app/schemas/result_schema.py`
- `app/core/net_rate/rate_strategy.py`

重构：
- `app/core/net_rate/net_rate_calculator.py`（→ `NetRateCalculator`，删 `_get_value`/`safe_float`）
- `app/core/prediction_time/depletion_time/depletion_time_calculator.py`（→ `DepletionTimeCalculator`）
- `app/core/warning/stockout_warning.py`（→ `StockoutWarningEvaluator`）
- `app/core/candidate_machine/stockout_candidate_finder.py`（→ `StockoutCandidateFinder`）
- `app/core/net_rate/rate_utils.py`（取数逻辑迁入 `rate_strategy.py`、`safe_float` 迁入 `app/utils/`、`_get_value` 删除；文件清空后删除）
- `app/adapters/snapshot_adapter.py`（实现 dict/JSON → `CutlineSnapshot`）
- `app/adapters/mock_adapter.py`（实现 examples → `CutlineSnapshot`）
- `app/service/cutline_service.py`（实现门面 + 管道编排）
- `app/utils/`（收敛 `safe_float`）
- `tests/`（断言改属性访问；新增 adapter / strategy 测试）

新增管道载体 `app/service/cutline_pipeline.py`：
- `CutlinePipeline`
