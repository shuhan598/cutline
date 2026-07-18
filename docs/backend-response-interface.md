<<<<<<< HEAD
# 切线算法对外输出接口文档

> 更新时间：2026-07-17
>
> 本文档描述算法服务对外输出给后端的 JSON 响应结构。当前项目尚未提供正式 HTTP 路由；本文档中的 HTTP 路径是建议接口契约。

## 1. 输出 JSON 是哪一块

当前代码的对外服务入口是：

```python
CutlineService().evaluate_algorithm(request)
```

返回对象是：

```python
app.schemas.response_schema.CutlineAlgorithmResponse
```

因此，对外输出给后端的是 `CutlineAlgorithmResponse` 整个 JSON 根对象。

不是以下内部对象：

- 不是 `AlgorithmEvaluateResult`。
- 不是 `net_rate_results`。
- 不是 `depletion_results`。
- 不是 `overflow_time_results`。
- 不是任何算法中间计算对象。

代码链路：
=======
# 切线算法后端请求与响应接口

## 1. 正式调用链

当前仓库没有 HTTP 路由。后端调用入口及唯一正式数据链为：
>>>>>>> c89d9c2e13714628ac16d26bc1ef13e365bf952a

```text
CutlineAlgorithmRequest
  -> SnapshotAdapter.to_algorithm_snapshot
  -> CutlinePipeline.evaluate_algorithm
  -> AlgorithmResponseMapper.to_response
  -> CutlineAlgorithmResponse
```

<<<<<<< HEAD
相关代码：

- `app/service/cutline_service.py`
- `app/mappers/algorithm_response_mapper.py`
- `app/schemas/response_schema.py`

## 2. 建议接口

```http
POST /api/cutline/evaluate
Content-Type: application/json
```

请求体：

```text
CutlineAlgorithmRequest
```

响应体：

```text
CutlineAlgorithmResponse
```

当前可参考样例：

- 请求样例：`examples/backend_request_stockout_plan_sample.json`
- 响应样例：`debug_outputs/stockout_plan_sample_response.json`

## 3. 响应顶层结构
=======
后端只应接收 `CutlineAlgorithmResponse`，不得依赖内部
`AlgorithmEvaluateResult` 的净速率、候选排序或模拟诊断字段。

## 2. 顶层响应
>>>>>>> c89d9c2e13714628ac16d26bc1ef13e365bf952a

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

<<<<<<< HEAD
| 字段 | 类型 | 用途 | 是否建议前端展示 | 后端是否需要保存 |
|---|---|---|---|---|
| `calculation_time` | datetime | 本次计算时间 | 是 | 可选 |
| `stockout_warnings` | array | 断料预警 | 是 | 可选 |
| `overflow_warnings` | array | 溢满预警 | 是 | 可选 |
| `cutline_decisions` | array | 切线方案或人工介入结果 | 是 | 建议保存 |
| `return_results` | array | 切回判断结果 | 是 | 建议保存 |
| `silk_screen_results` | array | 丝网清台提醒 | 是 | 可选 |
| `mixing_trace_records` | array | 混料追溯记录 | 视业务决定 | 建议保存，可用于 MES |
| `mixing_trace_failures` | array | 混料追溯失败原因 | 可展示给运维/调度 | 建议保存 |
| `new_active_cutline_events` | array | 新增活动切线跟踪事件 | 否 | 必须保存并下轮回传 |
| `updated_active_cutline_events` | array | 更新后的活动切线跟踪事件 | 否 | 必须按 `event_id` 更新 |
| `errors` | array | 局部计算错误 | 可展示给运维/调度 | 建议保存 |

重要说明：

`new_active_cutline_events` 和 `updated_active_cutline_events` 是算法状态跟踪数据，用于后端保存、更新和下轮请求回传，不用于前端展示。

## 4. 断料预警 `stockout_warnings`

断料预警表示某个 Buffer 区间内某个订单的库存预计会在预警窗口内耗尽。

示例：

```json
{
  "warning_type": "stockout",
  "warning_time": "2026-07-16T08:30:00+08:00",
  "buffer_code": "BUF-ZR-PK",
  "order_code": "O-T",
  "wafer_size": "182",
  "wafer_spec": "N",
  "workshop_code": "WS-S1",
  "upstream_process_code": "P-ZR",
  "downstream_process_code": "P-PK",
  "current_quantity": 100.0,
  "upstream_output_rate": 200.0,
  "downstream_input_rate": 600.0,
  "net_consumption_rate": 400.0,
  "depletion_minutes": 15.0,
  "stockout_warning_lead_minutes": 30.0
}
```

关键字段：

| 字段 | 含义 |
|---|---|
| `buffer_code` | 风险所在 Buffer |
| `order_code` | 风险订单 |
| `upstream_process_code` | 上游工序 |
| `downstream_process_code` | 下游工序 |
| `current_quantity` | 当前区间库存 |
| `upstream_output_rate` | 上游产出速率，片/小时 |
| `downstream_input_rate` | 下游吞入速率，片/小时 |
| `net_consumption_rate` | 净消耗速率，片/小时 |
| `depletion_minutes` | 预计断料时间，分钟 |

## 5. 溢满预警 `overflow_warnings`

溢满预警表示某个物理 Buffer 的库存增长速率会导致其在预警窗口内达到容量上限。

核心字段：

| 字段 | 含义 |
|---|---|
| `buffer_code` | 风险 Buffer |
| `max_capacity` | 最大容量 |
| `total_inventory` | 当前总库存 |
| `remaining_capacity` | 剩余容量 |
| `buffer_growth_rate` | Buffer 总增长速率 |
| `overflow_minutes` | 预计溢满时间，分钟 |
| `order_growth_details` | 各订单对库存增长的贡献明细 |

## 6. 切线决策 `cutline_decisions`

每条切线决策只会出现以下两种形态之一。

正式方案：

```json
{
  "plan": {},
  "manual_intervention": null
}
```

人工介入：

```json
{
  "plan": null,
  "manual_intervention": {}
}
```

### 6.1 正式切线方案 `plan`

断料方案示例：

```json
{
  "plan_id": "stockout:2026-07-16T08:30:00+08:00:BUF-ZR-PK:O-T",
=======
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
>>>>>>> c89d9c2e13714628ac16d26bc1ef13e365bf952a
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

<<<<<<< HEAD
| 字段 | 含义 |
|---|---|
| `plan_id` | 方案 ID |
| `warning_type` | `stockout` 或 `overflow` |
| `buffer_code` | 风险 Buffer |
| `order_code` | 断料目标订单。溢满方案使用 `source_order_code` |
| `initial_capacity_gap` | 初始产能缺口，断料方案字段 |
| `total_contribution_capacity` | 已选机台可贡献产能，断料方案字段 |
| `remaining_capacity_gap` | 方案执行后剩余缺口，`0` 表示已补足 |
| `selected_machines` | 推荐执行切线的机台列表 |
| `risk_resolved` | 风险是否已解决 |
| `manual_intervention_required` | 是否需要人工介入 |

### 6.2 选中机台 `selected_machines`
=======
### 3.2 溢满预警
>>>>>>> c89d9c2e13714628ac16d26bc1ef13e365bf952a

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

<<<<<<< HEAD
字段说明：

| 字段 | 含义 |
|---|---|
| `machine_code` | 推荐切线机台 |
| `source_order_code` | 当前正在生产的源订单 |
| `target_order_code` | 建议切入的目标订单 |
| `contribution_capacity` | 断料场景中切入后的贡献产能 |
| `reduced_capacity` | 溢满场景中切走后的减少产能 |
| `source_depletion_minutes_after` | 借出后源订单预计断料时间 |
| `target_net_rate_after` | 切入后目标订单净速率 |
| `target_overflow_minutes_after` | 切入后目标 Buffer 溢满时间 |

## 7. 人工介入 `manual_intervention`

当算法无法完全解除风险时，`manual_intervention` 有值。

核心字段：

| 字段 | 含义 |
|---|---|
| `warning_type` | 风险类型 |
| `reason` | 需要人工介入的原因 |
| `initial_risk_value` | 初始风险值 |
| `remaining_risk_value` | 仍未解决的风险值 |
| `evaluated_candidate_count` | 已评估候选数 |
| `passed_candidate_count` | 通过影响校验的候选数 |
| `rejected_candidate_count` | 被拒绝候选数 |
| `passed_machines` | 通过的机台 |
| `rejected_machines` | 被拒绝的机台及原因 |

## 8. 跟踪事件 `new_active_cutline_events` 和 `updated_active_cutline_events`

这两个字段只用于后端保存、更新和下轮请求回传，不用于前端展示。

### 8.1 新增跟踪事件 `new_active_cutline_events`

当算法生成正式切线方案并选中机台后，会生成新的活动切线事件。
=======
对外只展示物理 Buffer 总体风险。订单增长明细、订单库存、订单净速率和
订单增长速率不返回；内部仍保留这些数据供溢满候选机台选择使用。

## 4. 切线决策

每条决策通过 `warning_id` 关联预警。正式方案和人工介入使用两个独立模型，
最终 JSON 只出现实际存在的分支。

自动方案：
>>>>>>> c89d9c2e13714628ac16d26bc1ef13e365bf952a

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

<<<<<<< HEAD
1. 持久化 `new_active_cutline_events`。
2. 下一轮请求时，把仍需跟踪的事件放入请求顶层 `active_cutline_events`。
3. 不要把这些事件直接作为前端展示列表；前端展示应使用 `cutline_decisions`、`return_results` 等业务结果字段。

### 8.2 更新跟踪事件 `updated_active_cutline_events`

当算法对历史活动事件做切回判断后，可能返回更新后的事件。

后端处理要求：

1. 按 `event_id` 查找已保存事件。
2. 用 `updated_active_cutline_events` 中的同名事件更新保存状态。
3. 如果更新后 `status == "return_recommended"`，表示算法已经给出切回建议，后端应关闭该跟踪事件，并停止在下一轮请求中回传该事件。
4. 如果更新后仍是 `active`，表示还需要继续跟踪，下轮请求继续放入 `active_cutline_events`。
5. 该字段同样不用于前端展示。

## 9. 切回结果 `return_results`

`return_results` 是前端可以展示的切回判断结果。

关键字段：

| 字段 | 含义 |
|---|---|
| `event_id` | 对应后端保存的跟踪事件 |
| `machine_code` | 切线机台 |
| `return_recommended` | 是否建议切回 |
| `updated_status` | `active` 或 `return_recommended` |
| `reason` | 判断原因 |
| `condition_net_rate_met` | 目标订单是否进入库存积累状态 |
| `condition_stability_met` | 是否超过稳定窗口 |
| `condition_inventory_met` | 库存是否高于安全水位 |

## 10. 丝网结果 `silk_screen_results`

丝网结果用于当前订单完工和清台准备提醒。

核心字段：

| 字段 | 含义 |
|---|---|
| `current_order_code` | 当前丝网订单 |
| `machine_codes` | 相关丝网机台 |
| `remaining_quantity` | 当前订单剩余数量 |
| `current_order_output_rate` | 当前订单产出速率 |
| `estimated_finish_time` | 预计完工时间 |
| `clearance_prepare_time` | 建议清台准备时间 |
| `prepare_clearance` | 当前是否需要准备清台 |
| `reason` | 判断原因 |
| `message` | 可展示说明 |

## 11. 混料追溯 `mixing_trace_records`

正式切线方案生成后，算法会为选中机台计算混料追溯记录。
=======
## 7. 更新与关闭事件

更新事件只包含：
>>>>>>> c89d9c2e13714628ac16d26bc1ef13e365bf952a

```json
{
  "event_id": "CUT-202607170800-EA004",
  "negative_start_time": null
}
```

`negative_start_time: null` 表示净速率已恢复非负，后端必须清空原计时。
响应不会全局排除 `null`，因此该字段不会丢失。

<<<<<<< HEAD
- 保存混料记录。
- 按业务需要推送 MES。
- `notification_status=scheduled` 表示尚未到达混料时间。
- `notification_status=due` 表示按当前时间已经到达或应处理。

## 12. 混料失败 `mixing_trace_failures`

混料追溯失败不会阻断主切线方案。

常见原因：

- 缺少机台产能/工艺时间。
- 源订单或目标订单不存在。
- 源产品和目标产品相同，不需要混料追溯。
- 运行数量无法计算有效产能。

## 13. 局部错误 `errors`

`errors` 只表示某个阶段或某条预警计算失败，不一定代表整个算法失败。
=======
关闭事件只返回 ID：
>>>>>>> c89d9c2e13714628ac16d26bc1ef13e365bf952a

```json
{
  "closed_active_cutline_event_ids": [
    "CUT-202607170800-EA004"
  ]
}
```

<<<<<<< HEAD
后端处理建议：

- 保存并展示给运维或调度人员。
- 不要因为 `errors` 非空就丢弃其它有效结果。
- 如果请求体 schema 不合法，通常会在进入算法前抛出校验异常，不会返回该响应体。

## 14. 前端展示与后端保存边界

建议前端展示：

- `stockout_warnings`
- `overflow_warnings`
- `cutline_decisions`
- `return_results`
- `silk_screen_results`
- `mixing_trace_records`（视业务需要）
- `mixing_trace_failures`（运维/调度视图）
- `errors`（运维/调度视图）

建议仅后端保存和回传，不给前端展示：

- `new_active_cutline_events`
- `updated_active_cutline_events`

原因：这两个字段是算法跨轮次状态跟踪数据，不是业务展示结果。前端如果需要展示切线方案或切回建议，应读取 `cutline_decisions` 和 `return_results`。

## 15. 最小对接闭环

如果后端先做最小闭环，需要完成：

1. 接收算法响应 `CutlineAlgorithmResponse`。
2. 展示或保存 `cutline_decisions`。
3. 保存 `new_active_cutline_events`。
4. 下轮请求把保存的活动事件放入 `active_cutline_events`。
5. 收到 `updated_active_cutline_events` 后按 `event_id` 更新保存记录；若状态为 `return_recommended`，关闭该跟踪事件，下一轮不再回传。
6. 保存 `errors` 便于排查。

=======
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
>>>>>>> c89d9c2e13714628ac16d26bc1ef13e365bf952a
