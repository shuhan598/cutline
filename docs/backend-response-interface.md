# 切线算法后端响应接口文档

## 1. 当前传给后端的 JSON 是哪一块

当前代码里还没有正式 HTTP 路由。算法对外统一入口是：

```python
CutlineService().evaluate_algorithm(request)
```

这个方法返回的对象是：

```python
app.schemas.response_schema.CutlineAlgorithmResponse
```

因此，后端真正应该接收/保存/转发的是 `CutlineAlgorithmResponse` 整个 JSON 根对象，而不是算法内部的 `AlgorithmEvaluateResult`，也不是 `net_rate_results`、`depletion_results` 等中间结果。

代码链路如下：

```text
CutlineAlgorithmRequest
  -> SnapshotAdapter.to_algorithm_snapshot
  -> CutlinePipeline.evaluate_algorithm
  -> AlgorithmResponseMapper.to_response
  -> CutlineAlgorithmResponse
```

映射位置：

- `app/service/cutline_service.py`
- `app/mappers/algorithm_response_mapper.py`
- `app/schemas/response_schema.py`

示例响应文件：

- `debug_outputs/stockout_plan_sample_response.json`

## 2. 建议 HTTP 接口

当前项目尚未实现 HTTP 入口。若后端要通过接口调用，建议使用如下契约：

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

| 字段 | 类型 | 含义 | 后端处理建议 |
|---|---|---|---|
| `calculation_time` | datetime | 本次算法计算时间 | 展示、审计、关联本次运行 |
| `stockout_warnings` | array | 断料预警列表 | 展示预警原因和缺口 |
| `overflow_warnings` | array | 溢满预警列表 | 展示溢满风险 |
| `cutline_decisions` | array | 切线决策列表 | 核心字段，可能是正式方案或人工介入 |
| `return_results` | array | 已有活动切线事件的切回判断结果 | 用于提示是否建议切回 |
| `silk_screen_results` | array | 丝网订单清台准备结果 | 用于丝网清台提醒 |
| `mixing_trace_records` | array | 混料追溯通知记录 | 可推送 MES 或保存 |
| `mixing_trace_failures` | array | 混料追溯失败原因 | 展示/排查，不等同于主流程失败 |
| `new_active_cutline_events` | array | 本轮新生成的活动切线事件 | 后端需要持久化，下轮请求再传回 |
| `updated_active_cutline_events` | array | 本轮更新后的历史活动事件 | 后端需要更新持久化状态 |
| `errors` | array | 局部计算错误 | 单条预警失败时记录，不一定代表整个响应失败 |

## 4. 切线决策 `cutline_decisions`

`cutline_decisions` 中每一项二选一：

```json
{
  "plan": {},
  "manual_intervention": null
}
```

或：

```json
{
  "plan": null,
  "manual_intervention": {}
}
```

### 4.1 正式切线方案 `plan`

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
| `plan_id` | 本次切线方案 ID |
| `warning_type` | `stockout` 或 `overflow` |
| `buffer_code` | 触发风险的 Buffer |
| `order_code` | 断料目标订单。溢满方案使用 `source_order_code` |
| `initial_capacity_gap` | 初始产能缺口，断料方案字段 |
| `total_contribution_capacity` | 选中机台切入后可贡献产能，断料方案字段 |
| `remaining_capacity_gap` | 方案执行后剩余缺口，`0` 表示已补足 |
| `selected_machines` | 建议切线的机台列表 |
| `risk_resolved` | 风险是否已由方案解决 |
| `manual_intervention_required` | 是否需要人工介入 |

### 4.2 选中机台 `selected_machines`

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

后端/前端展示建议：

- `machine_code`：推荐切线机台。
- `source_order_code`：机台当前生产订单。
- `target_order_code`：建议切到的目标订单。
- `contribution_capacity`：断料场景中该机台切入后的贡献产能。
- `reduced_capacity`：溢满场景中该机台切走后的减少产能。
- `source_depletion_minutes_after`：借出后原订单预计断料时间；用于说明借出是否安全。
- `target_net_rate_after`：切入后目标订单净速率；小于等于 0 表示断料风险被消除。

## 5. 人工介入 `manual_intervention`

当算法无法完全解除风险时，`plan` 为 `null`，`manual_intervention` 有值。

核心字段：

| 字段 | 含义 |
|---|---|
| `warning_type` | 风险类型 |
| `reason` | 需要人工介入的原因 |
| `initial_risk_value` | 初始风险值，例如产能缺口或增长速率 |
| `remaining_risk_value` | 选机后仍未解决的风险值 |
| `evaluated_candidate_count` | 已评估候选数 |
| `passed_candidate_count` | 通过影响校验的候选数 |
| `rejected_candidate_count` | 被拒绝候选数 |
| `passed_machines` | 通过的机台 |
| `rejected_machines` | 被拒绝的机台及原因 |

## 6. 新活动事件 `new_active_cutline_events`

当 `cutline_decisions[].plan` 存在并有选中机台时，算法会生成活动切线事件。

后端必须持久化这些事件，并在下一轮请求的 `active_cutline_events` 字段中传回算法。

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

1. 保存 `event_id`、`plan_id`、机台、源订单、目标订单、切线时间和状态。
2. 下轮请求时，把仍需跟踪的事件放入请求顶层 `active_cutline_events`。
3. 如果响应中出现 `updated_active_cutline_events`，用其中同 `event_id` 的记录更新持久化状态。

## 7. 切回结果 `return_results`

`return_results` 用于判断历史活动切线事件是否可以切回。

关键字段：

| 字段 | 含义 |
|---|---|
| `event_id` | 对应历史活动事件 |
| `machine_code` | 切线机台 |
| `return_recommended` | 是否建议切回 |
| `updated_status` | `active` 或 `return_recommended` |
| `reason` | 判断原因 |
| `condition_net_rate_met` | 目标订单是否已进入积累状态 |
| `condition_stability_met` | 是否超过稳定窗口 |
| `condition_inventory_met` | 库存是否高于安全水位 |

## 8. 混料追溯 `mixing_trace_records`

当正式切线方案生成后，算法会为选中机台生成混料追溯记录。

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

- 可持久化后推送 MES。
- `notification_status=scheduled` 表示混料尚未到达。
- `notification_status=due` 表示按当前时间已经到达或应处理。
- 如果混料计算失败，失败原因会进入 `mixing_trace_failures`，不会重复进入 `errors`。

## 9. 局部错误 `errors`

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

后端建议：

- 保存并展示。
- 不要因为 `errors` 非空就丢弃其它数组中的有效结果。
- 如果整个请求 schema 不合法，则会在进入算法前抛出校验异常，不会返回这个响应体。

## 10. 当前完整假数据和响应样例

输入假数据：

- `examples/backend_request_stockout_plan_sample.json`

算法输出响应：

- `debug_outputs/stockout_plan_sample_response.json`

这个样例会输出：

- 1 条 `stockout_warnings`
- 1 条正式 `cutline_decisions[].plan`
- 选中机台 `ZR-02`
- 1 条 `new_active_cutline_events`
- 1 条 `mixing_trace_records`
- `errors=[]`

## 11. 对接时最重要的字段

如果后端只先接最小闭环，优先处理这些字段：

1. `cutline_decisions`
2. `new_active_cutline_events`
3. `updated_active_cutline_events`
4. `return_results`
5. `mixing_trace_records`
6. `errors`

其中 `new_active_cutline_events` 和 `updated_active_cutline_events` 是后端持久化闭环的关键。
