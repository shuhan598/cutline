# 切线算法后端响应与持久化状态接口

## 1. 正式调用链

需要 Pending 跨轮闭环时使用 `POST /cutline/evaluate`：

```text
CutlineAlgorithmRequest
  -> SnapshotAdapter.to_algorithm_snapshot
  -> CutlinePipeline.evaluate_algorithm
  -> AlgorithmResponseMapper.to_evaluate_response
  -> CutlineEvaluateResponse
       = CutlineAlgorithmResponse 原有字段
       + persistence_state
```

兼容路由 `POST /stub/algo/run` 仍以 `CutlineAlgorithmResponse` 作为响应模型，字段集合
保持不变，不输出 `persistence_state`。两个路由都不得依赖内部
`AlgorithmEvaluateResult` 的净速率、候选排序或模拟诊断字段。

## 2. 基础业务响应

```json
{
  "calculation_time": "2026-07-17T08:00:00+08:00",
  "stockout_warnings": [],
  "overflow_warnings": [],
  "cutline_decisions": [],
  "return_recommendations": [],
  "silk_screen_results": [],
  "mixing_trace_records": [],
  "new_active_cutline_events": [],
  "updated_active_cutline_events": [],
  "closed_active_cutline_event_ids": [],
  "errors": []
}
```

响应分为三类：

1. 甲方业务结果：`stockout_warnings`、`overflow_warnings`、
   `cutline_decisions`、`return_recommendations`、`silk_screen_results`、
   `mixing_trace_records`。
2. 后端算法状态：`new_active_cutline_events`、
   `updated_active_cutline_events`、`closed_active_cutline_event_ids`。
3. 后端错误记录：`errors`。

正式响应不再包含 `return_results` 和 `mixing_trace_failures`。这两类完整
诊断结果仍可保留在算法内部。

### 2.1 增强评估响应

`CutlineEvaluateResponse` 平铺保留上面全部基础字段，仅增加一个状态隔离字段：

```json
{
  "calculation_time": "2026-07-17T08:00:00+08:00",
  "stockout_warnings": [],
  "overflow_warnings": [],
  "cutline_decisions": [],
  "return_recommendations": [],
  "silk_screen_results": [],
  "mixing_trace_records": [],
  "new_active_cutline_events": [],
  "updated_active_cutline_events": [],
  "closed_active_cutline_event_ids": [],
  "errors": [],
  "persistence_state": {
    "pending_cutline_plans": [],
    "active_cutline_events": [],
    "expired_pending_plan_ids": [],
    "completed_pending_plan_ids": [],
    "return_suggested_event_ids": [],
    "mixed_cutline_event_ids": [],
    "new_mixing_trace_records": []
  }
}
```

这里没有重复嵌套的 `business_response` 对象：基础业务字段仍位于顶层，
`persistence_state` 只承载后端保存和下一轮回传的完整状态。基础
`CutlineAlgorithmResponse` 仍可独立严格校验增强响应的业务字段投影。

## 3. 预警

### 3.1 断料预警

```json
{
  "warning_id": "stockout:2026-07-17T08:00:00+08:00:310110302:ORD-S2-001",
  "warning_type": "stockout",
  "warning_time": "2026-07-17T08:00:00+08:00",
  "buffer_code": "310110302",
  "order_code": "ORD-S2-001",
  "wafer_size": "182",
  "wafer_spec": "N",
  "workshop_code": "S2",
  "upstream_process_code": "制绒",
  "downstream_process_code": "碱抛",
  "current_quantity": 100.0,
  "upstream_output_rate": 200.0,
  "downstream_input_rate": 600.0,
  "net_consumption_rate": 400.0,
  "depletion_minutes": 15.0,
  "stockout_warning_lead_minutes": 30.0
}
```

`warning_id` 由 Mapper 确定性生成，用于关联对应的切线决策，不依赖数组下标。

### 3.2 溢满预警

```json
{
  "warning_id": "overflow:2026-07-17T08:00:00+08:00:310110302",
  "warning_type": "overflow",
  "warning_time": "2026-07-17T08:00:00+08:00",
  "buffer_code": "310110302",
  "workshop_code": "S2",
  "total_inventory": 900.0,
  "max_capacity": 1000.0,
  "remaining_capacity": 100.0,
  "buffer_growth_rate": 300.0,
  "overflow_minutes": 20.0,
  "overflow_warning_lead_minutes": 30.0
}
```

对外只展示物理 Buffer 总体风险。订单增长明细、订单库存、订单净速率和
订单增长速率不返回；内部仍保留这些数据供溢满候选机台选择使用。

## 4. 切线决策

每条决策通过 `warning_id` 关联预警。正式方案是算法建议，不代表现场已经切线；
自动方案同轮只在 `persistence_state` 创建 Pending，不创建 Active 或混料。正式方案和人工介入使用两个独立模型，
最终 JSON 只出现实际存在的分支。

自动方案：

```json
{
  "warning_id": "stockout:2026-07-17T08:00:00+08:00:310110302:ORD-S2-001",
  "plan": {}
}
```

人工介入：

```json
{
  "warning_id": "stockout:2026-07-17T08:00:00+08:00:310110302:ORD-S2-001",
  "manual_intervention": {
    "reason": "no_candidate_machine"
  }
}
```

自动方案中不存在 `manual_intervention` 键；人工介入中不存在 `plan` 键。
人工介入对象只返回稳定原因代码 `reason`，例如 `no_candidate_machine`、
`insufficient_capacity`、`source_order_stockout_risk`、
`target_buffer_overflow_risk`、`no_valid_target_order`；中文文案由展示层映射。

### 4.1 断料正式方案

字段为：

- `plan_id`、`warning_type`、`calculation_time`
- `workshop_code`、`buffer_code`、`order_code`
- `wafer_size`、`wafer_spec`
- `upstream_process_code`、`downstream_process_code`
- `initial_capacity_gap`、`total_contribution_capacity`、
  `remaining_capacity_gap`
- `selected_machines`

### 4.2 溢满正式方案

字段为：

- `plan_id`、`warning_type`、`calculation_time`
- `workshop_code`、`buffer_code`、`source_order_code`
- `source_wafer_size`、`source_wafer_spec`
- `upstream_process_code`、`downstream_process_code`
- `initial_growth_rate`、`total_reduced_capacity`、`remaining_growth_rate`、
  `updated_overflow_minutes`
- `selected_machines`

对外正式方案不返回 `risk_resolved` 和 `manual_intervention_required`。

### 4.3 选中机台

断料和溢满均保留：

- `machine_code`
- `source_order_code`、`target_order_code`
- `source_buffer_code`、`target_buffer_code`
- `process_code`、`workshop_code`
- `wafer_size`、`source_wafer_spec`、`target_wafer_spec`

断料机台只增加 `contribution_capacity`；溢满机台只增加 `reduced_capacity`。
不返回利用率、空闲度、切线前后净速率、断料时间和溢满时间等模拟诊断字段。

## 5. 切回建议

```json
{
  "event_id": "CUT-202607170800-EA004",
  "machine_code": "EA004",
  "source_order_code": "ORD-S2-002",
  "target_order_code": "ORD-S2-001",
  "return_recommended_time": "2026-07-17T08:26:00+08:00"
}
```

`return_recommendations` 是给甲方展示的业务结果，不用于后端持续计时。
`return_recommended_time` 是算法首次满足全部切回条件的计算时间。
同轮事件 ID 会写入累计 `persistence_state.return_suggested_event_ids`，完整 Active 状态
改为 `return_recommended`；后续原样回传后不会重复输出建议。现场实际完成切回的
`returned_time` 由后端或现场系统记录，算法不推测，也不创建 PendingReturnPlan。

## 6. 活动事件的业务投影与完整状态

基础业务响应 `new_active_cutline_events` 继续使用原有 12 字段：

```json
{
  "event_id": "CUT-202607170800-EA004",
  "machine_code": "EA004",
  "source_order_code": "ORD-S2-002",
  "target_order_code": "ORD-S2-001",
  "workshop_code": "S2",
  "target_buffer_code": "310110302",
  "upstream_process_code": "制绒",
  "downstream_process_code": "碱抛",
  "target_wafer_size": "182",
  "target_wafer_spec": "N",
  "cutline_start_time": "2026-07-17T08:03:00+08:00",
  "negative_start_time": null
}
```

`negative_start_time` 必须显式存在并允许为 `null`。该业务投影不增加生命周期字段，
因此不能单独承担完整跨轮持久化。

`persistence_state.active_cutline_events` 返回完整对象；除上述公开字段外，还保留：

- `plan_id`、`warning_id`
- `status`：`active`、`return_recommended`、`returned` 或 `cancelled`
- `source_buffer_code`、`source_wafer_size`、`source_wafer_spec`
- `contribution_capacity`
- `warning_type`、`process_code`
- `warning_buffer_code`、`warning_upstream_process_code`、
  `warning_downstream_process_code`
- `is_recommended_candidate`

后端应保存并回传这个完整对象。`is_recommended_candidate=true` 表示方案推荐机台，
`false` 表示客户在相同车间、工序、精确订单映射、时间窗口和切换方向约束内实际选择的
非候选机台；非候选确认不附加候选影响筛选或全局优化。

`cutline_start_time` 取窗口内证明绑定变化的 AGV `createtime`，其语义是“本轮首次观察
到绑定变化的记录时间”，不是精确物理换型时刻，也不是方案 `calculation_time`。

## 7. 更新与关闭事件

更新事件只包含：

```json
{
  "event_id": "CUT-202607170800-EA004",
  "negative_start_time": null
}
```

`negative_start_time: null` 表示净速率已恢复非负，后端必须清空原计时。
响应不会全局排除 `null`，因此该字段不会丢失。

关闭事件只返回 ID：

```json
{
  "closed_active_cutline_event_ids": [
    "CUT-202607170800-EA004"
  ]
}
```

同一基础业务响应中，`return_recommendations[].event_id` 与
`closed_active_cutline_event_ids[]` 仍一一对应。增强响应还会在完整 Active 上保存
`status=return_recommended` 并累计事件 ID 水位；满足切回条件的事件不会再出现在
`updated_active_cutline_events`。

## 8. Pending 与 Active 生命周期

### 8.1 Pending 确认

首轮自动方案在 `persistence_state.pending_cutline_plans` 创建 `PENDING`。后端回传
Pending、完整 AGV 历史和 Active 后，算法仅认领
`created_at < observed_at <= expire_at` 且不晚于本轮快照的逐台订单变化：

- 断料：`baseline_order_code != target_order_code` 且
  `current_order_code == target_order_code`。
- 溢满：机台从监控源订单切到保存的合法其他订单；目标区间仅是持久化上下文，
  不用当轮净速率否认已经发生的真实切换，缺失或歧义会明确报错。
- 推荐机台标记 `is_recommended_candidate=true`；合法非候选机台标记 `false`。
- 部分执行为 `PARTIALLY_CONFIRMED`；全部执行为 `CONFIRMED`；窗口结束后未完成部分为
  `EXPIRED`。边界记录先确认，再处理到期。

同一 Pending 不重复确认已确认机台；同一物理变化若可被多个 Pending 认领会明确报错，
不会按推荐优先或输入顺序猜测。终态 Pending 重放安全，不重新创建 Active。

### 8.2 切回跟踪

事件未产生切回建议时继续观察：

1. `net_consumption_rate >= 0`：计时重置为 `null`；只有原值非空时返回更新。
2. `net_consumption_rate < 0` 且计时为空：以本轮 `calculation_time` 开始计时并
   返回更新。
3. 连续负净速率时间小于或等于稳定窗口：保留计时，不建议切回。
4. 稳定时间满足但库存小于或等于安全库存：继续观察。

仅当以下三项同时满足时关闭：

1. `net_consumption_rate < 0`；
2. `current_time - negative_start_time > stability_window_minutes`；
3. `current_quantity > safe_inventory_quantity`。

其中：

```text
safe_inventory_quantity
  = abs(net_consumption_rate)
  × stockout_warning_lead_minutes
  ÷ 60
```

稳定窗口和库存阈值均使用严格大于。ReturnEvaluator 三个条件保持不变，但只处理
状态为 `active` 且事件 ID 尚未进入 `return_suggested_event_ids` 的真实 Active。
算法给出建议后不等待现场真实切回；后端保存完整状态和累计水位，后续不会重复建议。

如果目标 Buffer、订单、净速率无法关联，或 ReturnEvaluator 出现局部异常，
算法只返回 `errors`，不会建议切回、不会关闭事件；后端保留原事件并在下一轮
继续提交。

## 9. 丝网清台

每条 `silk_screen_results` 只包含：

- `workshop_code`
- `current_order_code`
- `machine_codes`
- `calculation_time`
- `silk_screen_clear_minutes`
- `remaining_production_hours`
- `prepare_clearance`
- `reason`
- `message`

不返回工序、产品、总量/完成量/剩余量、实时产能、预计完工时间、准备时间和
`next_order_code`。异常丝网机台仍不参与计算；`prepare_clearance` 的判断公式未变。

## 10. 混料追踪与错误

成功的 `mixing_trace_records` 保持现有字段，但触发入口改为确认后的完整 Active：

- 首轮业务方案和 Pending 不创建混料。
- Active 必须处于 `active` 或 `return_recommended`，且 `plan_id`、`warning_id`、
  `process_code`、`is_recommended_candidate` 完整。
- 同一事件 ID 不在 `mixed_cutline_event_ids` 时才计算。
- `mix_start_time` 从 Active 的 `cutline_start_time` 起算，不额外增加计划执行延迟；
  残余、AGV、工艺、篮数、S2 P/R 和组成公式不变。
- 成功记录同时出现在业务 `mixing_trace_records` 和
  `persistence_state.new_mixing_trace_records`，并累计混料水位。
- 失败不推进水位，数据修复后可重试；同一机台后续的新事件仍可再次生成。

单机混料失败转换为：

```json
{
  "stage": "mixing_trace",
  "machine_code": "EA004",
  "reason": "process_duration_not_found",
  "message": "process duration for EA004/PROD-S2-N-SUPPORT was not found"
}
```

每个失败只进入 `errors` 一次；不会再出现在已删除的
`mixing_trace_failures`。其它 Active 的成功记录和状态继续返回。

## 11. 后端处理顺序

1. 通过 `/cutline/evaluate` 调用并展示或转发顶层业务结果。
2. 原子保存整个 `persistence_state`，不要根据公开事件 ID 反向解析 Pending。
3. 下一轮把 `pending_cutline_plans`、`active_cutline_events`、
   `return_suggested_event_ids`、`mixed_cutline_event_ids` 映射回请求同名字段。
4. 完整保存终态和两个累计水位；不要因业务 `closed_active_cutline_event_ids` 丢失
   `return_recommended` 状态。
5. 独立保存 `errors`，不得因局部错误丢弃其它成功结果；混料失败保留事件并允许重试。

## 12. 可执行样例

请求场景位于 `examples/scenarios/`。基础响应样例为
`examples/cutline_algorithm_response_sample.json`；首轮、确认轮和切回轮增强响应为
`examples/cutline_evaluate_*_response.json`。场景调试输出位于 `debug_outputs/`，包括：

- `v3_stockout_auto_response.json`
- `v3_stockout_manual_no_candidate_response.json`
- `v3_overflow_warning_response.json`
- `v3_return_tracking_started_response.json`
- `v3_return_recommended_response.json`
- `v3_silk_prepare_response.json`
- `v3_mixing_failure_response.json`

所有文件均由 `python examples/generate_v3_scenarios.py` 通过真实 Loader、Service 和
Mapper 链生成。`v3_stockout_auto` 展示首轮 Pending 且无 Active/混料；
`v3_return_round_2` 展示确认轮创建 Active、单次混料和水位推进；
`v3_return_recommended` 展示已混料事件首次产生切回建议。


