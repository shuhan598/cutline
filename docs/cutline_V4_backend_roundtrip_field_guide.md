# 切线算法 V4 后端保存及下轮回传字段说明

- 算法版本：V4
- Git 分支：V4
- 当前 Git HEAD：`56f46cb refactor: simplify cutline input schema and update interface docs`
- 文档生成日期：2026-08-03
- 正式接口：`POST /cutline/evaluate`

> 本文档说明当前算法响应中，哪些状态需要后端持久化，以及下一轮调用 `/cutline/evaluate` 时应放入哪个请求字段。本文档不修改正式接口结构。

V4 算法只返回一份正式响应 JSON。本文所说的“后端保存”和“下一轮回传”只是字段用途分类，不是新的接口、响应或运行时区块，也不会引入 `backend_persistence` 等字段。

## 1. 权威状态和处理原则

正式 `CutlineEvaluateResponse` 是原有业务响应字段加一个 `persistence_state`：

```text
POST /cutline/evaluate
  -> CutlineEvaluateResponse
       -> 业务结果和事件增量
       -> persistence_state（跨轮权威状态）
```

后端处理原则：

1. 每轮成功响应后原子保存完整 `persistence_state`，不能只保存 ID 或本轮增量。
2. 下一轮请求只回传当前请求 Schema 确实定义的四类状态。
3. `new_active_cutline_events` 和 `updated_active_cutline_events` 是本轮变化提示，不能替代完整 `persistence_state.active_cutline_events`。
4. completed/expired ID 和新增混料明细需要保存或落业务库，但没有同名下一轮请求字段。
5. `errors` 用于诊断，不是跨轮算法状态。

## 2. `persistence_state` 顶层字段

`PersistenceStateResponse` 当前包含 7 个字段：

| JSON 字段路径 | 中文名称 | 数据类型 | 后端是否必须保存 | 下一轮是否回传 | 业务作用 |
|---|---|---|:---:|:---:|---|
| `persistence_state.pending_cutline_plans` | Pending 切线方案全集 | `PendingCutlinePlan[]` | 是 | 是 | 判断方案是否在确认窗口内被 AGV 绑定变化实际执行 |
| `persistence_state.active_cutline_events` | Active 切线事件全集 | `ActiveCutlineEventPersistenceResponse[]` | 是 | 是 | 持续混料追踪、负速率计时和切回判断 |
| `persistence_state.expired_pending_plan_ids` | 本轮过期方案 ID | `string[]` | 是 | 否 | 后端更新方案过期状态和审计记录 |
| `persistence_state.completed_pending_plan_ids` | 本轮完成方案 ID | `string[]` | 是 | 否 | 后端更新方案完成状态和审计记录 |
| `persistence_state.return_suggested_event_ids` | 已建议切回事件水位 | `string[]` | 是 | 是 | 防止同一 Active 事件重复发送切回建议 |
| `persistence_state.mixed_cutline_event_ids` | 已生成混料事件水位 | `string[]` | 是 | 是 | 防止同一 Active 事件重复生成混料记录 |
| `persistence_state.new_mixing_trace_records` | 本轮新增混料明细 | `MixingTraceRecordResponse[]` | 是 | 否 | 持久化混料业务历史；幂等回传使用 event ID 水位 |

## 3. 必须保存并在下一轮回传的数据

| 上一轮响应字段路径 | 下一轮请求字段路径 | 后端必须保存 | 下一轮必须回传 | 用途 |
|---|---|:---:|:---:|---|
| `persistence_state.pending_cutline_plans` | `pending_cutline_plans` | 是 | 是 | Pending 确认、过期和防止重复方案 |
| `persistence_state.active_cutline_events` | `active_cutline_events` | 是 | 是 | Active 生命周期、混料和切回判断 |
| `persistence_state.return_suggested_event_ids` | `return_suggested_event_ids` | 是 | 是 | 切回建议幂等水位 |
| `persistence_state.mixed_cutline_event_ids` | `mixed_cutline_event_ids` | 是 | 是 | 混料记录幂等水位 |

丢失这些状态的后果：

- 丢失 Pending：可能重复生成方案，或无法识别真实切线执行。
- 丢失 Active：会中断混料追踪、负速率稳定窗口和切回判断。
- 丢失 return 水位：同一事件可能重复推送切回建议。
- 丢失 mixed 水位：同一事件可能重复生成混料记录。

## 4. Pending 切线方案完整字段

`persistence_state.pending_cutline_plans[]` 使用 `PendingCutlinePlan`，当前共有 **25 个顶层字段**。后端必须完整保存并原样回传，不能只保存 `plan_id`、候选机台编码或确认结果。

| JSON 字段路径 | 中文名称 | 数据类型 | 后端是否必须保存 | 下一轮是否回传 | 业务作用 |
|---|---|---|:---:|:---:|---|
| `...pending_cutline_plans[].plan_id` | 方案 ID | string | 是 | 是 | Pending 唯一标识，并关联自动方案和 Active |
| `...pending_cutline_plans[].warning_id` | 预警 ID | string | 是 | 是 | 关联触发方案的断料或溢满预警 |
| `...pending_cutline_plans[].warning_type` | 预警类型 | `stockout` / `overflow` | 是 | 是 | 决定确认时的订单变化方向和语义 |
| `...pending_cutline_plans[].warning_time` | 预警时间 | datetime | 是 | 是 | 记录来源预警时点，不等于方案创建或执行时间 |
| `...pending_cutline_plans[].created_at` | 方案创建时间 | datetime | 是 | 是 | Pending 确认窗口起点 |
| `...pending_cutline_plans[].expire_at` | 方案过期时间 | datetime | 是 | 是 | 超过该时间仍未完成确认时判定过期 |
| `...pending_cutline_plans[].status` | Pending 状态 | enum | 是 | 是 | `PENDING`、`PARTIALLY_CONFIRMED`、`CONFIRMED`、`EXPIRED`、`RETURN_SUGGESTED` |
| `...pending_cutline_plans[].workshop_code` | 车间编码 | string | 是 | 是 | 方案所属车间 |
| `...pending_cutline_plans[].buffer_code` | 预警 Buffer | string | 是 | 是 | 触发方案的风险 Buffer |
| `...pending_cutline_plans[].upstream_process_code` | 预警上游工序 | string | 是 | 是 | 风险区间上游工序 |
| `...pending_cutline_plans[].downstream_process_code` | 预警下游工序 | string | 是 | 是 | 风险区间下游工序 |
| `...pending_cutline_plans[].monitored_order_code` | 被监控订单 | string | 是 | 是 | 用于比较方案执行前后的机台绑定数量 |
| `...pending_cutline_plans[].process_code` | 切线机台工序 | string 或 null | 是 | 是 | 用于确认机台工序上下文；历史兼容时可为空 |
| `...pending_cutline_plans[].source_order_code` | 来源订单 | string 或 null | 是 | 是 | 自动方案中机台切线前订单 |
| `...pending_cutline_plans[].target_order_code` | 目标订单 | string 或 null | 是 | 是 | 自动方案建议切换到的订单 |
| `...pending_cutline_plans[].source_product_code` | 来源产品 | string 或 null | 是 | 是 | 来源订单对应产品编码 |
| `...pending_cutline_plans[].target_product_code` | 目标产品 | string 或 null | 是 | 是 | 目标订单对应产品编码 |
| `...pending_cutline_plans[].before_machine_count` | 执行前机台数量 | integer >= 0 | 是 | 是 | 创建方案时被监控订单绑定的机台数 |
| `...pending_cutline_plans[].before_machine_codes` | 执行前机台列表 | `string[]` | 是 | 是 | 创建方案时被监控订单的机台编码集合 |
| `...pending_cutline_plans[].expected_machine_count` | 预期机台数量 | integer >= 0 | 是 | 是 | 方案全部执行后被监控订单应达到的机台数 |
| `...pending_cutline_plans[].expected_delta_direction` | 预期变化方向 | `increase` / `decrease` | 是 | 是 | 断料通常增加机台，溢满通常减少机台 |
| `...pending_cutline_plans[].candidate_machines` | 候选机台上下文 | `PendingCandidateMachine[]` | 是 | 是 | 确认绑定变化是否与原方案建议一致 |
| `...pending_cutline_plans[].candidate_machine_codes` | 候选机台编码 | `string[]` | 是 | 是 | 必须与 `candidate_machines[].machine_code` 顺序和值一致 |
| `...pending_cutline_plans[].baseline_machine_bindings` | 基线机台绑定 | `BaselineMachineBinding[]` | 是 | 是 | 保存创建方案时的真实 AGV 绑定快照，作为确认基线 |
| `...pending_cutline_plans[].confirmed_machine_codes` | 已确认机台 | `string[]` | 是 | 是 | 已观察到按方案发生绑定变化的机台集合 |

### 4.1 Pending 状态关系

- `before_machine_count` 必须等于 `before_machine_codes` 数量。
- `expected_machine_count` 必须与执行前数量有非零差异，并符合 `expected_delta_direction`。
- `confirmed_machine_codes` 数量决定 `PENDING`、`PARTIALLY_CONFIRMED` 或 `CONFIRMED` 状态。
- `candidate_machines` 和 `baseline_machine_bindings` 不是展示冗余字段，而是跨轮执行确认所需上下文。
- `expire_at` 是确认窗口截止时间；算法用请求快照时间判断，不读取服务器墙钟。

### 4.2 `candidate_machines[]` 完整字段

每个 `PendingCandidateMachine` 当前包含 **19 个字段**：

| JSON 字段路径 | 中文名称 | 数据类型 | 业务作用 |
|---|---|---|---|
| `...candidate_machines[].machine_code` | 候选机台 | string | 被建议执行切线的机台 |
| `...candidate_machines[].baseline_order_code` | 基线订单 | string | 方案创建时机台绑定订单 |
| `...candidate_machines[].baseline_product_code` | 基线产品编码 | string | 基线订单产品编码 |
| `...candidate_machines[].baseline_product_name` | 基线产品名称 | string | 基线订单产品名称 |
| `...candidate_machines[].baseline_wafer_size` | 基线尺寸 | string | 切线前硅片尺寸 |
| `...candidate_machines[].baseline_wafer_spec` | 基线规格 | string | 切线前硅片规格 |
| `...candidate_machines[].baseline_source_grade` | 基线片源等级 | string | 切线前产品片源等级 |
| `...candidate_machines[].expected_target_order_code` | 预期目标订单 | string | 方案建议切换到的订单 |
| `...candidate_machines[].expected_target_product_code` | 预期目标产品编码 | string | 目标订单产品编码 |
| `...candidate_machines[].expected_target_product_name` | 预期目标产品名称 | string | 目标订单产品名称 |
| `...candidate_machines[].expected_target_wafer_size` | 预期目标尺寸 | string | 切线后尺寸 |
| `...candidate_machines[].expected_target_wafer_spec` | 预期目标规格 | string | 切线后规格 |
| `...candidate_machines[].expected_target_source_grade` | 预期目标片源等级 | string | 切线后产品片源等级 |
| `...candidate_machines[].process_code` | 机台工序 | string | 候选机台所属工序 |
| `...candidate_machines[].workshop_code` | 机台车间 | string | 候选机台所属车间 |
| `...candidate_machines[].source_buffer_code` | 来源 Buffer | string 或 null | 原订单产能借出 Buffer |
| `...candidate_machines[].target_buffer_code` | 目标 Buffer | string | 目标订单对应 Buffer |
| `...candidate_machines[].target_upstream_process_code` | 目标上游工序 | string | 目标 Buffer 区间上游工序 |
| `...candidate_machines[].target_downstream_process_code` | 目标下游工序 | string | 目标 Buffer 区间下游工序 |

### 4.3 `baseline_machine_bindings[]` 完整字段

每个 `BaselineMachineBinding` 当前包含 **11 个字段**：

| JSON 字段路径 | 中文名称 | 数据类型 | 业务作用 |
|---|---|---|---|
| `...baseline_machine_bindings[].machine_code` | 机台编码 | string | 基线绑定机台 |
| `...baseline_machine_bindings[].order_code` | 基线订单 | string | 方案创建时 AGV 绑定订单 |
| `...baseline_machine_bindings[].product_code` | 基线产品编码 | string | AGV 绑定产品编码 |
| `...baseline_machine_bindings[].product_name` | 基线产品名称 | string | AGV 绑定产品名称 |
| `...baseline_machine_bindings[].wafer_size` | 基线尺寸 | string | 基线产品硅片尺寸 |
| `...baseline_machine_bindings[].wafer_spec` | 基线规格 | string | AGV 绑定硅片规格 |
| `...baseline_machine_bindings[].source_grade` | 基线片源等级 | string | 基线产品片源等级 |
| `...baseline_machine_bindings[].process_code` | 工序编码 | string | 机台所属工序 |
| `...baseline_machine_bindings[].workshop_code` | 车间编码 | string | 机台所属车间 |
| `...baseline_machine_bindings[].machine_status` | 机台状态 | string 或 null | 方案创建时的运行状态 |
| `...baseline_machine_bindings[].observed_at` | 基线观察时间 | datetime | 该 AGV 绑定记录的时间；旧输入别名 `agv_record_time` 也可校验，但响应序列化字段为 `observed_at` |

## 5. Active 切线事件完整字段

`persistence_state.active_cutline_events[]` 当前包含 **25 个字段**，并与下一轮请求 `active_cutline_events[]` 的字段集合一致。

| JSON 字段路径 | 中文名称 | 数据类型 | 后端是否必须保存 | 下一轮是否回传 | 业务作用 |
|---|---|---|:---:|:---:|---|
| `...active_cutline_events[].event_id` | Active 事件 ID | string | 是 | 是 | 单台机台切线事件唯一标识 |
| `...active_cutline_events[].plan_id` | 来源方案 ID | string 或 null | 是 | 是 | 关联产生该事件的 Pending/自动方案 |
| `...active_cutline_events[].warning_id` | 来源预警 ID | string 或 null | 是 | 是 | 关联触发切线的预警 |
| `...active_cutline_events[].machine_code` | 机台编码 | string | 是 | 是 | 被切线并持续跟踪的机台 |
| `...active_cutline_events[].source_order_code` | 原订单 | string | 是 | 是 | 切线前订单 |
| `...active_cutline_events[].target_order_code` | 目标订单 | string | 是 | 是 | 切线后支援订单 |
| `...active_cutline_events[].workshop_code` | 车间编码 | string | 是 | 是 | 事件所属车间 |
| `...active_cutline_events[].source_buffer_code` | 来源 Buffer | string 或 null | 是 | 是 | 原订单产能借出 Buffer |
| `...active_cutline_events[].target_buffer_code` | 目标 Buffer | string | 是 | 是 | 切回判断监控的目标 Buffer |
| `...active_cutline_events[].upstream_process_code` | 目标上游工序 | string | 是 | 是 | 目标监控区间上游工序 |
| `...active_cutline_events[].downstream_process_code` | 目标下游工序 | string | 是 | 是 | 目标监控区间下游工序 |
| `...active_cutline_events[].source_wafer_size` | 原尺寸 | string 或 null | 是 | 是 | 切线前产品尺寸 |
| `...active_cutline_events[].source_wafer_spec` | 原规格 | string 或 null | 是 | 是 | 切线前硅片规格 |
| `...active_cutline_events[].target_wafer_size` | 目标尺寸 | string | 是 | 是 | 切线后产品尺寸 |
| `...active_cutline_events[].target_wafer_spec` | 目标规格 | string | 是 | 是 | 切线后硅片规格 |
| `...active_cutline_events[].cutline_start_time` | 切线开始观察时间 | datetime | 是 | 是 | AGV 记录首次证明绑定变化的时间，不等于精确物理切线时间 |
| `...active_cutline_events[].negative_start_time` | 连续负速率起点 | datetime 或 null | 是 | 是 | 目标区间净消耗率首次连续小于 0 的时间；恢复非负时清空为 null |
| `...active_cutline_events[].status` | Active 状态 | enum | 是 | 是 | `active`、`return_recommended`、`returned`、`cancelled` |
| `...active_cutline_events[].contribution_capacity` | 切线产能 | number >= 0 或 null | 是 | 是 | 机台切线贡献或削减的小时产能 |
| `...active_cutline_events[].warning_type` | 来源预警类型 | `stockout` / `overflow` / null | 是 | 是 | 记录事件来源业务类型 |
| `...active_cutline_events[].process_code` | 机台工序 | string 或 null | 是 | 是 | 确认切线机台所属输出侧工序 |
| `...active_cutline_events[].warning_buffer_code` | 预警 Buffer | string 或 null | 是 | 是 | 原始预警对应 Buffer |
| `...active_cutline_events[].warning_upstream_process_code` | 预警上游工序 | string 或 null | 是 | 是 | 原预警区间上游工序 |
| `...active_cutline_events[].warning_downstream_process_code` | 预警下游工序 | string 或 null | 是 | 是 | 原预警区间下游工序 |
| `...active_cutline_events[].is_recommended_candidate` | 是否原方案候选 | boolean 或 null | 是 | 是 | 该真实切线是否来自原方案推荐候选 |

### 5.1 两个关键时间字段

- `cutline_start_time` 是算法首次确认或观察到 AGV 绑定发生切线变化的时间，作为混料估算和支援持续时间的基准；它不保证等于设备物理切换的精确秒级时间。
- `negative_start_time` 是目标区间净消耗速率连续小于 0 的开始时间，用于切回稳定窗口判断；净速率恢复非负时应更新为 `null`。
- 两个时间不能混用。后端合并 `updated_active_cutline_events` 时必须保留 `cutline_start_time`，只更新或清空 `negative_start_time`。

## 6. 后端保存但不直接作为同名字段回传的数据

| 响应字段路径 | 后端处理方式 | 是否直接展示甲方 | 为什么不以同名字段回传 |
|---|---|:---:|---|
| `persistence_state.expired_pending_plan_ids` | 更新 Pending 为过期并保存审计记录 | 否 | 请求 Schema 无同名字段；下一轮回传更新后的完整 Pending 集合 |
| `persistence_state.completed_pending_plan_ids` | 更新 Pending 完成状态并保存审计记录 | 否 | 请求 Schema 无同名字段；下一轮回传更新后的完整 Pending/Active 状态 |
| `persistence_state.new_mixing_trace_records` | 写入混料历史库 | 可按业务展示 | 请求 Schema 无混料明细字段；下一轮只回传 `mixed_cutline_event_ids` 水位 |
| `new_active_cutline_events` | 保存本轮新增提示，并以 `event_id` 对照完整 Active | 通常否 | 下一轮必须回传 `persistence_state.active_cutline_events` 完整对象，而不是 12 字段摘要 |
| `updated_active_cutline_events` | 按 `event_id` 合并 `negative_start_time`，包括显式 null | 否 | 下一轮回传合并后的完整 Active 对象 |
| `closed_active_cutline_event_ids` | 更新事件业务状态，并与切回建议一一核对 | 通常否 | 防重复使用累计 `return_suggested_event_ids`，不是回传本轮关闭列表 |
| `mixing_trace_records` | 保存并用于业务展示或通知 | 是 | 请求 Schema 无明细字段；回传 mixed event ID 水位 |
| `return_recommendations` | 保存切回建议历史并推送业务方 | 是 | 请求 Schema 无建议对象字段；回传 return event ID 水位 |
| `errors` | 写日志、告警和排查记录 | 否 | 错误不是算法跨轮状态 |

### 6.1 Active 增量字段

`new_active_cutline_events[]` 是 12 字段公开摘要：`event_id`、`machine_code`、`source_order_code`、`target_order_code`、`workshop_code`、`target_buffer_code`、`upstream_process_code`、`downstream_process_code`、`target_wafer_size`、`target_wafer_spec`、`cutline_start_time`、`negative_start_time`。

`updated_active_cutline_events[]` 只有 `event_id` 和 `negative_start_time`。`negative_start_time: null` 是有效更新，表示清空连续负速率计时，不能在反序列化或数据库更新时忽略。

`closed_active_cutline_event_ids[]` 与同轮 `return_recommendations[].event_id` 一一对应。完整 Active 状态仍以 `persistence_state.active_cutline_events` 为准。

### 6.2 混料明细字段

`persistence_state.new_mixing_trace_records[]` 与公开 `mixing_trace_records[]` 使用同一个 18 字段模型：`mix_trace_id`、`plan_id`、`cutline_event_id`、`machine_code`、`workshop_code`、`process_code`、`process_name`、源/目标订单、源/目标产品、`mix_start_time`、花篮起止序号、篮数、预计总片数、`compositions` 和 `notification_status`。

混料明细必须落业务历史，但下一轮只回传 `mixed_cutline_event_ids`，不回传历史记录本体。

## 7. 下一轮回传映射总表

### 7.1 必须回传

| 上一轮响应字段路径 | 下一轮请求字段路径 | 后端必须保存 | 下一轮必须回传 | 用途 |
|---|---|:---:|:---:|---|
| `persistence_state.pending_cutline_plans` | `pending_cutline_plans` | 是 | 是 | 方案执行确认和过期判断 |
| `persistence_state.active_cutline_events` | `active_cutline_events` | 是 | 是 | Active 生命周期、混料和切回 |
| `persistence_state.return_suggested_event_ids` | `return_suggested_event_ids` | 是 | 是 | 防止重复切回建议 |
| `persistence_state.mixed_cutline_event_ids` | `mixed_cutline_event_ids` | 是 | 是 | 防止重复混料记录 |

### 7.2 不需要直接回传

| 响应字段路径 | 后端处理方式 | 为什么不回传 |
|---|---|---|
| `persistence_state.expired_pending_plan_ids` | 更新数据库中的 Pending 状态并审计 | 请求没有同名字段 |
| `persistence_state.completed_pending_plan_ids` | 更新数据库中的方案完成状态并审计 | 请求没有同名字段 |
| `persistence_state.new_mixing_trace_records` | 保存混料明细 | 请求只接收 mixed event ID 水位 |
| `new_active_cutline_events` | 处理本轮新增提示 | 使用完整 Active 状态回传 |
| `updated_active_cutline_events` | 合并到完整 Active | 使用合并后的完整 Active 状态回传 |
| `closed_active_cutline_event_ids` | 更新关闭/建议状态 | 使用 return event ID 水位防重 |
| `mixing_trace_records` | 保存和展示混料历史 | 请求没有混料明细字段 |
| `return_recommendations` | 保存和推送切回建议 | 请求没有建议对象字段 |
| `stockout_warnings` / `overflow_warnings` / `cutline_decisions` / `silk_screen_results` | 按业务需要保存或展示 | 它们是本轮结果，不是跨轮算法状态 |
| `errors` | 日志和运维排查 | 错误诊断不参与下一轮算法状态 |

## 8. 时间字段说明

| 字段路径 | 时间含义 | 后端处理注意事项 |
|---|---|---|
| `calculation_time` | 本轮算法统一计算时间 | 可作为响应批次时间；不是预警或执行时间 |
| `stockout_warnings[].warning_time` / `overflow_warnings[].warning_time` | 对应预警计算时间 | 用于预警 ID 和业务记录 |
| `cutline_decisions[].plan.calculation_time` | 自动方案生成时间 | 不等于方案实际执行时间 |
| `pending_cutline_plans[].warning_time` | Pending 来源预警时间 | 必须不晚于 `created_at` |
| `pending_cutline_plans[].created_at` | Pending 创建时间 | 确认窗口起点 |
| `pending_cutline_plans[].expire_at` | Pending 过期时间 | 必须晚于 `created_at` |
| `baseline_machine_bindings[].observed_at` | 创建方案时基线 AGV 绑定的观察时间 | 用于证明执行前真实绑定；响应字段名为 `observed_at` |
| `active_cutline_events[].cutline_start_time` | 首次观察到绑定切换的时间 | 混料起算和切回持续时间基准，不等于精确物理切线时间 |
| `active_cutline_events[].negative_start_time` | 目标区间连续负速率起点 | 用于稳定窗口；恢复非负时设为 null |
| `return_recommendations[].return_recommended_time` | 算法产生切回建议的时间 | 不表示甲方已执行切回 |
| `mixing_trace_records[].mix_start_time` | 预计混料开始时间 | 算法估算时间，不是人工确认时间 |
| `silk_screen_results[].calculation_time` | 本轮丝网判断时间 | 与清台实际执行时间不同 |

## 9. 当前正式响应节选

以下仅为当前正式响应中的字段节选，不是独立接口响应：

```json
{
  "persistence_state": {
    "pending_cutline_plans": [],
    "active_cutline_events": [
      {
        "event_id": "CUT-stockout:2026-07-17T08:00:00+08:00:310110302:ORD-S2-001-EA004",
        "plan_id": "stockout:2026-07-17T08:00:00+08:00:310110302:ORD-S2-001",
        "warning_id": "stockout:2026-07-17T08:00:00+08:00:310110302:ORD-S2-001",
        "machine_code": "EA004",
        "source_order_code": "ORD-S2-002",
        "target_order_code": "ORD-S2-001",
        "workshop_code": "S2",
        "source_buffer_code": "310110302",
        "target_buffer_code": "310110302",
        "upstream_process_code": "制绒",
        "downstream_process_code": "碱抛",
        "source_wafer_size": "182",
        "source_wafer_spec": "N",
        "target_wafer_size": "182",
        "target_wafer_spec": "N",
        "cutline_start_time": "2026-07-17T08:03:00+08:00",
        "negative_start_time": "2026-07-17T08:05:00+08:00",
        "status": "active",
        "contribution_capacity": null,
        "warning_type": "stockout",
        "process_code": "制绒",
        "warning_buffer_code": "310110302",
        "warning_upstream_process_code": "制绒",
        "warning_downstream_process_code": "碱抛",
        "is_recommended_candidate": true
      }
    ],
    "expired_pending_plan_ids": [],
    "completed_pending_plan_ids": [],
    "return_suggested_event_ids": [],
    "mixed_cutline_event_ids": [
      "CUT-stockout:2026-07-17T08:00:00+08:00:310110302:ORD-S2-001-EA004"
    ],
    "new_mixing_trace_records": []
  }
}
```

## 10. 下一轮请求状态节选

以下仅为下一轮正式请求中的状态字段节选；完整请求还必须包含 `snapshot_meta`、机台、订单、产品、工艺、Buffer 和 AGV 等输入数据：

```json
{
  "pending_cutline_plans": [],
  "active_cutline_events": [
    {
      "event_id": "CUT-stockout:2026-07-17T08:00:00+08:00:310110302:ORD-S2-001-EA004",
      "plan_id": "stockout:2026-07-17T08:00:00+08:00:310110302:ORD-S2-001",
      "warning_id": "stockout:2026-07-17T08:00:00+08:00:310110302:ORD-S2-001",
      "machine_code": "EA004",
      "source_order_code": "ORD-S2-002",
      "target_order_code": "ORD-S2-001",
      "workshop_code": "S2",
      "source_buffer_code": "310110302",
      "target_buffer_code": "310110302",
      "upstream_process_code": "制绒",
      "downstream_process_code": "碱抛",
      "source_wafer_size": "182",
      "source_wafer_spec": "N",
      "target_wafer_size": "182",
      "target_wafer_spec": "N",
      "cutline_start_time": "2026-07-17T08:03:00+08:00",
      "negative_start_time": "2026-07-17T08:05:00+08:00",
      "status": "active",
      "contribution_capacity": null,
      "warning_type": "stockout",
      "process_code": "制绒",
      "warning_buffer_code": "310110302",
      "warning_upstream_process_code": "制绒",
      "warning_downstream_process_code": "碱抛",
      "is_recommended_candidate": true
    }
  ],
  "return_suggested_event_ids": [],
  "mixed_cutline_event_ids": [
    "CUT-stockout:2026-07-17T08:00:00+08:00:310110302:ORD-S2-001-EA004"
  ]
}
```

## 11. 错误、HTTP 状态和 V4 已知限制

- `errors` 返回给后端，用于日志、运维和算法排查；不属于下一轮回传状态，也不建议把技术错误原文直接展示甲方。
- HTTP 200 表示算法完成正常计算；响应可能包含人工干预或可隔离的局部 `errors`。
- HTTP 422 表示输入数据、完整性或 Snapshot 转换错误，不属于正常成功响应。
- HTTP 500 表示未知程序异常；后端应记录请求标识、时间和服务日志。

当前 V4 `BackendRequestCompletenessValidator` 的通用空编码检查会把非空 `list[str]` 元素当作 Pydantic 对象调用 `model_dump()`。因此非空 `return_suggested_event_ids` 或 `mixed_cutline_event_ids` 在正式完整性校验链上存在既有阻塞风险。本文不修改 Validator；后端仍必须持久化两个水位，不能因为该已知问题丢弃状态。

## 12. 与任务示例或历史资料的真实差异

- Pending 顶层实际是 25 个字段，不包含独立顶层 `observed_at`；`observed_at` 位于每条 `baseline_machine_bindings[]` 中。
- Active 持久化对象实际是 25 个字段；`warning_id`、来源上下文和推荐候选标志均属于完整状态。
- `expired_pending_plan_ids`、`completed_pending_plan_ids` 和 `new_mixing_trace_records` 没有同名请求字段，不能把整个 `persistence_state` 原样嵌入下一轮请求。
- `new_active_cutline_events` 只有 12 个公开摘要字段，不能替代完整 Active。
- `return_recommendations` 不含 `cutline_start_time`；需要时必须按 `event_id` 关联完整 Active。
- 当前接口没有 `backend_persistence` 运行时区块。
