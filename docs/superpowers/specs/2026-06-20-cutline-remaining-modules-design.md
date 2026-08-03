# 切线剩余算法模块实现设计（3.3 逐台选取 / 溢满 / 切回 / 丝网 / 混料）

> 本文是**实现设计**，与《算法设计v2》互补：v2 规定算法行为（领先实现的规格书），本文规定这批模块如何接入现有代码架构、数据怎么流、对外契约怎么映射、怎么测。
>
> 范围：实现问题清单中"已设计、未实现"的 5 个模块。一份 spec，落地拆两份计划：**切线主链**（3.3 + 溢满 + 切回 + 丝网，挂进 `CutlinePipeline`）与 **混料算法B**（独立服务/端点）。
>
> 关键约束（沿用既有架构与记忆）：组件吃 Pydantic 对象、吐结果对象；裸 dict 只在适配器之前；门面做内部结果→对外响应的映射；字段名以"算法/示例JSON"为准、snake_case；净速率口径保留实时速率优先（`RealtimeFirstRateStrategy`）。复杂场景断料基线 41 测试必须保持绿。

---

## 一、架构与接线

### 1.1 新增组件

| 组件 | 文件 | 职责 |
|---|---|---|
| `CutlinePlanBuilder` | `app/core/cutline_plan/plan_builder.py` | 3.3 断料逐台选取 + 借出影响校验 → `PlanResult`；未补足 → `ManualInterventionResult` |
| `OverflowWarningEvaluator` | `app/core/warning/overflow_warning.py` | 段级溢满预测 → `OverflowWarningResult` |
| `OverflowCandidateFinder` | `app/core/candidate_machine/overflow_candidate_finder.py` | 溢满"切走方向"候选池（3.2 溢满分支） |
| `ReturnEvaluator` | `app/core/return_judge/return_evaluator.py` | 3.4 切回判断 + `negative_start_time` 回吐 |
| `SilkScreenHandler` | `app/core/silk_screen/silk_screen_handler.py` | 3.5 丝网水位/订单双触发标注 |
| `MixTraceService` | `app/service/mix_trace_service.py` | 算法B：单切线事件 → 混料通知 |

### 1.2 管道扩展

`CutlinePipeline.run()` 按序产出：

```
净速率 → 耗尽 → (断料预警 + 溢满预警) → (断料候选 + 溢满候选) → 逐台选取(plans + 人工介入) → 切回
```

`PipelineResult` 增字段：`overflow_warnings`、`plans`、`manual_interventions`、`return_results`（保留既有 `net_rates / depletions / warnings / candidates`）。

### 1.3 内部结果对象（`app/schemas/result_schema.py` 新增）

沿用"内部结果对象 → 门面映射对外"模式，新增：

- `OverflowWarningResult`：段级溢满预警（buffer_code、product_code、process_from/to、warning_type="overflow"、warning_triggered、reason、segment_inventory、segment_capacity、net_rate_per_hour、overflow_minutes、cutline_lead_minutes）。
- `PlanResult`：切线方案（buffer_code、product_code、process_from/to、warning_type、selected_machines: List[CandidateMachine]、total_contribution_capacity、remaining_capacity_gap、requires_silk_screen_clear、silk_screen_clear_minutes）。
- `ManualInterventionResult`：未补足（同区间键 + warning_type、required_capacity、candidates）。
- `ReturnResult`：切回逐事件结果（equipment_code、product_code、original_product_code、buffer_code、process_from/to、net_rate_per_hour、inventory_quantity、negative_start_time、negative_duration_minutes、safety_inventory_quantity、triggered: bool）。

> `CandidateMachine` 复用现有定义（已带 `contribution_capacity_per_hour`）。逐台选取需要"空闲度/利用率"，在 `CandidateMachine` 增可选字段 `idle_rate` / `utilization_rate`（默认 None），由 finder 填充。

---

## 二、3.3 断料逐台选取（`CutlinePlanBuilder`）

输入：snapshot + 已触发 `StockoutWarningResult` + 对应 `CandidateResult` 候选池 + 全部 `NetRateResult`（供借出校验复算）。

```
产能缺口 = warning.net_rate_per_hour          # 断料时即 下游吞入 − 上游产出，已算，不另算
候选池按空闲度降序：
    空闲度 = 1 − 当前产出速率 / 静态产能           # 静态产能 = capacity_records[M, M当前型号].actual_capacity_per_hour
    （静态产能缺失或为 0 时空闲度记为 None，排在最后）

WHILE 缺口 > 0 且 候选池非空:
    取出（并从池中移除）空闲度最高的 M     # 每轮必移除一台，保证循环终止
    贡献 = capacity_records[M, 预警型号X].actual_capacity_per_hour
    IF 贡献 缺失或 ≤ 0:
        跳过 M（无可计产能贡献）
        continue
    借出影响校验（模拟移除 M 对其"原区间"的冲击）：
        原区间 = [M.process_code → 下游, M当前型号]
        new_上游产出 = 原上游产出 − M.output_rate
        new_净速率   = 原下游吞入 − new_上游产出
        new_耗尽分钟 = 原区间库存 / new_净速率 × 60   (new_净速率 > 0 时)
        IF new_净速率 > 0 且 new_耗尽分钟 ≤ cutline_lead_minutes:
            跳过 M（借出会害原线断料）
        ELSE:
            选中 M；缺口 −= 贡献

缺口 ≤ 0  → PlanResult(selected_machines=已选, total_contribution_capacity=Σ贡献, remaining_capacity_gap=缺口)
缺口 > 0  → ManualInterventionResult(required_capacity=缺口, candidates=候选池快照)
```

要点：
- "原区间库存"与"原上游产出/下游吞入"来自现有 `NetRateResult` / `DepletionResult`（按区间键查），M 的 output 来自注入的 `RateStrategy`。校验是纯模拟重算，不引新数据。
- 借出校验若 M 当前型号无对应区间（M 当前型号无在产下游），视为借出无害，直接选中。
- 切换后可贡献产能 = `capacity_records[M, 预警型号X].actual_capacity_per_hour`；缺该记录或 ≤0 时跳过该台（不计入方案，与"无可计产能贡献"一致），避免缺口无法收敛。

---

## 三、溢满预警（`OverflowWarningEvaluator` + `OverflowCandidateFinder`）

### 3.1 段级溢满预测

```
区间定位：每个 BufferSegment S 的 service_process_codes 决定段内工序顺序，相邻对 = 区间。
对每个 (S, 型号X区间):
    IF 区间净速率 < 0 (积累):
        Σ段库存 = Σ inventory.inventory_quantity WHERE inventory.buffer_code == S.buffer_code   # 物理池共用，跨型号跨区间求和
        溢满预测分钟 = (S.max_capacity − Σ段库存) / |区间净速率| × 60
        IF 溢满预测分钟 ≤ cutline_lead_minutes:
            → OverflowWarningResult(warning_triggered=True, reason="overflow_time_within_lead_time")
        ELSE:
            → warning_triggered=False, reason="overflow_time_beyond_lead_time"
    净速率 ≥ 0 → 不产出溢满预警（该区间走断料分支）
```

同段多个区间触发时，按溢满预测分钟最短优先（与断料一致的全局紧迫度排序）。

### 3.2 切走候选池（3.2 溢满分支）

```
候选唯一条件（全部满足）：
  条件1：机台所属工序 = 预警区间工序i（产出侧）
  条件2：机台当前生产型号 = 预警型号X
  条件3：机台当前状态 = 运行
  条件4：存在至少一个目标型号Y：同硅片尺寸 AND 同形状代码，
         且 Y 的目标区间[工序i→工序i+1, Y] 当前存在产能缺口（断料向净速率 > 0，切过去有意义）
候选池为空 → "无处可切"，人工介入。
```

### 3.3 切走逐台选取

```
产能过剩量 = |区间净速率|
候选池按产能利用率降序：利用率 = 当前产出 / 静态产能
WHILE 溢满风险未消解 且 候选池非空:
    取利用率最高的 M
    对每个候选 Y 执行切入影响校验：
        模拟 M 切到 Y 后，重算 Y 目标区间溢满预测
        IF 溢满预测 ≤ lead → 换下一个 Y；所有 Y 不通过 → 跳过 M
    选中 M（切走到 Y），重算原区间净速率
    IF 原区间净速率 ≥ 0 或 溢满预测 > lead → 风险消解，停止
候选池耗尽仍未消解 → 人工介入（required_capacity = 仍需切走量）
```

溢满方案同样产出 `PlanResult`（warning_type="overflow"，selected_machines 的 target_product_code = 选定的 Y）。

---

## 四、切回判断（`ReturnEvaluator`，无状态回吐）

### 4.1 契约改动

- `CutlineEvent` 增字段：`negative_start_time: Optional[datetime] = None`（后端持久化、每周期通过 `snapshot.active_cutline_events` 回吐）。
- `CutlineEvaluateResponse` 增字段：`tracked_events: List[CutlineEvent]`（回吐**全部**被跟踪事件的最新 `negative_start_time`，供后端续存）。

### 4.2 逻辑

```
遍历 snapshot.active_cutline_events 的每个事件 ev:
    定位受影响区间 = [ev 机台所属工序 → 下游, ev.next_product_code]
    取该区间当前 净速率 r、当前库存 inv
    IF r < 0:
        若 ev.negative_start_time 为空 → 置 current_time
        持续时长 = current_time − ev.negative_start_time   (分钟)
        安全水位 = cutline_lead_minutes / 60 × |r|
        triggered = (持续时长 > stability_window_minutes) AND (inv > 安全水位)
    ELSE (r ≥ 0):
        ev.negative_start_time = None
        triggered = False
    产出 ReturnResult(... 含更新后的 negative_start_time、negative_duration_minutes、safety、triggered)
    并把更新后的 ev 收集进 tracked_events 回吐
```

每个被跟踪事件都产出一条 `ReturnResult`；门面只把 `triggered=True` 的映射进 `response.return_suggestions`，全部事件的最新状态经 `response.tracked_events` 回吐。

---

## 五、丝网工序特殊处理（`SilkScreenHandler`）

### 5.1 丝网工序识别（自动、不硬编码）

```
exit_processes = { 每个 BufferSegment 的 service_process_codes 末位 }
upstream_processes = { 所有 service_process_codes 中非末位的工序 }
丝网工序 = exit_processes 中不属于 upstream_processes 的那个（buffer 链全局终端出口工序）
```

唯一性按设计假设成立；若识别到 0 个或多个，`SilkScreenHandler` 不报错、跳过丝网特殊处理（退化为普通预警），并在日志/message 标注。

### 5.2 两类触发

```
情况1 水位触发（同 3.1）：预警区间工序i == 丝网工序时，
       其方案 PlanResult.requires_silk_screen_clear = True，
       silk_screen_clear_minutes = config.silk_screen_clear_minutes，
       切线准备时刻 = 预警时刻（立即准备清台）。
情况2 订单触发（不依赖 Buffer 水位）：对丝网在产机台，
       剩余量   = order.total_quantity − produced_quantity         # order 按机台 order_code 关联
       完工时刻 = current_time + 剩余量 / 机台当前产能(片/h) × 60(min)
       准备时刻 = 完工时刻 − silk_screen_clear_minutes
       IF current_time ≥ 准备时刻 → 产出预警 warning_type="silk_screen_order"
                                    （reason="silk_screen_clear_preparation"）
```

---

## 六、混料追溯（算法B，`MixTraceService`，独立服务）

`MixTraceService.trace(MixTraceRequest) → MixTraceResponse`，与切线管道完全解耦。

```
ev = request.cutline_event = (equipment, cut_time, prev=model_A, next=model_B)
cap = capacity_records[equipment, model_A]
残留消耗(min) = config.max_feed_basket_count × config.basket_capacity / cap.actual_capacity_per_hour × 60
AGV送料(min)  = config.agv_delivery_minutes        # 缺省/0 时计 0，并在 message 标注 "AGV 时长待确认"
工艺时长(min) = cap.process_time_minutes
T_mix_start  = cut_time + 残留消耗 + AGV送料 + 工艺时长

m = config.mix_basket_count
估算总片数 = m × config.basket_capacity
型号组成 = [
    {product_code: model_A, sequence_no: 1, estimated_quantity: (m/2)×basket_capacity},
    {product_code: model_B, sequence_no: 2, estimated_quantity: (m/2)×basket_capacity},
]
status = "arrived" if request.current_time ≥ T_mix_start else "pending"
→ MixTraceNotification
```

边界：`cap` 缺失（无该机台该型号产能记录）→ 残留消耗与工艺时长无法算，返回 `success=False` + message 说明；不抛异常。

---

## 七、对外输出映射（`CutlineService` 门面扩展）

| 内部结果 | 对外 | 备注 |
|---|---|---|
| 断料 triggered `StockoutWarningResult` | `response.warnings`（warning_type="stockout"） | 现状已做 |
| 溢满 triggered `OverflowWarningResult` | `response.warnings`（warning_type="overflow"） | inventory_quantity 用段库存，prediction_minutes=overflow_minutes |
| 丝网订单触发 | `response.warnings`（warning_type="silk_screen_order"） | |
| `PlanResult` | `response.plans`（`CutlinePlan`，含 requires_silk_screen_clear） | 替换现状的 plans=[] |
| `ManualInterventionResult` | `response.manual_interventions` | 现状仅候选展示，改为带 required_capacity |
| `ReturnResult` triggered | `response.return_suggestions` | |
| 全部跟踪事件最新状态 | `response.tracked_events` | 切回状态回吐 |

混料：`mix_trace_api.py` 加 POST 端点接 `MixTraceService`；`cutline_api.py` 把现有 `CutlineService` 接成 POST 端点。

---

## 八、测试策略与 fixture

现有 examples 全是断料场景（净速率>0）。需新造 fixture 放 `examples/`：

| fixture | 覆盖模块 | 关键构造 |
|---|---|---|
| `cutline_overflow_input.json` | 溢满预警 + 切走选取 | 上游产出 > 下游吞入（净速率<0），段库存逼近 max_capacity |
| `cutline_return_input.json` | 切回判断 | 带 `active_cutline_events`（含/不含 negative_start_time 两种），净速率<0、库存>安全水位 |
| `cutline_silk_screen_input.json` | 丝网订单触发 | 丝网在产机台 + order 剩余量使准备时刻已到 |
| `mix_trace_input.json` | 混料算法B | 单切线事件 + capacity_records 带 process_time_minutes |

每模块严格 TDD：先写读取 fixture 的失败测试（断言对象 API + 数值），再实现。3.3 逐台选取复用现有 `cutline_complex_input.json`（HG182T 已有候选池，可断言选中 zr 候选并补足缺口）。

### 验收标准

- `python -m pytest -q` 全绿，无 ERROR/skip；现有 41 测试数值不变。
- 3.3：复杂场景 HG182T 产出含 selected_machines、缺口补足；无候选的 HG182N 仍走人工介入。
- 溢满：fixture 触发 overflow 预警并产出切走方案或人工介入。
- 切回：fixture 中满足三条件的事件 triggered=True，未满足的回吐更新后的 negative_start_time。
- 丝网：识别出终端出口工序；水位方案标 requires_silk_screen_clear；订单触发产出 silk_screen_order 预警。
- 混料：T_mix_start 数值与 v2 第八章示例一致（zr03 例：08:30 + 9 + 5 + 40 = 09:24）。
- 算法核心组件、pipeline、service、mix_trace 内 0 处裸 dict 取值、0 处本地 safe_float。

---

## 九、计划拆分

- **计划一 切线主链**：内部结果对象 → 3.3 逐台选取 → 溢满预警 → 溢满候选+切走 → 切回 → 丝网 → pipeline/service 接线 → 全链路测试。
- **计划二 混料算法B**：`MixTraceService` → `mix_trace_api` 端点 →（顺带）`cutline_api` 端点 → 测试。

契约改动（`CutlineEvent.negative_start_time`、`CutlineEvaluateResponse.tracked_events`、`CandidateMachine.idle_rate/utilization_rate`）在计划一最前的 schema 任务统一落地。
