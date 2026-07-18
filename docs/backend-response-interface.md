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

```text
CutlineAlgorithmRequest
  -> SnapshotAdapter.to_algorithm_snapshot
  -> CutlinePipeline.evaluate_algorithm
  -> AlgorithmResponseMapper.to_response
  -> CutlineAlgorithmResponse
```

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

```json
{
  "calculation_time": "2026-07-16T08:30:00+08:00",
  "stockout_warnings": [],
  "overflow_warnings": [],
  "cutline_decisions": [],
  "return_results": [],
  "silk_screen_results": [],
  "mixing_trace_records": [],
  "mixing_trace_failures": [],
  "new_active_cutline_events": [],
  "updated_active_cutline_events": [],
  "errors": []
}
```

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
  "warning_type": "stockout",
  "calculation_time": "2026-07-16T08:30:00+08:00",
  "workshop_code": "WS-S1",
  "buffer_code": "BUF-ZR-PK",
  "order_code": "O-T",
  "wafer_size": "182",
  "wafer_spec": "N",
  "upstream_process_code": "P-ZR",
  "downstream_process_code": "P-PK",
  "initial_capacity_gap": 400.0,
  "total_contribution_capacity": 600.0,
  "remaining_capacity_gap": 0.0,
  "selected_machines": [],
  "risk_resolved": true,
  "manual_intervention_required": false
}
```

关键字段：

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

```json
{
  "machine_code": "ZR-02",
  "source_order_code": "O-R",
  "target_order_code": "O-T",
  "source_buffer_code": "BUF-ZR-PK",
  "target_buffer_code": "BUF-ZR-PK",
  "process_code": "P-ZR",
  "workshop_code": "WS-S1",
  "wafer_size": "182",
  "source_wafer_spec": "N",
  "target_wafer_spec": "N",
  "contribution_capacity": 600.0,
  "reduced_capacity": null,
  "utilization_rate": 1.0,
  "idle_rate": 0.0,
  "source_net_rate_before": -400.0,
  "source_net_rate_after": 200.0,
  "source_depletion_minutes_after": 600.0,
  "target_net_rate_before": 400.0,
  "target_net_rate_after": -200.0,
  "target_overflow_minutes_after": null
}
```

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

```json
{
  "event_id": "CUT-stockout:2026-07-16T08:30:00+08:00:BUF-ZR-PK:O-T-ZR-02",
  "plan_id": "stockout:2026-07-16T08:30:00+08:00:BUF-ZR-PK:O-T",
  "machine_code": "ZR-02",
  "source_order_code": "O-R",
  "target_order_code": "O-T",
  "workshop_code": "WS-S1",
  "source_buffer_code": "BUF-ZR-PK",
  "target_buffer_code": "BUF-ZR-PK",
  "upstream_process_code": "P-ZR",
  "downstream_process_code": "P-PK",
  "source_wafer_size": "182",
  "source_wafer_spec": "N",
  "target_wafer_size": "182",
  "target_wafer_spec": "N",
  "cutline_start_time": "2026-07-16T08:30:00+08:00",
  "negative_start_time": null,
  "status": "active",
  "contribution_capacity": 600.0,
  "warning_type": "stockout"
}
```

后端处理要求：

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

```json
{
  "mix_trace_id": "MIX-stockout:2026-07-16T08:30:00+08:00:BUF-ZR-PK:O-T-ZR-02",
  "plan_id": "stockout:2026-07-16T08:30:00+08:00:BUF-ZR-PK:O-T",
  "cutline_event_id": "CUT-stockout:2026-07-16T08:30:00+08:00:BUF-ZR-PK:O-T-ZR-02",
  "machine_code": "ZR-02",
  "source_order_code": "O-R",
  "target_order_code": "O-T",
  "source_product_code": "PROD-R",
  "target_product_code": "PROD-T",
  "mix_start_time": "2026-07-16T10:37:00+08:00",
  "mixed_basket_start_index": 1,
  "mixed_basket_end_index": 10,
  "mixed_basket_count": 10,
  "estimated_total_mixed_pieces": 1200,
  "notification_status": "scheduled"
}
```

后端处理建议：

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

```json
{
  "stage": "stockout_candidate",
  "warning_type": "stockout",
  "warning_key": "BUF-TARGET:ORD-TARGET:182:N:P-ZR:P-PK",
  "reason": "candidate_machine_calculation_error",
  "message": "candidate boundary failed"
}
```

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

