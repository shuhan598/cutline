# 切线算法输入输出接口规范

## 1. 文档信息

| 项目 | 当前值 |
| --- | --- |
| 文档名称 | 切线算法输入输出接口规范 |
| 适用分支 | `V5` |
| 生成基线 | Git HEAD `1c0f8ab99783a4fdfa0990783bfff545896735eb` 加当前工作区改动 |
| 生成日期 | 2026-08-15 |
| 正式接口 | `POST /cutline/evaluate` |
| Content-Type | `application/json` |
| 请求和响应编码 | UTF-8 JSON |
| 时间格式 | ISO 8601；推荐带 UTC+08:00 偏移，例如 `2026-07-17T08:00:00+08:00` |
| 时区约定 | 无时区时间按 UTC+08:00 解释；带时区时间换算为 UTC+08:00 后比较 |
| 调用频率 | HTTP 契约未强制规定。内部默认参数含 5 分钟调度周期，仅可作为业务建议，须由后端与项目方确认。 |

本规范以当前磁盘中的 `CutlineAlgorithmRequest`、`CutlineEvaluateResponse`、Loader、完整性校验器、SnapshotAdapter、ResponseMapper 和通过测试的 V3 场景为准。请求和响应模型均禁止未知字段。

标准输入中的人员可读业务值可使用中文，例如 `trigger_type="手动触发"`、`cache_type="工序缓存"`、`buffer_type="工序"`。工序名称必须使用第 4.2 节的 12 个规范名称，例如 `process_name="POLY"`；机台、订单、产品、车间、Buffer 编码，硅片规格以及 `PENDING`、`stockout` 等程序枚举保持真实契约值，不做中文翻译。

> 当前工作区包含正式接口完整性校验的未提交改动；本规范描述的是该工作区实际执行的 `/cutline/evaluate`，而不是仅描述上述 Git HEAD 的历史快照。

## 2. 正式接口与处理链路

```text
后端 JSON
  -> BackendRequestLoader（仅映射 AGV 原始字段）
  -> BackendRequestCompletenessValidator（完整性和关联关系）
  -> SnapshotAdapter（生成 AlgorithmSnapshot）
  -> CutlinePipeline（预警、方案、Pending、Active、切回、混料、丝网）
  -> AlgorithmResponseMapper
  -> HTTP Response
```

算法所有结果只返回给后端：

```text
算法服务 -> 后端 -> 后端持久化/编排 -> 前端展示给甲方
```

前端不直接调用算法，也不应把技术错误原样展示给甲方。

## 3. 输入总体结构

| 顶层字段 | 类型 | 必填 | 可为空数组 | 数据来源/用途 |
| --- | --- | :---: | :---: | --- |
| `snapshot_meta` | object | 是 | 否 | 本轮快照、版本和触发信息 |
| `machine_realtime` | array | 是 | 否 | P166 实时机台状态和 30 分钟产量 |
| `machine_master` | array | 是 | 否 | 标准机台、P166 映射和工序 |
| `machine_process_times` | array | 是 | 否 | 机台-产品工艺秒数和产能 |
| `workshops` | array | 是 | 否 | 车间目录 |
| `lines` | array | 否，默认 `[]` | 是 | 兼容产线数据；核心算法不依赖 |
| `machine_lines` | array | 否，默认 `[]` | 是 | 兼容机台-产线关系；核心算法不依赖 |
| `orders` | array | 是 | 否 | 生产订单 |
| `products` | array | 是 | 否 | 产品目录 |
| `process_routes` | array | 是 | 否 | 按车间组织的完整工艺路线；内部循环由名称生成 |
| `buffer_realtime` | array | 是 | 否 | Buffer 实时库存 |
| `buffer_master` | array | 是 | 否 | Buffer 容量、服务工序及兼容循环描述 |
| `agv_relations` | array | 是 | 取决于运行机台 | AGV 当前/历史定线绑定 |
| `pending_cutline_plans` | array | 否，默认 `[]` | 是 | 后端持久化的待确认方案 |
| `active_cutline_events` | array | 否，默认 `[]` | 是 | 后端持久化的活动切线事件 |
| `return_suggested_event_ids` | array | 否，默认 `[]` | 是 | 已发送切回建议的事件幂等水位 |
| `mixed_cutline_event_ids` | array | 否，默认 `[]` | 是 | 已生成混料记录的事件幂等水位 |

完整性校验要求以下数据集非空：`machine_realtime`、`machine_master`、`machine_process_times`、`workshops`、`orders`、`products`、`process_routes`、`buffer_realtime`、`buffer_master`。`agv_relations` 在 Pydantic 层是必填数组；每台运行机台还必须有快照时刻有效的 AGV 绑定。

## 4. 输入数据字典

### 4.1 快照、机台和目录

| 字段路径 | 类型 | 必填 | 默认/可空 | 说明 |
| --- | --- | :---: | --- | --- |
| `snapshot_meta.run_id` | string | 是 | - | 本次运行编号 |
| `snapshot_meta.trigger_type` | string | 是 | - | 触发方式 |
| `snapshot_meta.workshop_id` | string | 是 | - | 当前请求车间编号 |
| `snapshot_meta.snapshot_time` | datetime | 是 | - | 本轮算法快照时间 |
| `snapshot_meta.params_version` | integer | 是 | - | 算法参数版本 |
| `snapshot_meta.catalog_version` | string | 是 | - | 静态目录版本 |
| `snapshot_meta.catalog_loaded_at` | datetime | 是 | - | 目录加载时间 |
| `snapshot_meta.degraded_flags` | string array | 是 | 可空数组 | 数据降级诊断标记 |
| `machine_realtime[].machine_code` | string | 是 | - | P166 集团编码，匹配 `machine_master[].p166_jt_group` |
| `machine_realtime[].status` | string | 是 | - | 机台状态；`运行`/`running` 会被视为运行态 |
| `machine_realtime[].tangent_time` | datetime/null | 是 | 可为 `null` | 最近切线时间 |
| `machine_realtime[].input_quantity` | number >= 0 | 是 | - | 当前 30 分钟上料数量 |
| `machine_realtime[].output_quantity` | number >= 0 | 是 | - | 当前 30 分钟出料数量 |
| `machine_realtime[].out_time` | datetime/null | 是 | 可为 `null` | 运行态出料时间 |
| `machine_master[].machine_code` | string | 是 | - | 标准机台编码；AGV `equipmentid` 必须匹配它 |
| `machine_master[].p166_jt_group` | string | 是 | - | P166 实时编码；实时机台必须匹配它 |
| `machine_master[].machine_name` | string | 是 | - | 标准机台名称 |
| `machine_master[].process_code` | string | 是 | - | 机台所属工序编码 |
| `machine_master[].process_name` | string | 是 | - | 机台所属工序名称 |
| `machine_process_times[].machine_code` | string | 是 | - | 标准机台编码 |
| `machine_process_times[].machine_name` | string | 是 | - | 机台名称 |
| `machine_process_times[].product_code` | string | 是 | - | 产品编码 |
| `machine_process_times[].product_name` | string | 是 | - | 产品名称 |
| `machine_process_times[].proc_seconds` | number >= 0 | 是 | - | 工艺时间，单位秒 |
| `machine_process_times[].actual_capacity` | number > 0 | 是 | - | 实际产能 |
| `workshops[].workshop_code` | string | 是 | - | 车间编码 |
| `workshops[].workshop_name` | string/null | 是 | Schema 可空，完整性校验不允许 `null` | 车间名称 |
| `lines[].line_code` | string | 条目存在时是 | - | 产线编码 |
| `lines[].line_name` | string | 条目存在时是 | - | 产线名称 |
| `lines[].wafer_spec` | string | 条目存在时是 | - | 兼容保留的产线规格，不是机台实际规格来源 |
| `lines[].workshop_code` | string | 条目存在时是 | - | 兼容保留的产线车间，不是机台车间权威来源 |
| `lines[].workshop_name` | string | 条目存在时是 | - | 产线车间名称 |
| `machine_lines[].machine_code` | string | 条目存在时是 | - | 标准机台编码 |
| `machine_lines[].machine_name` | string | 条目存在时是 | - | 机台名称 |
| `machine_lines[].line_code` | string | 条目存在时是 | - | 产线编码 |
| `machine_lines[].line_name` | string | 条目存在时是 | - | 产线名称 |
| `machine_lines[].wafer_spec` | string | 条目存在时是 | - | 关联产线规格 |

`lines` 与 `machine_lines` 是兼容数据。当前 SnapshotAdapter 在 `machine_lines` 非空而 `lines` 为空时会抛出 `SnapshotConversionError`；两者均为空是允许的。

### 4.2 订单、产品、路线与 Buffer

| 字段路径 | 类型 | 必填 | 默认/可空 | 说明 |
| --- | --- | :---: | --- | --- |
| `orders[].order_code` | string | 是 | - | 订单编码，唯一 |
| `orders[].order_status` | string | 是 | - | `生产中`、`running`、`open` 是当前订单状态 |
| `orders[].total_quantity` | number >= 0 | 是 | - | 计划总数量 |
| `orders[].piece_source` | string | 是 | - | 订单片源 |
| `orders[].estimated_yield` | string | 是 | - | 预计良率，保持后端字符串格式 |
| `orders[].product_code` | string | 是 | - | 产品编码，匹配产品目录 |
| `orders[].product_name` | string | 是 | - | 产品名称，必须与产品目录一致；当前订单中唯一 |
| `orders[].workshop_code` | string | 是 | - | 订单车间，匹配车间目录 |
| `orders[].workshop_name` | string | 是 | - | 订单车间名称 |
| `orders[].produced_quantity` | number >= 0 | 是 | - | 已产数量；不得大于总数量 |
| `orders[].remaining_quantity` | number >= 0 | 是 | - | 后端提供的剩余数量；内部订单未产量按 `total_quantity - produced_quantity` 计算 |
| `products[].product_code` | string | 是 | - | 产品编码，唯一 |
| `products[].product_name` | string | 是 | - | 产品名称，唯一 |
| `products[].wafer_size` | string | 是 | - | 硅片尺寸，例如 `182`、`210` |
| `products[].source_grade` | string | 是 | - | 片源等级；当前兼容等级仅识别 `A-`、`A` |
| `products[].material_code` | string | 是 | - | 物料编码 |
| `products[].material_name` | string | 是 | - | 物料名称 |
| `process_routes[].process_code` | string | 是 | - | 工序编码 |
| `process_routes[].process_name` | string | 是 | - | 用于识别内部循环；只接受下方 12 个规范名称 |
| `process_routes[].sequence` | integer >= 1 | 是 | - | 后端权威路线顺序；同 workshop 唯一，车间最小值不必等于 1，也不要求连续 |
| `process_routes[].cache_type` | string | 是 | - | 下料缓存类型 |
| `process_routes[].workshop_code` | string | 是 | - | 路线车间，也是机台车间的权威来源 |
| `process_routes[].workshop_name` | string | 是 | - | 路线车间名称 |
| `process_routes[].loop_code` | string/null | 否 | `null` | 可选兼容字段；即使传旧值或错误值也会被忽略 |
| `process_routes[].loop_name` | string/null | 否 | `null` | 可选兼容字段；内部值与 `loop_code` 一同按名称重建 |
| `process_routes[].upstream_process_code` | string/null | 是 | 首工序为 `null` | 上游编码 |
| `process_routes[].upstream_process_name` | string/null | 是 | 首工序为 `null` | 上游名称 |
| `process_routes[].downstream_process_code` | string/null | 是 | 末工序为 `null` | 下游编码 |
| `process_routes[].downstream_process_name` | string/null | 是 | 末工序为 `null` | 下游名称 |
| `buffer_realtime[].main_id` | string/null | 是 | Schema 可空，完整性校验不允许 `null` | 参与共同计算的库存主记录分组编码 |
| `buffer_realtime[].buffer_code` | string | 是 | - | 物理 Buffer 编码 |
| `buffer_realtime[].bound_source_name` | string | 是 | - | 当前绑定产品名称，精确匹配当前订单 `product_name` |
| `buffer_realtime[].current_quantity` | number >= 0 | 是 | - | 当前库存数量 |
| `buffer_realtime[].current_utilization_rate` | number >= 0 | 是 | - | 当前占用率 |
| `buffer_master[].buffer_code` | string | 是 | - | Buffer 编码 |
| `buffer_master[].buffer_name` | string | 是 | - | Buffer 名称 |
| `buffer_master[].buffer_type` | string | 是 | - | Buffer 类型 |
| `buffer_master[].buffer_type_title` | string | 是 | - | Buffer 类型名称 |
| `buffer_master[].max_capacity` | number > 0 | 是 | - | 最大容量 |
| `buffer_master[].safety_low` | number >= 0 | 是 | - | 安全下限 |
| `buffer_master[].served_process_codes` | string array | 是 | Loader Schema 至少 1 项；算法运行时必须正好 2 个可解析工序 | 数组顺序不代表上下游；按 route sequence 定向 |
| `buffer_master[].served_process_names` | string array | 是 | Loader Schema 至少 1 项；须与 codes 等长 | 服务工序名称，不参与区间方向判断 |
| `buffer_master[].loop_code` | string | 是 | - | 兼容/描述字段，不参与服务工序判断或区间定向 |
| `buffer_master[].loop_name` | string | 是 | - | 兼容/描述字段，不参与服务工序判断或区间定向 |

`process_name` 内部映射严格如下；目录不包含 `sequence`：

| 规范工序名称 | 内部 `loop_code` | 内部 `loop_name` |
| --- | --- | --- |
| 发料机 | `LOOP1` | 一循环 |
| 制绒、硼扩、氧化 | `LOOP2` | 二循环 |
| 碱抛、`POLY`、退火 | `LOOP3` | 三循环 |
| `RCA` | `LOOP4` | 四循环 |
| `ALD`、正膜、背膜、丝网 | `LOOP5` | 五循环 |

名称统一先 trim。中文只做精确匹配；仅 `POLY`、`RCA`、`ALD` 大小写兼容。未知名称
按现有错误体系报告 `process_code`、原始 `process_name` 和无法识别所属循环的原因，不
提供其他别名或模糊匹配。`process_code` 始终是工序关联主键。

### 4.3 AGV 原始字段与 Loader 映射

标准示例使用后端原始 AGV 字段。Loader 不改变其他数据集，只深拷贝请求并执行下表映射。

| 后端原始字段 | Loader 后字段 | AlgorithmSnapshot 内部字段 | 含义 |
| --- | --- | --- | --- |
| `agv_relations[].equipmentid` | `machine_code` | `agv_relations[].machine_code` | 标准机台编码，匹配 `machine_master.machine_code` |
| `agv_relations[].equipmentname` | `machine_name` | `agv_relations[].machine_name` | 必须与静态机台名称一致 |
| `agv_relations[].linename` | `product_name` | `agv_relations[].product_name`，并解析出 `order_code`、`product_code` | 当前产品名称，精确匹配当前订单和产品目录 |
| `agv_relations[].lastlinename` | `previous_product_name` | `agv_relations[].previous_product_name`，并解析出上一产品编码 | 上一次产品名称；可为 `null` 或空字符串 |
| `agv_relations[].waferspec` | `wafer_spec` | `agv_relations[].wafer_spec` | 当前定线硅片规格，不能为空 |
| `agv_relations[].createtime` | `binding_time` | `agv_relations[].binding_time` | AGV 绑定记录时间 |

同一条 AGV 记录同时传原始字段和标准字段时，值必须一致，否则 Loader 返回 422。对每台机台，算法只选取 `binding_time <= snapshot_time` 的最新有效时间；同一最新时刻多条记录的机台名称、产品、规格或上次产品冲突会导致 Snapshot 转换失败。

### 4.4 Pending、Active 和幂等水位

| 字段路径 | 类型 | 必填 | 默认/可空 | 说明 |
| --- | --- | :---: | --- | --- |
| `pending_cutline_plans[].plan_id` / `warning_id` | string | 是 | - | 非空唯一标识 |
| `pending_cutline_plans[].warning_type` | `stockout`/`overflow` | 是 | - | 预警方向 |
| `pending_cutline_plans[].warning_time` / `created_at` / `expire_at` | datetime | 是 | - | 创建时间必须早于失效时间，预警时间不得晚于创建时间 |
| `pending_cutline_plans[].status` | enum | 是 | - | `PENDING`、`PARTIALLY_CONFIRMED`、`CONFIRMED`、`EXPIRED`、`RETURN_SUGGESTED` |
| `pending_cutline_plans[].workshop_code` / `buffer_code` | string | 是 | - | Pending 业务范围 |
| `pending_cutline_plans[].upstream_process_code` / `downstream_process_code` | string | 是 | - | 监测区间 |
| `pending_cutline_plans[].monitored_order_code` | string | 是 | - | 被监测订单 |
| `pending_cutline_plans[].process_code` | string/null | 否 | `null` | 候选机台工序 |
| `pending_cutline_plans[].source_order_code` / `target_order_code` | string/null | 否 | `null` | 方案源、目标订单 |
| `pending_cutline_plans[].source_product_code` / `target_product_code` | string/null | 否 | `null` | 方案源、目标产品 |
| `pending_cutline_plans[].before_machine_count` | integer >= 0 | 是 | - | 方案前监测机台数 |
| `pending_cutline_plans[].before_machine_codes` | string array | 是 | - | 方案前机台集合 |
| `pending_cutline_plans[].expected_machine_count` | integer >= 0 | 是 | - | 方案后预期机台数，必须与前值有非零差值 |
| `pending_cutline_plans[].expected_delta_direction` | `increase`/`decrease` | 是 | - | 预期变化方向 |
| `pending_cutline_plans[].candidate_machines` | object array | 否 | `[]` | 候选机台完整快照 |
| `pending_cutline_plans[].candidate_machine_codes` | string array | 否 | `[]` | 必须与 `candidate_machines[].machine_code` 完全一致 |
| `pending_cutline_plans[].baseline_machine_bindings` | object array | 否 | `[]` | 创建 Pending 时的 AGV 基线 |
| `pending_cutline_plans[].confirmed_machine_codes` | string array | 否 | `[]` | 已确认切线机台；数量必须符合状态和期望差值 |
| `candidate_machines[].machine_code` | string | 是 | - | 候选机台 |
| `candidate_machines[].baseline_*` | string | 是 | - | 候选机台切线前订单、产品、尺寸、规格和等级 |
| `candidate_machines[].expected_target_*` | string | 是 | - | 预期支援目标订单、产品、尺寸、规格和等级 |
| `candidate_machines[].process_code` / `workshop_code` | string | 是 | - | 候选范围 |
| `candidate_machines[].source_buffer_code` | string/null | 否 | `null` | 原订单 Buffer |
| `candidate_machines[].target_buffer_code` | string | 是 | - | 目标 Buffer |
| `candidate_machines[].target_upstream_process_code` / `target_downstream_process_code` | string | 是 | - | 目标区间 |
| `baseline_machine_bindings[].machine_code` / `order_code` / `product_code` / `product_name` | string | 是 | - | 基线机台与订单/产品 |
| `baseline_machine_bindings[].wafer_size` / `wafer_spec` / `source_grade` | string | 是 | - | 基线兼容属性 |
| `baseline_machine_bindings[].process_code` / `workshop_code` | string | 是 | - | 基线位置 |
| `baseline_machine_bindings[].machine_status` | string/null | 否 | `null` | 基线状态 |
| `baseline_machine_bindings[].observed_at` | datetime | 是 | - | 基线 AGV 观察时间；也接受别名 `agv_record_time` |
| `active_cutline_events[].event_id` | string | 是 | - | Active 事件唯一标识 |
| `active_cutline_events[].plan_id` / `warning_id` | string/null | 否 | `null` | 来源 Pending/预警；非空时不可空白 |
| `active_cutline_events[].machine_code` / `source_order_code` / `target_order_code` | string | 是 | - | 借用机台和切线前后订单 |
| `active_cutline_events[].workshop_code` | string | 是 | - | 事件车间 |
| `active_cutline_events[].source_buffer_code` | string/null | 否 | `null` | 原订单借出 Buffer |
| `active_cutline_events[].target_buffer_code` | string | 是 | - | 切回监测 Buffer |
| `active_cutline_events[].upstream_process_code` / `downstream_process_code` | string | 是 | - | 切回监测区间 |
| `active_cutline_events[].source_wafer_size` / `source_wafer_spec` | string/null | 否 | `null` | 源订单规格 |
| `active_cutline_events[].target_wafer_size` / `target_wafer_spec` | string | 是 | - | 目标订单规格 |
| `active_cutline_events[].cutline_start_time` | datetime | 是 | - | AGV 首次观察到绑定变化的时间，不等于精确物理切线时间 |
| `active_cutline_events[].negative_start_time` | datetime/null | 是 | 可为 `null` | 目标区间净消耗为负的连续起点 |
| `active_cutline_events[].status` | enum | 否 | `active` | `active`、`return_recommended`、`returned`、`cancelled` |
| `active_cutline_events[].contribution_capacity` | number/null >= 0 | 否 | `null` | 已确认切线贡献/减少的小时产能 |
| `active_cutline_events[].warning_type` | `stockout`/`overflow`/null | 否 | `null` | 来源预警类型 |
| `active_cutline_events[].process_code` | string/null | 否 | `null` | 确认机台输出侧工序 |
| `active_cutline_events[].warning_buffer_code` / `warning_upstream_process_code` / `warning_downstream_process_code` | string/null | 否 | `null` | 原预警范围 |
| `active_cutline_events[].is_recommended_candidate` | boolean/null | 否 | `null` | 是否来自原候选列表 |
| `return_suggested_event_ids` | string array | 否 | `[]` | 已发送切回建议的事件 ID；不得空白或重复 |
| `mixed_cutline_event_ids` | string array | 否 | `[]` | 已成功生成混料记录的事件 ID；不得空白或重复 |

`input_quantity` 和 `output_quantity` 是当前算法实际使用的机台实时数量。代码将两者按“最近 30 分钟数量”解释，并在净速率、候选机台贡献产能及丝网输出速率等计算中乘以 2 换算为小时速率。本次字段清理不改变该统计窗口和换算公式；后端与甲方必须确认真实数据源确实提供同一 30 分钟窗口，否则算法速率口径会与现场数据不一致。

## 5. 输入关联关系和工艺路线规则

### 5.1 必须成立的关联关系

| 来源字段 | 目标字段/规则 |
| --- | --- |
| `machine_realtime.machine_code` | 精确匹配 `machine_master.p166_jt_group`，一对一映射到标准 `machine_code` |
| `agv_relations.equipmentid` | Loader 映射后精确匹配 `machine_master.machine_code` |
| `agv_relations.equipmentname` | 必须等于静态 `machine_master.machine_name` |
| `agv_relations.linename` | 精确匹配产品目录名称，并且必须找到唯一的当前订单（状态为 `生产中`、`running` 或 `open`） |
| `orders.product_code` | 匹配 `products.product_code`；订单 `product_name` 必须等于对应产品名称 |
| `orders.workshop_code` | 匹配 `workshops.workshop_code` |
| `machine_process_times` | 机台、机台名称、产品编码、产品名称均须与目录一致 |
| `buffer_realtime.buffer_code` | 匹配 `buffer_master.buffer_code` |
| `buffer_realtime.bound_source_name` | 精确匹配唯一当前订单的 `product_name`，并通过该订单得到库存的 `order_code` |
| 机台所属车间 | 由 `machine_master.process_code` 在工艺路线中解析；产线和机台产线关系不是权威来源 |
| Buffer 上下游 | `buffer_master.served_process_codes` 的两个编码在同一 workshop 完整路线中唯一解析，并按 route `sequence` 规范化为上游/下游；输入数组顺序不具权威性 |
| Pending/Active | 所有机台、订单、产品、车间、Buffer、工序引用都必须存在且在相同业务范围；已确认 Pending 必须有匹配 Active 事件 |

产品兼容性中，`wafer_size` 来自产品目录，`wafer_spec` 来自 AGV 当前绑定；二者不是同一字段。规格默认要求相等；当前仅在 `S2`、非精确名称 `丝网` 工序时允许 `R` 与 `P` 互换。片源等级当前仅识别 `A-`、`A`，且当前等级不得低于目标等级。

### 5.2 工艺路线完整性规则

路线按 `workshop_code` 分组，正式接口执行下列规则：

1. `sequence` 完全采用后端输入，每项为正整数且在 workshop 内唯一、可排序；不写死顺序，车间最小值不必等于 1，也不要求连续。
2. 严格按 `sequence` 串行。首工序的上游编码和名称必须为 `null`；末工序的下游编码和名称必须为 `null`。
3. 任意相邻两道路线节点必须双向衔接：前一道的下游代码/名称等于后一道的 `process_code`/`process_name`，后一道的上游字段反向相等；这些引用可以跨内部循环。
4. 每个 workshop 的完整路线必须且只能存在一个 trim 后精确 `process_name == "丝网"` 的工序；不会对每个循环分别要求丝网，`丝网01`、`丝网印刷` 也不等价。
5. 该唯一 `丝网` 的 `sequence` 必须是 workshop 内最大值，即为完整车间路线的最后一道工序。
6. Buffer 的两个服务工序只要求能在同一 workshop 路线中唯一解析且 sequence 不同；可跨循环、可存在中间路线节点。解析器按 sequence 判断方向，不读取 Buffer loop，也不信任 served code 数组顺序。

典型问题代码包括 `duplicate_sequence`、`missing_silk_screen_process`、`duplicate_silk_screen_process`、`silk_screen_not_last`、`broken_process_route`、`invalid_last_process_downstream`。

## 6. 首轮与后续轮次

### 6.1 首轮

使用 [cutline_standard_input_first_round.json](../examples/cutline_standard_input_first_round.json)。它覆盖所有主要输入数据集，并显式传入：

```json
{
  "pending_cutline_plans": [],
  "active_cutline_events": [],
  "return_suggested_event_ids": [],
  "mixed_cutline_event_ids": []
}
```

该样例通过 Loader、完整性校验、SnapshotAdapter 和正式 API；实际输出见 [cutline_standard_output_stockout_plan.json](../examples/cutline_standard_output_stockout_plan.json)。

### 6.2 后续确认轮

使用 [cutline_standard_input_next_round.json](../examples/cutline_standard_input_next_round.json)。该样例回传上一轮 Pending，且 AGV 对 `EA004` 增加了创建时间之后的绑定记录；算法据此确认方案已执行，输出新 Active、`completed_pending_plan_ids` 和混料记录，见 [cutline_standard_output_pending_confirmed.json](../examples/cutline_standard_output_pending_confirmed.json)。

后端应按下表持久化和回传：

| 上一轮响应字段 | 下一轮请求字段 | 后端操作 |
| --- | --- | --- |
| `persistence_state.pending_cutline_plans` | `pending_cutline_plans` | 必须完整保存并回传；不可只保存 plan ID |
| `persistence_state.active_cutline_events` | `active_cutline_events` | 必须完整保存并回传；不要用简化的 `new_active_cutline_events` 替代 |
| `persistence_state.return_suggested_event_ids` | `return_suggested_event_ids` | 必须持久化，用于抑制重复切回建议 |
| `persistence_state.mixed_cutline_event_ids` | `mixed_cutline_event_ids` | 必须持久化，用于抑制重复混料记录 |
| `persistence_state.new_mixing_trace_records` | 无直接请求字段 | 持久化为业务记录；下一轮以 `mixed_cutline_event_ids` 作为幂等水位 |
| `persistence_state.completed_pending_plan_ids` | 无直接请求字段 | 后端更新 Pending 完成状态的审计结果 |
| `persistence_state.expired_pending_plan_ids` | 无直接请求字段 | 后端更新 Pending 过期状态的审计结果 |

**当前代码冲突，必须在联调前处理：** 请求 Schema 明确允许并要求回传非空 `return_suggested_event_ids` 和 `mixed_cutline_event_ids`，但当前 `BackendRequestCompletenessValidator._validate_empty_codes()` 把非空字符串数组元素当作 Pydantic 模型调用 `model_dump()`。因此正式 `/cutline/evaluate` 对任一非空 ID 数组会触发 `AttributeError` 并返回 HTTP 500。该问题未在本次文档任务中修改。上述两类水位的持久化语义仍是正确的；在代码修复前，不能完成其正式接口全链路回传验证。

若丢失跨轮状态，会导致 Pending 无法确认、Active 事件丢失、混料记录重复或切回建议重复。禁止接收后丢弃这些字段。

## 7. 成功响应总体结构

`POST /cutline/evaluate` 的 HTTP 200 响应为 `CutlineEvaluateResponse`：

工序循环内部化同时调整了 Request route loop 的兼容解释、workshop 级路线与丝网校验、
跨 loop 上下游引用、Buffer 按 route sequence 定向，以及 Aggregator 使用该已解析方向构造
物理键。这些调整都位于 Request/Snapshot 与区间识别边界；本节及第 8、9、10 节的
正式 Response 字段、层级、展示口径和持久化结构均不变化。

| 字段 | 类型 | 业务含义 | 后端保存 | 下一轮回传 | 甲方展示 |
| --- | --- | --- | :---: | :---: | :---: |
| `calculation_time` | datetime | 本轮计算时间 | 建议审计 | 否 | 是 |
| `stockout_warnings` | array | 断料预警 | 建议审计 | 否 | 是 |
| `overflow_warnings` | array | 溢满预警 | 建议审计 | 否 | 是 |
| `cutline_decisions` | array | 自动方案或人工干预 | 建议审计 | 方案状态由 persistence 管理 | 是 |
| `return_recommendations` | array | 切回建议 | 是 | 通过 return ID 回传 | 是 |
| `silk_screen_results` | array | 丝网清台/准备提醒 | 建议审计 | 否 | 是 |
| `mixing_trace_records` | array | 本轮混料记录 | 是 | 通过 mixed ID 回传 | 是 |
| `new_active_cutline_events` | array | 本轮新增 Active 摘要 | 是 | 使用 persistence 中完整对象 | 通常否 |
| `updated_active_cutline_events` | array | Active 计时器更新 | 是 | 合并回完整 Active 后回传 | 通常否 |
| `closed_active_cutline_event_ids` | string array | 本轮给出切回建议的事件 ID | 是 | 通过完整 Active 状态和 return ID 回传 | 可展示状态 |
| `errors` | array | 局部业务/计算诊断 | 是，日志 | 否 | 不直接展示 |
| `persistence_state` | object | 后端跨轮状态和状态更新 | **必须** | 按第 6 节映射 | 通常否 |

## 8. 输出字段详细数据字典

### 8.1 预警、方案和人工干预

| 字段路径 | 类型 | 说明 |
| --- | --- | --- |
| `stockout_warnings[].warning_id` | string | 断料预警唯一标识，格式由 Mapper 生成 |
| `stockout_warnings[].warning_type` | literal `stockout` | 预警类型 |
| `stockout_warnings[].warning_time` | datetime | 预警计算时间 |
| `stockout_warnings[].buffer_code` / `order_code` / `workshop_code` | string | 风险 Buffer、订单和车间 |
| `stockout_warnings[].wafer_size` / `wafer_spec` | string | 风险订单尺寸和规格 |
| `stockout_warnings[].upstream_process_code` / `downstream_process_code` | string | 风险区间 |
| `stockout_warnings[].current_quantity` | number >= 0 | 当前库存 |
| `stockout_warnings[].upstream_output_rate` / `downstream_input_rate` | number >= 0 | 上游出料和下游进料速率 |
| `stockout_warnings[].net_consumption_rate` | number | 净消耗速率 |
| `stockout_warnings[].depletion_minutes` | number >= 0 | 预计断料分钟数 |
| `stockout_warnings[].stockout_warning_lead_minutes` | number > 0 | 断料预警提前量 |
| `overflow_warnings[].warning_id` / `warning_type` / `warning_time` | string/literal/datetime | 溢满预警标识、类型和时间 |
| `overflow_warnings[].buffer_code` / `workshop_code` | string | 风险 Buffer 和车间 |
| `overflow_warnings[].total_inventory` / `max_capacity` / `remaining_capacity` | number | 总库存、容量、剩余容量 |
| `overflow_warnings[].buffer_growth_rate` | number | 当前库存增长速率 |
| `overflow_warnings[].overflow_minutes` / `overflow_warning_lead_minutes` | number >= 0 / > 0 | 预计溢满分钟数和提前量 |
| `cutline_decisions[].warning_id` | string | 对应预警 ID |
| `cutline_decisions[].plan` | object | 自动方案分支；与 `manual_intervention` 互斥 |
| `cutline_decisions[].manual_intervention.reason` | string | 人工处理原因，例如 `no_candidate_machine`、`insufficient_capacity` |
| `plan.plan_id` / `warning_type` / `calculation_time` | string/literal/datetime | 方案标识、方向和计算时间 |
| `plan.workshop_code` / `buffer_code` | string | 方案范围 |
| `stockout plan.order_code` / `wafer_size` / `wafer_spec` | string | 断料方案目标订单和兼容属性 |
| `stockout plan.upstream_process_code` / `downstream_process_code` | string | 断料风险区间 |
| `stockout plan.initial_capacity_gap` | number | 原始产能缺口 |
| `stockout plan.total_contribution_capacity` | number >= 0 | 选中机台补充产能合计 |
| `stockout plan.remaining_capacity_gap` | number >= 0 | 补充后的剩余缺口 |
| `overflow plan.source_order_code` / `source_wafer_size` / `source_wafer_spec` | string | 溢满方案源订单和兼容属性 |
| `overflow plan.upstream_process_code` / `downstream_process_code` | string | 溢满方案区间 |
| `overflow plan.initial_growth_rate` | number | 原始增长速率 |
| `overflow plan.total_reduced_capacity` | number >= 0 | 总减少能力 |
| `overflow plan.remaining_growth_rate` | number | 调整后增长速率 |
| `overflow plan.updated_overflow_minutes` | number/null | 调整后预计溢满分钟数 |
| `plan.selected_machines[]` | array | 已选机台。共同字段：`machine_code`、`source_order_code`、`target_order_code`、`source_buffer_code`、`target_buffer_code`、`process_code`、`workshop_code`、`wafer_size`、`source_wafer_spec`、`target_wafer_spec` |
| `stockout selected_machines[].contribution_capacity` | number >= 0 | 单机补充产能 |
| `overflow selected_machines[].reduced_capacity` | number >= 0 | 单机减少产能 |

### 8.2 切回、丝网、混料和 Active

| 字段路径 | 类型 | 说明 |
| --- | --- | --- |
| `return_recommendations[].event_id` | string | 被建议切回的 Active 事件 |
| `return_recommendations[].machine_code` | string | 建议切回机台 |
| `return_recommendations[].source_order_code` / `target_order_code` | string | 原订单和当前支援订单 |
| `return_recommendations[].return_recommended_time` | datetime | 建议产生时间 |
| `silk_screen_results[].workshop_code` / `current_order_code` | string | 丝网车间和当前订单 |
| `silk_screen_results[].machine_codes` | string array | 丝网机台 |
| `silk_screen_results[].calculation_time` | datetime | 计算时间 |
| `silk_screen_results[].silk_screen_clear_minutes` | number > 0 | 清台停机分钟数 |
| `silk_screen_results[].remaining_production_hours` | number/null >= 0 | 剩余生产小时 |
| `silk_screen_results[].prepare_clearance` | boolean | 是否进入清台准备 |
| `silk_screen_results[].reason` | enum | `not_yet_time_to_prepare`、`clearance_preparation_required`、`current_order_completed`、`current_order_capacity_unavailable` |
| `silk_screen_results[].message` | string | 可读提示文案 |
| `mixing_trace_records[].mix_trace_id` / `plan_id` / `cutline_event_id` | string | 混料、来源方案和事件标识 |
| `mixing_trace_records[].machine_code` / `workshop_code` / `process_code` / `process_name` | string | 混料位置 |
| `mixing_trace_records[].source_order_code` / `target_order_code` | string | 两侧订单 |
| `mixing_trace_records[].source_product_code` / `target_product_code` | string | 两侧产品 |
| `mixing_trace_records[].mix_start_time` | datetime | 预计混料开始时间 |
| `mixing_trace_records[].mixed_basket_start_index` / `mixed_basket_end_index` / `mixed_basket_count` | integer >= 1 | 花篮范围和数量 |
| `mixing_trace_records[].estimated_total_mixed_pieces` | integer >= 1 | 预计混料总片数 |
| `mixing_trace_records[].compositions[].order_code` / `product_code` | string | 组成订单和产品 |
| `mixing_trace_records[].compositions[].sequence` | integer >= 1 | 组成顺序 |
| `mixing_trace_records[].compositions[].estimated_pieces` | integer >= 0 | 预计片数 |
| `mixing_trace_records[].notification_status` | `scheduled`/`due` | 通知状态 |
| `new_active_cutline_events[]` | object array | 新 Active 摘要：`event_id`、`machine_code`、源/目标订单、`workshop_code`、目标 Buffer、上下游工序、目标尺寸/规格、`cutline_start_time`、`negative_start_time` |
| `updated_active_cutline_events[].event_id` | string | 被更新的 Active 事件 |
| `updated_active_cutline_events[].negative_start_time` | datetime/null | 新的连续负速率起点；明确 `null` 表示清除计时器 |
| `closed_active_cutline_event_ids` | string array | 与 `return_recommendations[].event_id` 一一对应 |

### 8.3 Persistence 和错误

| 字段路径 | 类型 | 说明 |
| --- | --- | --- |
| `persistence_state.pending_cutline_plans` | Pending array | 下一轮完整回传的权威 Pending 状态 |
| `persistence_state.active_cutline_events` | Active array | 下一轮完整回传的权威 Active 状态；字段与输入 `active_cutline_events[]` 对应 |
| `persistence_state.expired_pending_plan_ids` | string array | 本轮识别为过期的 Pending ID |
| `persistence_state.completed_pending_plan_ids` | string array | 本轮确认完成或已进入切回建议的 Pending ID |
| `persistence_state.return_suggested_event_ids` | string array | 切回建议幂等水位 |
| `persistence_state.mixed_cutline_event_ids` | string array | 混料记录幂等水位 |
| `persistence_state.new_mixing_trace_records` | Mixing array | 本轮新增、应持久化的混料记录 |
| `errors[].stage` | string | 失败阶段，例如 `pending_cutline_confirmation`、`return_evaluation`、`mixing_trace` |
| `errors[].warning_type` / `warning_key` | string/null | 关联预警类型和业务键 |
| `errors[].reason` / `message` | string | 机器可读原因和技术诊断文本 |
| `errors[].machine_code` | string | 仅 `stage="mixing_trace"` 分支存在的机台上下文 |

`persistence_state.pending_cutline_plans[]` 是完整 `PendingCutlinePlan`，字段逐项为第 4.4 节中的 `plan_id` 至 `confirmed_machine_codes`，包括候选机台和基线绑定嵌套对象。`persistence_state.active_cutline_events[]` 是完整 Active 对象，字段逐项为第 4.4 节中的 `event_id` 至 `is_recommended_candidate`。它们是下一轮的权威对象；`new_active_cutline_events[]` 仅包含展示/通知所需摘要，不能替代完整 Active 对象。

## 9. 输出字段去向矩阵

| 字段路径 | 返回后端 | 后端持久化 | 下一轮回传 | 甲方展示 | 后台日志 | 说明 |
| --- | :---: | :---: | :---: | :---: | :---: | --- |
| `calculation_time` | 是 | 建议 | 否 | 是 | 是 | 计算批次时间 |
| `stockout_warnings[]` | 是 | 建议 | 否 | 是 | 是 | 预警列表 |
| `overflow_warnings[]` | 是 | 建议 | 否 | 是 | 是 | 预警列表 |
| `cutline_decisions[].plan` | 是 | 是 | 间接 | 是 | 是 | 方案本体，Pending 才是跨轮状态 |
| `cutline_decisions[].manual_intervention` | 是 | 建议 | 否 | 是 | 是 | 正常业务结果，不是接口故障 |
| `return_recommendations[]` | 是 | 是 | 间接 | 是 | 是 | 回传 return ID 以防重复 |
| `silk_screen_results[]` | 是 | 建议 | 否 | 是 | 是 | 清台/准备提醒 |
| `mixing_trace_records[]` | 是 | 是 | 间接 | 是 | 是 | 回传 mixed ID 以防重复 |
| `new_active_cutline_events[]` | 是 | 是 | 使用完整 persistence Active | 否 | 是 | 新增事件摘要 |
| `updated_active_cutline_events[]` | 是 | 是 | 合并后回传 | 否 | 是 | 更新 Active 的负速率计时器 |
| `closed_active_cutline_event_ids[]` | 是 | 是 | 间接 | 状态 | 是 | 与切回建议一一对应 |
| `errors[]` | 是 | 是 | 否 | 否 | 是 | 诊断，不直接展示原文 |
| `persistence_state.pending_cutline_plans[]` | 是 | **必须** | **必须** | 否 | 是 | 禁止接收后丢弃 |
| `persistence_state.active_cutline_events[]` | 是 | **必须** | **必须** | 否 | 是 | 禁止接收后丢弃 |
| `persistence_state.expired_pending_plan_ids[]` | 是 | **必须** | 否 | 否 | 是 | 后端状态更新 |
| `persistence_state.completed_pending_plan_ids[]` | 是 | **必须** | 否 | 否 | 是 | 后端状态更新 |
| `persistence_state.return_suggested_event_ids[]` | 是 | **必须** | **必须** | 否 | 是 | 禁止接收后丢弃；当前有第 6.2 节阻塞问题 |
| `persistence_state.mixed_cutline_event_ids[]` | 是 | **必须** | **必须** | 否 | 是 | 禁止接收后丢弃；当前有第 6.2 节阻塞问题 |
| `persistence_state.new_mixing_trace_records[]` | 是 | **必须** | 否 | 否 | 是 | 保存明细，ID 水位负责回传 |

## 10. 甲方页面展示建议

### 10.1 预警列表

断料卡片可显示 `warning_time`、`workshop_code`、`buffer_code`、`order_code`、上下游工序、`current_quantity`、`net_consumption_rate`、`depletion_minutes`。溢满卡片可显示 `warning_time`、`workshop_code`、`buffer_code`、库存、容量、剩余容量、增长速率和 `overflow_minutes`。当前溢满响应没有订单或上下游字段；需要时由后端用本轮 Buffer 主数据关联，不可伪造为接口返回字段。

### 10.2 切线建议

展示自动方案的源/目标订单、建议机台、工序、贡献/减少产能、原始缺口或增长速率、调整后的剩余风险及建议时间。`manual_intervention.reason` 应映射为业务文案，例如“当前无可用候选机台”；原始 reason 仍保留在日志中。

### 10.3 切回建议

展示机台、原订单、当前支援订单和 `return_recommended_time`。需要显示切线开始时间时，前端/后端应按 `event_id` 关联 `persistence_state.active_cutline_events[].cutline_start_time`。当前公开切回建议没有 `reason` 字段；不要自行补造。**切回建议只表示算法建议，不表示甲方已经实际执行切回。**

### 10.4 混料追踪

展示车间、机台、工序、源/目标产品、`mix_start_time`、花篮范围、预计混料片数、组成明细和 `notification_status`。当前接口没有“预计结束时间”或独立“追踪状态”字段，不应虚构。

## 11. HTTP 状态与错误响应

| HTTP 状态 | 含义 | 后端处理 |
| --- | --- | --- |
| 200 | 正常计算；可能有方案、无预警、人工干预或局部 `errors` | 解析完整响应、持久化状态；人工干预不是接口异常 |
| 422 | 已识别的输入数据、完整性或 Snapshot 转换错误 | 不进入正常业务展示；记录问题并修复数据 |
| 500 | 未知程序异常或非预期系统错误 | 记录请求标识、时间和服务日志；不可一律归因为甲方数据问题 |

`1010`（兼容标识 `BACKEND_DATA_INVALID`）的真实格式见 [cutline_standard_error_backend_data_invalid.json](../examples/cutline_standard_error_backend_data_invalid.json)：

```json
{
  "detail": {
    "code": "1010",
    "legacy_code": "BACKEND_DATA_INVALID",
    "message": "后端数据不完整或数据关联关系错误",
    "issues": [
      {
        "code": "float_parsing",
        "error_code": "2193",
        "dataset": "orders",
        "field": "total_quantity",
        "record_key": "index:0",
        "message": "Input should be a valid number, unable to parse string as a number"
      }
    ]
  }
}
```

`1011`（兼容标识 `SNAPSHOT_CONVERSION_FAILED`）的真实格式见 [cutline_standard_error_snapshot_conversion.json](../examples/cutline_standard_error_snapshot_conversion.json)：

```json
{
  "detail": {
    "code": "1011",
    "legacy_code": "SNAPSHOT_CONVERSION_FAILED",
    "message": "machine_lines were provided but lines are empty",
    "issues": []
  }
}
```

422 常见原因包括字段类型错误、缺少必需数据集、引用关系不成立、路线不合法、运行机台缺 AGV 绑定以及 Snapshot 关系无法构造。HTTP 200 中的 `errors` 是可隔离的业务/计算分支问题，不等同于 422。

## 12. 溢满接口稳定性说明

相对稳定、可用于前端预警展示的字段为 `overflow_warnings` 中的预警标识、时间、Buffer、车间、总库存、最大容量、剩余容量、增长速率、预计溢满分钟数和预警提前量。

当前版本存在 `OverflowCutlinePlanResponse`、目标订单、目标 Buffer、选中机台、减少能力和 Pending 相关结构；由于溢满策略后续准备重新评估，这些**方案层**字段可能调整。前端和后端不得把溢满自动方案结构视为长期稳定接口；应采用版本化存档并在策略重构前确认契约。

## 13. 标准交付文件与场景

| 文件 | 场景 |
| --- | --- |
| [cutline_standard_input_first_round.json](../examples/cutline_standard_input_first_round.json) | 首轮断料风险输入，所有跨轮状态为空 |
| [cutline_standard_input_next_round.json](../examples/cutline_standard_input_next_round.json) | Pending 确认轮；AGV 出现创建后绑定变化 |
| [cutline_standard_output_no_warning.json](../examples/cutline_standard_output_no_warning.json) | 无断料/溢满/方案/切回/混料/错误；当前仍可能有丝网提示 |
| [cutline_standard_output_stockout_plan.json](../examples/cutline_standard_output_stockout_plan.json) | 断料预警、自动方案和新 Pending |
| [cutline_standard_output_pending_confirmed.json](../examples/cutline_standard_output_pending_confirmed.json) | Pending 被确认、新 Active、完成 Pending ID、混料记录 |
| [cutline_standard_output_return_recommendation.json](../examples/cutline_standard_output_return_recommendation.json) | 切回建议、关闭事件 ID、return/mixed 幂等水位 |
| [cutline_standard_output_manual_intervention.json](../examples/cutline_standard_output_manual_intervention.json) | 无候选机台的正常 HTTP 200 人工干预结果 |
| [cutline_standard_error_backend_data_invalid.json](../examples/cutline_standard_error_backend_data_invalid.json) | Pydantic 字段类型错误的 422 |
| [cutline_standard_error_snapshot_conversion.json](../examples/cutline_standard_error_snapshot_conversion.json) | `machine_lines` 与空 `lines` 冲突的 422 |
| [generate_cutline_standard_examples.py](../examples/generate_cutline_standard_examples.py) | 通过真实正式 API 可重复生成上述样例 |

## 14. 已知冲突与交付边界

除第 6.2 节所述非空 `return_suggested_event_ids`/`mixed_cutline_event_ids` 在正式接口触发 500 的冲突外，未发现本次新增样例的字段名、JSON 语法、Loader、完整性校验、Snapshot、成功响应 Schema 或 422 包络与当前代码不一致。

本次工序循环内部化包括：ProcessRoute loop Optional 与按名称重建、workshop 级路线/丝网、
跨 loop 引用、Buffer 按 route sequence 解析方向，以及 Aggregator 物理键使用该规范方向。
未修改正式 Response Schema、断料公式、溢满公式、候选机台、逐台选择、
切线方案生成核心业务逻辑、Pending 确认、Active、混料、切回、丝网输出、API 响应字段、
数据库或前端代码。
