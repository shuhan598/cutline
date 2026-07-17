# 切线算法后端请求与响应接口

## 1. 正式调用链

当前仓库没有 HTTP 路由。后端调用入口及唯一正式数据链为：

```text
CutlineAlgorithmRequest
  -> SnapshotAdapter.to_algorithm_snapshot
  -> CutlinePipeline.evaluate_algorithm
  -> AlgorithmResponseMapper.to_response
  -> CutlineAlgorithmResponse
```

后端只应接收 `CutlineAlgorithmResponse`，不得依赖内部
`AlgorithmEvaluateResult` 的净速率、候选排序或模拟诊断字段。

## 2. 顶层响应

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

每条决策通过 `warning_id` 关联预警。正式方案和人工介入使用两个独立模型，
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
现场实际完成切回的 `returned_time` 由后端或现场系统记录，算法不推测。

## 6. 活动事件请求与新事件响应

请求 `active_cutline_events` 与响应 `new_active_cutline_events` 使用同一最小字段集：

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
  "cutline_start_time": "2026-07-17T08:00:00+08:00",
  "negative_start_time": null
}
```

后端不再回传 `plan_id`、源 Buffer、源硅片尺寸/规格、贡献产能、预警类型和
`status`。`negative_start_time` 必须显式存在并允许为 `null`。

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

同一响应中，`return_recommendations[].event_id` 与
`closed_active_cutline_event_ids[]` 必须一一对应。满足切回条件的事件不会再
出现在 `updated_active_cutline_events`。

## 8. 事件生命周期

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

稳定窗口和库存阈值均使用严格大于。算法给出建议后立即结束跟踪，不等待现场
真实切回。后端收到关闭 ID 后必须移除事件，下一轮不得再次提交。

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

成功的 `mixing_trace_records` 保持现有字段。单机混料失败转换为：

```json
{
  "stage": "mixing_trace",
  "machine_code": "EA004",
  "reason": "process_duration_not_found",
  "message": "process duration for EA004/PROD-S2-N-SUPPORT was not found"
}
```

每个失败只进入 `errors` 一次；不会再出现在已删除的
`mixing_trace_failures`。其它机台成功记录、正式方案和新活动事件继续返回。

## 11. 后端处理顺序

1. 展示或转发甲方业务结果。
2. 将 `new_active_cutline_events` 加入活动事件集合。
3. 按 `event_id` 应用 `updated_active_cutline_events`；允许把
   `negative_start_time` 更新为 `null`。
4. 按 `closed_active_cutline_event_ids` 移除事件。
5. 下一轮只提交仍在活动集合且未关闭的事件。
6. 独立保存 `errors`，不得因局部错误丢弃其它成功结果。

## 12. 可执行样例

请求场景位于 `examples/scenarios/`。正式响应样例位于 `debug_outputs/`，包括：

- `v3_stockout_auto_response.json`
- `v3_stockout_manual_no_candidate_response.json`
- `v3_overflow_warning_response.json`
- `v3_return_tracking_started_response.json`
- `v3_return_recommended_response.json`
- `v3_silk_prepare_response.json`
- `v3_mixing_failure_response.json`

所有文件均由 `python examples/generate_v3_scenarios.py` 通过真实 Service 链生成。
