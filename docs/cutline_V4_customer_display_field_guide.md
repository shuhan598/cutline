# 切线算法 V4 甲方展示数据字段说明

- 算法版本：V4
- Git 分支：V4
- 当前 Git HEAD：`56f46cb refactor: simplify cutline input schema and update interface docs`
- 文档生成日期：2026-08-03
- 正式接口：`POST /cutline/evaluate`

> 本文档只对当前算法已有输出字段进行用途分类和中文解释，不修改正式接口结构。算法的全部结果仍先返回后端，再由后端选择相应业务字段展示或推送给甲方。

“甲方展示数据”只是字段用途分类，不是新的响应区块。V4 算法仍只返回一份 JSON；本文不会引入 `customer_display`、`section_name`、`audience` 或 `description` 等运行时字段。

## 1. 当前正式响应骨架

`CutlineEvaluateResponse` 当前共有 12 个顶层字段：

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

其中 `new_active_cutline_events`、`updated_active_cutline_events`、`closed_active_cutline_event_ids`、`errors` 和 `persistence_state` 主要供后端处理，通常不直接展示甲方。

## 2. 本轮计算时间

| JSON 字段路径 | 中文名称 | 数据类型 | 业务含义 | 是否建议直接展示 | 备注 |
|---|---|---|---|---|---|
| `calculation_time` | 本轮计算时间 | datetime | 本轮算法统一使用的快照计算时间 | 是 | 可显示为“算法更新时间”；不等于预警发生时间，也不等于实际切线执行时间 |

自动方案和丝网提醒中也有各自的 `calculation_time`，用于标识对应结果的计算时点。

## 3. 断料预警 `stockout_warnings`

**数据使用对象：甲方业务人员、车间管理人员和前端展示系统。**

**数据用途：由后端用于页面展示或消息推送，说明哪个车间、哪个 Buffer、哪个订单存在断料风险，以及预计多少分钟后断料。**

`stockout_warnings[]` 当前包含 16 个字段：

| JSON 字段路径 | 中文名称 | 数据类型 | 业务含义 | 是否建议直接展示 | 备注 |
|---|---|---|---|---|---|
| `stockout_warnings[].warning_id` | 断料预警 ID | string | 由预警时间、Buffer 和订单组成的稳定关联标识 | 可隐藏 | 后端应保留，用于关联切线决策和日志 |
| `stockout_warnings[].warning_type` | 预警类型 | `"stockout"` | 固定表示断料预警 | 可隐藏 | 可用于前端选择图标、颜色和模板 |
| `stockout_warnings[].warning_time` | 预警时间 | datetime | 算法产生该预警的计算时间 | 是 | 不代表设备实际切线时间 |
| `stockout_warnings[].buffer_code` | Buffer 编码 | string | 存在断料风险的 Buffer | 是 | 当前公开响应不含 Buffer 名称 |
| `stockout_warnings[].order_code` | 订单编码 | string | 当前存在断料风险的订单 | 是 | 当前公开响应不含订单名称和产品编码 |
| `stockout_warnings[].wafer_size` | 硅片尺寸 | string | 风险订单对应的尺寸 | 是 | 例如 `182` |
| `stockout_warnings[].wafer_spec` | 硅片规格 | string | 风险订单对应的硅片规格 | 是 | 具体枚举由业务主数据定义 |
| `stockout_warnings[].workshop_code` | 车间编码 | string | 风险所属车间 | 是 | 当前公开响应不含车间名称 |
| `stockout_warnings[].upstream_process_code` | 上游工序编码 | string | Buffer 区间的上游工序 | 是 | 可由后端关联工序名称 |
| `stockout_warnings[].downstream_process_code` | 下游工序编码 | string | Buffer 区间的下游工序 | 是 | 可由后端关联工序名称 |
| `stockout_warnings[].current_quantity` | 当前库存 | number >= 0 | 风险订单在该 Buffer 的当前数量 | 是 | 数量单位应与后端业务口径保持一致 |
| `stockout_warnings[].upstream_output_rate` | 上游产出速率 | number >= 0 | 上游每小时向 Buffer 增加的数量 | 是 | 小时速率 |
| `stockout_warnings[].downstream_input_rate` | 下游消耗速率 | number >= 0 | 下游每小时从 Buffer 消耗的数量 | 是 | 小时速率 |
| `stockout_warnings[].net_consumption_rate` | 净消耗速率 | number | 下游消耗减去上游产出的净消耗速度 | 是 | 正值表示库存持续下降 |
| `stockout_warnings[].depletion_minutes` | 预计断料分钟数 | number >= 0 | 按当前净消耗速度预计还可维持的分钟数 | 是 | 建议作为预警主信息 |
| `stockout_warnings[].stockout_warning_lead_minutes` | 断料预警提前量 | number > 0 | 触发断料预警使用的时间窗口 | 可隐藏 | 可用于解释为什么本轮触发预警 |

以下仅为当前正式响应中的字段节选：

```json
{
  "stockout_warnings": [
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
  ]
}
```

## 4. 溢满预警 `overflow_warnings`

**数据使用对象：甲方业务人员、车间管理人员和前端展示系统。**

**数据用途：由后端用于展示 Buffer 当前库存、容量、增长速度及预计溢满时间。**

`overflow_warnings[]` 当前包含 11 个字段：

| JSON 字段路径 | 中文名称 | 数据类型 | 业务含义 | 是否建议直接展示 | 备注 |
|---|---|---|---|---|---|
| `overflow_warnings[].warning_id` | 溢满预警 ID | string | 由预警时间和 Buffer 组成的关联标识 | 可隐藏 | 用于关联决策和日志 |
| `overflow_warnings[].warning_type` | 预警类型 | `"overflow"` | 固定表示溢满预警 | 可隐藏 | 可用于选择展示模板 |
| `overflow_warnings[].warning_time` | 预警时间 | datetime | 算法产生该预警的计算时间 | 是 | 与本轮 `calculation_time` 通常一致 |
| `overflow_warnings[].buffer_code` | Buffer 编码 | string | 存在溢满风险的 Buffer | 是 | 当前公开响应不含 Buffer 名称 |
| `overflow_warnings[].workshop_code` | 车间编码 | string | 风险所属车间 | 是 | 当前公开响应不含车间名称 |
| `overflow_warnings[].total_inventory` | Buffer 总库存 | number >= 0 | 参与该物理 Buffer 组计算的当前总库存 | 是 | 不是单一订单库存 |
| `overflow_warnings[].max_capacity` | 最大容量 | number > 0 | Buffer 允许的最大库存容量 | 是 | 用于计算剩余容量 |
| `overflow_warnings[].remaining_capacity` | 剩余容量 | number | 最大容量减去当前总库存 | 是 | 已超容量时可能为负数 |
| `overflow_warnings[].buffer_growth_rate` | Buffer 增长速率 | number | 当前 Buffer 每小时净增长速度 | 是 | 正值表示库存继续增加 |
| `overflow_warnings[].overflow_minutes` | 预计溢满分钟数 | number >= 0 | 按当前增长速度预计到达满容量的分钟数 | 是 | 建议作为预警主信息 |
| `overflow_warnings[].overflow_warning_lead_minutes` | 溢满预警提前量 | number > 0 | 触发溢满预警使用的时间窗口 | 可隐藏 | 用于解释触发阈值 |

当前公开 `OverflowWarningResponse` **不包含** `order_growth_details`、上下游工序编码或订单信息。若页面需要这些内容，只能由后端使用本轮主数据或其他业务数据关联，不能当作算法响应字段。

> 当前溢满预警字段可以使用；溢满自动切线方案逻辑暂不修改，后续可能重新评审。

## 5. 切线决策 `cutline_decisions`

`cutline_decisions[]` 是一个联合结构，每项只会出现以下两个分支之一：

| 分支 | 当前 JSON 结构 | 业务含义 | HTTP 状态 |
|---|---|---|---|
| 自动方案 | `warning_id` + `plan` | 算法找到可执行且已解除风险的切线方案 | 200 |
| 人工干预 | `warning_id` + `manual_intervention` | 算法完成计算，但无法形成自动方案，需要人工处理 | 200 |

### 5.1 自动断料方案

`cutline_decisions[].plan.warning_type="stockout"` 时包含 14 个方案字段：

| JSON 字段路径 | 中文名称 | 数据类型 | 业务含义 | 是否建议直接展示 | 备注 |
|---|---|---|---|---|---|
| `cutline_decisions[].warning_id` | 关联预警 ID | string | 与断料预警一一关联 | 可隐藏 | 后端关联键 |
| `cutline_decisions[].plan.plan_id` | 方案 ID | string | 正式切线方案唯一标识 | 可隐藏 | 后端必须保留，Pending 使用同一 ID |
| `cutline_decisions[].plan.warning_type` | 方案类型 | `"stockout"` | 断料支援方案 | 是 | 可显示为“断料支援” |
| `cutline_decisions[].plan.calculation_time` | 方案计算时间 | datetime | 生成方案的算法时间 | 是 | 不是实际执行时间 |
| `cutline_decisions[].plan.workshop_code` | 车间编码 | string | 方案所属车间 | 是 | - |
| `cutline_decisions[].plan.buffer_code` | 风险 Buffer | string | 需要获得产能支援的 Buffer | 是 | - |
| `cutline_decisions[].plan.order_code` | 风险订单 | string | 需要获得产能支援的订单 | 是 | - |
| `cutline_decisions[].plan.wafer_size` | 目标尺寸 | string | 风险订单尺寸 | 是 | - |
| `cutline_decisions[].plan.wafer_spec` | 目标规格 | string | 风险订单规格 | 是 | - |
| `cutline_decisions[].plan.upstream_process_code` | 上游工序 | string | 风险区间上游工序 | 是 | - |
| `cutline_decisions[].plan.downstream_process_code` | 下游工序 | string | 风险区间下游工序 | 是 | - |
| `cutline_decisions[].plan.initial_capacity_gap` | 初始产能缺口 | number | 方案生成前的小时产能缺口 | 是 | - |
| `cutline_decisions[].plan.total_contribution_capacity` | 总贡献产能 | number >= 0 | 选中机台贡献的小时产能合计 | 是 | - |
| `cutline_decisions[].plan.remaining_capacity_gap` | 剩余产能缺口 | number >= 0 | 执行方案后的剩余缺口 | 是 | 正式自动方案通常为 0 |
| `cutline_decisions[].plan.selected_machines` | 选中机台 | array | 建议执行切线的机台明细 | 是 | 见下表 |

断料 `selected_machines[]` 字段：

| JSON 字段路径 | 中文名称 | 数据类型 | 业务含义 | 是否建议直接展示 | 备注 |
|---|---|---|---|---|---|
| `...selected_machines[].machine_code` | 机台编码 | string | 建议切线机台 | 是 | - |
| `...selected_machines[].source_order_code` | 原订单 | string | 机台切线前生产订单 | 是 | - |
| `...selected_machines[].target_order_code` | 目标订单 | string | 建议切换到的订单 | 是 | - |
| `...selected_machines[].source_buffer_code` | 来源 Buffer | string | 原订单对应的产能借出 Buffer | 是 | - |
| `...selected_machines[].target_buffer_code` | 目标 Buffer | string | 目标订单对应的 Buffer | 是 | 允许与来源 Buffer 相同是现有数据表现，不代表本文修改算法 |
| `...selected_machines[].process_code` | 工序编码 | string | 机台所属工序 | 是 | - |
| `...selected_machines[].workshop_code` | 车间编码 | string | 机台所属车间 | 是 | - |
| `...selected_machines[].wafer_size` | 硅片尺寸 | string | 目标生产尺寸 | 是 | - |
| `...selected_machines[].source_wafer_spec` | 原规格 | string | 切线前硅片规格 | 是 | - |
| `...selected_machines[].target_wafer_spec` | 目标规格 | string | 切线后硅片规格 | 是 | - |
| `...selected_machines[].contribution_capacity` | 贡献产能 | number >= 0 | 该机台为断料风险贡献的小时产能 | 是 | 仅断料方案存在 |

以下仅为当前正式响应中的字段节选：

```json
{
  "cutline_decisions": [
    {
      "warning_id": "stockout:2026-07-17T08:00:00+08:00:310110302:ORD-S2-001",
      "plan": {
        "plan_id": "stockout:2026-07-17T08:00:00+08:00:310110302:ORD-S2-001",
        "warning_type": "stockout",
        "calculation_time": "2026-07-17T08:00:00+08:00",
        "workshop_code": "S2",
        "buffer_code": "310110302",
        "order_code": "ORD-S2-001",
        "wafer_size": "182",
        "wafer_spec": "N",
        "upstream_process_code": "制绒",
        "downstream_process_code": "碱抛",
        "initial_capacity_gap": 400.0,
        "total_contribution_capacity": 600.0,
        "remaining_capacity_gap": 0.0,
        "selected_machines": [
          {
            "machine_code": "EA004",
            "source_order_code": "ORD-S2-002",
            "target_order_code": "ORD-S2-001",
            "source_buffer_code": "310110302",
            "target_buffer_code": "310110302",
            "process_code": "制绒",
            "workshop_code": "S2",
            "wafer_size": "182",
            "source_wafer_spec": "N",
            "target_wafer_spec": "N",
            "contribution_capacity": 600.0
          }
        ]
      }
    }
  ]
}
```

### 5.2 自动溢满方案

`cutline_decisions[].plan.warning_type="overflow"` 时，公共字段为：`plan_id`、`warning_type`、`calculation_time`、`workshop_code`、`buffer_code`、`source_order_code`、`source_wafer_size`、`source_wafer_spec`、`upstream_process_code`、`downstream_process_code`、`initial_growth_rate`、`total_reduced_capacity`、`remaining_growth_rate`、`updated_overflow_minutes`、`selected_machines`。

| JSON 字段路径 | 中文名称 | 数据类型 | 业务含义 | 是否建议直接展示 | 备注 |
|---|---|---|---|---|---|
| `cutline_decisions[].plan.source_order_code` | 来源订单 | string | 当前对溢满增长贡献最大的来源订单 | 是 | 溢满方案特有 |
| `cutline_decisions[].plan.source_wafer_size` | 来源尺寸 | string | 来源订单硅片尺寸 | 是 | - |
| `cutline_decisions[].plan.source_wafer_spec` | 来源规格 | string | 来源订单硅片规格 | 是 | - |
| `cutline_decisions[].plan.initial_growth_rate` | 初始增长率 | number | 方案前 Buffer 小时净增长率 | 是 | - |
| `cutline_decisions[].plan.total_reduced_capacity` | 总削减产能 | number >= 0 | 选中机台从来源侧减少的小时产能合计 | 是 | - |
| `cutline_decisions[].plan.remaining_growth_rate` | 剩余增长率 | number | 方案后的 Buffer 小时净增长率 | 是 | - |
| `cutline_decisions[].plan.updated_overflow_minutes` | 调整后溢满分钟数 | number >= 0 或 null | 方案后仍增长时的预计溢满时间；不再增长时为 null | 是 | - |
| `...selected_machines[].reduced_capacity` | 削减产能 | number >= 0 | 该机台从溢满来源侧减少的小时产能 | 是 | 其余 10 个机台字段与断料方案相同 |

当前公共自动方案没有 `risk_resolved` 字段；是否形成 `plan` 已表示算法内部判定方案可用。本文不修改溢满计算或方案生成逻辑。

### 5.3 人工干预结果

| JSON 字段路径 | 中文名称 | 数据类型 | 业务含义 | 是否建议直接展示 | 备注 |
|---|---|---|---|---|---|
| `cutline_decisions[].warning_id` | 关联预警 ID | string | 与对应断料或溢满预警关联 | 可隐藏 | 后端关联键 |
| `cutline_decisions[].manual_intervention.reason` | 人工干预原因 | string | 无法生成自动方案的稳定原因码 | 是，建议转中文文案 | 例如 `no_candidate_machine`、`insufficient_capacity` |

当前公开人工干预响应没有 `reason_code`、候选机台数量、`context` 或 `related_machine_codes`。人工干预属于正常业务结果，接口仍返回 HTTP 200，不代表算法接口调用失败。

以下仅为当前正式响应中的字段节选：

```json
{
  "cutline_decisions": [
    {
      "warning_id": "stockout:2026-07-17T08:00:00+08:00:310110302:ORD-S2-001",
      "manual_intervention": {
        "reason": "no_candidate_machine"
      }
    }
  ]
}
```

## 6. 切回建议 `return_recommendations`

| JSON 字段路径 | 中文名称 | 数据类型 | 业务含义 | 是否建议直接展示 | 备注 |
|---|---|---|---|---|---|
| `return_recommendations[].event_id` | Active 事件 ID | string | 被建议切回的活动切线事件 | 可隐藏 | 关联完整 Active 和防重水位 |
| `return_recommendations[].machine_code` | 机台编码 | string | 建议切回的机台 | 是 | - |
| `return_recommendations[].source_order_code` | 原订单 | string | 切线前生产的订单 | 是 | 切回目标通常是该订单 |
| `return_recommendations[].target_order_code` | 当前支援订单 | string | 切线后正在支援的订单 | 是 | - |
| `return_recommendations[].return_recommended_time` | 切回建议时间 | datetime | 算法产生切回建议的时间 | 是 | 不表示甲方已实际执行切回 |

当前公开切回建议没有 `plan_id`、`cutline_start_time`、`negative_start_time`、稳定窗口、安全库存或 `reason`。如需展示切线开始时间，后端应按 `event_id` 关联 `persistence_state.active_cutline_events[].cutline_start_time`。

- `cutline_start_time`：算法根据 AGV 绑定记录首次确认或观察到切线发生的时间，不是设备物理切换的精确秒级时间。
- `return_recommended_time`：算法给出切回建议的时间。
- 切回建议不表示甲方已经实际执行切回。

以下仅为当前正式响应中的字段节选：

```json
{
  "return_recommendations": [
    {
      "event_id": "CUT-stockout:2026-07-17T08:00:00+08:00:310110302:ORD-S2-001-EA004",
      "machine_code": "EA004",
      "source_order_code": "ORD-S2-002",
      "target_order_code": "ORD-S2-001",
      "return_recommended_time": "2026-07-17T08:26:00+08:00"
    }
  ]
}
```

## 7. 丝网提醒 `silk_screen_results`

| JSON 字段路径 | 中文名称 | 数据类型 | 业务含义 | 是否建议直接展示 | 备注 |
|---|---|---|---|---|---|
| `silk_screen_results[].workshop_code` | 车间编码 | string | 丝网工序所属车间 | 是 | - |
| `silk_screen_results[].current_order_code` | 当前订单 | string | 丝网当前生产订单 | 是 | - |
| `silk_screen_results[].machine_codes` | 机台列表 | string array | 当前订单涉及的运行机台 | 是 | - |
| `silk_screen_results[].calculation_time` | 计算时间 | datetime | 本轮丝网计算时间 | 是 | - |
| `silk_screen_results[].silk_screen_clear_minutes` | 清台准备提前量 | number > 0 | 丝网清台准备使用的分钟参数 | 是 | - |
| `silk_screen_results[].remaining_production_hours` | 剩余生产小时 | number >= 0 或 null | 按当前产能预计的剩余生产时间 | 是 | 无有效产能时为 null |
| `silk_screen_results[].prepare_clearance` | 是否准备清台 | boolean | 是否已经进入清台准备窗口 | 是 | 建议作为主要状态 |
| `silk_screen_results[].reason` | 原因码 | enum | 当前丝网判断原因 | 可隐藏或转中文 | 四种取值见下文 |
| `silk_screen_results[].message` | 提醒文案 | string | 当前原因的可读说明 | 是 | 可直接作为提示基础文案 |

`reason` 当前取值：`not_yet_time_to_prepare`、`clearance_preparation_required`、`current_order_completed`、`current_order_capacity_unavailable`。

当前公开丝网结果没有剩余数量、小时产出、预计完工时间、清台准备时间或下一订单字段，不能在前端接口模型中自行补造。

## 8. 混料追踪 `mixing_trace_records`

混料记录既需要后端保存历史，也可以展示或推送给甲方。页面建议重点展示机台、订单、时间、花篮范围、篮数和预计混料片数。

| JSON 字段路径 | 中文名称 | 数据类型 | 业务含义 | 是否建议直接展示 | 备注 |
|---|---|---|---|---|---|
| `mixing_trace_records[].mix_trace_id` | 混料记录 ID | string | 混料记录唯一标识 | 可隐藏 | 后端历史主键 |
| `mixing_trace_records[].plan_id` | 来源方案 ID | string | 产生该混料记录的切线方案 | 可隐藏 | 用于审计关联 |
| `mixing_trace_records[].cutline_event_id` | Active 事件 ID | string | 对应的实际切线事件 | 可隐藏 | 用于防重和关联 |
| `mixing_trace_records[].machine_code` | 机台编码 | string | 发生混料的机台 | 是 | - |
| `mixing_trace_records[].workshop_code` | 车间编码 | string | 机台所属车间 | 是 | - |
| `mixing_trace_records[].process_code` | 工序编码 | string | 发生混料的工序 | 是 | - |
| `mixing_trace_records[].process_name` | 工序名称 | string | 工序可读名称 | 是 | - |
| `mixing_trace_records[].source_order_code` | 原订单 | string | 切线前订单 | 是 | - |
| `mixing_trace_records[].target_order_code` | 目标订单 | string | 切线后订单 | 是 | - |
| `mixing_trace_records[].source_product_code` | 原产品编码 | string | 切线前产品型号 | 是 | - |
| `mixing_trace_records[].target_product_code` | 目标产品编码 | string | 切线后产品型号 | 是 | - |
| `mixing_trace_records[].mix_start_time` | 预计混料开始时间 | datetime | 依据切线事件和工艺流转估算的混料起点 | 是 | 不是人工确认时间 |
| `mixing_trace_records[].mixed_basket_start_index` | 混料起始篮序号 | integer >= 1 | 预计混料花篮区间起点 | 是 | - |
| `mixing_trace_records[].mixed_basket_end_index` | 混料结束篮序号 | integer >= 1 | 预计混料花篮区间终点 | 是 | - |
| `mixing_trace_records[].mixed_basket_count` | 混料篮数 | integer >= 1 | 预计受混料影响的花篮数量 | 是 | - |
| `mixing_trace_records[].estimated_total_mixed_pieces` | 预计混料总片数 | integer >= 1 | 各组成预计片数合计 | 是 | - |
| `mixing_trace_records[].compositions` | 混料组成 | array | 原订单和目标订单的预计组成 | 是 | 内部字段见下表 |
| `mixing_trace_records[].notification_status` | 通知状态 | `"scheduled"` 或 `"due"` | 提醒是预排还是已经到期 | 是 | - |

`compositions[]` 字段：

| JSON 字段路径 | 中文名称 | 数据类型 | 业务含义 | 是否建议直接展示 | 备注 |
|---|---|---|---|---|---|
| `...compositions[].order_code` | 组成订单 | string | 参与混料的订单 | 是 | - |
| `...compositions[].product_code` | 组成产品 | string | 参与混料的产品型号 | 是 | - |
| `...compositions[].sequence` | 组成顺序 | integer >= 1 | 原、目标物料的先后顺序 | 是 | - |
| `...compositions[].estimated_pieces` | 预计片数 | integer >= 0 | 该组成预计占用片数 | 是 | - |

以下仅为当前正式响应中的字段节选：

```json
{
  "mixing_trace_records": [
    {
      "mix_trace_id": "MIX-stockout:2026-07-17T08:00:00+08:00:310110302:ORD-S2-001-EA004",
      "plan_id": "stockout:2026-07-17T08:00:00+08:00:310110302:ORD-S2-001",
      "cutline_event_id": "CUT-stockout:2026-07-17T08:00:00+08:00:310110302:ORD-S2-001-EA004",
      "machine_code": "EA004",
      "workshop_code": "S2",
      "process_code": "制绒",
      "process_name": "制绒",
      "source_order_code": "ORD-S2-002",
      "target_order_code": "ORD-S2-001",
      "source_product_code": "PROD-S2-N-SUPPORT",
      "target_product_code": "PROD-S2-N-TARGET",
      "mix_start_time": "2026-07-17T10:10:00+08:00",
      "mixed_basket_start_index": 1,
      "mixed_basket_end_index": 10,
      "mixed_basket_count": 10,
      "estimated_total_mixed_pieces": 1200,
      "compositions": [
        {
          "order_code": "ORD-S2-002",
          "product_code": "PROD-S2-N-SUPPORT",
          "sequence": 1,
          "estimated_pieces": 600
        },
        {
          "order_code": "ORD-S2-001",
          "product_code": "PROD-S2-N-TARGET",
          "sequence": 2,
          "estimated_pieces": 600
        }
      ],
      "notification_status": "scheduled"
    }
  ]
}
```

## 9. 不建议直接展示的后端字段

| 当前响应字段 | 中文业务名称 | 是否给甲方展示 | 展示方式建议 | 是否建议后端保存历史 |
|---|---|:---:|---|:---:|
| `calculation_time` | 算法更新时间 | 是 | 页面更新时间 | 是 |
| `stockout_warnings` | 断料预警 | 是 | 预警列表、消息推送 | 是 |
| `overflow_warnings` | 溢满预警 | 是 | 预警列表、消息推送 | 是 |
| `cutline_decisions` | 自动方案或人工干预 | 是 | 方案详情或人工处理提示 | 是 |
| `return_recommendations` | 切回建议 | 是 | 机台级消息或待办 | 是 |
| `silk_screen_results` | 丝网清台提醒 | 是 | 状态提示或消息推送 | 建议 |
| `mixing_trace_records` | 混料追踪 | 是 | 混料明细和通知 | **必须** |
| `new_active_cutline_events` | 新增 Active 摘要 | 通常否 | 后台事件状态 | **必须处理** |
| `updated_active_cutline_events` | Active 计时更新 | 否 | 不直接展示 | **必须处理** |
| `closed_active_cutline_event_ids` | 本轮关闭事件 ID | 通常否 | 可用于后台状态，不展示技术 ID | **必须处理** |
| `errors` | 算法诊断 | 否 | 后台日志和运维排查 | 是 |
| `persistence_state` | 跨轮权威状态 | 否 | 不直接展示 | **必须** |

Active 增量字段不是下一轮权威对象。后端应使用 `persistence_state.active_cutline_events` 保存和回传完整 Active 状态，具体规则见《切线算法 V4 后端保存及下轮回传字段说明》。

## 10. 错误与 HTTP 状态

- `errors` 返回给后端，用于日志、运维和算法排查，不属于下一轮回传状态，也不建议将技术错误原文直接展示给甲方。
- `errors[].stage`、`reason`、`message` 表示失败阶段、机器原因和技术信息；普通 Pipeline 错误还可能含 `warning_type`、`warning_key`，混料错误含 `machine_code`。
- HTTP 200 表示算法正常完成；结果可以是预警、自动方案、人工干预、无预警或带可隔离的局部 `errors`。
- HTTP 422 表示输入、完整性或 Snapshot 转换错误，不属于正常成功响应。
- HTTP 500 表示未知程序异常，后端应记录请求标识、时间和服务日志。

## 11. 与任务示例或历史资料的真实差异

以下差异以当前 V4 `response_schema.py` 为准：

- 断料预警没有 `product_code`、各类名称字段或通用 `warning_lead_minutes`；实际字段为 `stockout_warning_lead_minutes`。
- 溢满预警没有 `order_growth_details`、订单字段和上下游工序字段；实际增长字段为 `buffer_growth_rate`。
- 自动计划没有公开 `warning_id` 内嵌字段、产品编码、`risk_resolved` 或名称字段；`warning_id` 位于 decision 外层。
- 人工干预只有 `reason`，没有 `reason_code`、候选统计、上下文或关联机台列表。
- 切回建议只有 5 个字段，没有 `plan_id`、`cutline_start_time`、`negative_start_time`、稳定窗口、安全库存和原因字段。
- 丝网提醒没有剩余数量、小时产出、预计完成时间或清台准备时间。
- 当前接口不返回任何 `customer_display` 中文说明区块。
