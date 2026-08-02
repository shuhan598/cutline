# 后端字段到算法权威来源映射

本文只说明会影响算法判断的权威来源。完整请求字段定义见
`docs/backend-request-interface.md`，原始文档字段对照见
`docs/2026-07-14-algo-request-document-field-mapping.md`。

## 机台当前生产信息

| 算法语义 | 原始字段 | 标准/内部字段 | 权威来源 |
| --- | --- | --- | --- |
| 当前产品型号名称 | `agv_relations.linename` | `product_name` | 最新有效 AGV 绑定 |
| 当前订单编码 | `agv_relations.linename -> products.product_name -> orders.product_name` | `order_code` | 产品型号名称唯一匹配出的当前有效订单（`RUNNING` / `OPEN` / `生产中`） |
| 当前订单硅片规格 | `agv_relations.waferspec` | `wafer_spec` | 最新有效 AGV 绑定 |
| 机台工序 | `machine_master.process_code` | `process_code` | 机台主数据 |
| 机台所属车间 | `process_routes.workshop_code` | `workshop_code` | 机台工序对应的工艺路线 |

机台所属车间完整链路：

```text
machine_code
  -> machine_master.process_code
  -> process_routes.process_code
  -> process_routes.workshop_code
```

外部机台双编号在 Adapter 层统一：

```text
AGV.equipmentid
  -> machine_master.machine_code
  -> 内部标准 machine_code

machine_realtime.machine_code
  -> machine_master.p166_jt_group
  -> machine_master.machine_code
  -> 内部标准 machine_code
```

`lastlinename` 只记录上一产品，不参与当前订单匹配，也不能作为确认切线的唯一证据。
Buffer 的
`bound_source_name` 表示当前产品型号名称，通过唯一的 `orders.product_name` 转换为
内部 `order_code`。所有名称匹配均为安全去空格后的精确匹配。

## Pending 确认与活动事件

| 算法语义 | 权威来源 |
| --- | --- |
| 方案创建时机台绑定 | `persistence_state.pending_cutline_plans[].baseline_machine_bindings`，后端原样保存并回传 |
| 窗口内当前绑定 | `agv_relations` 中满足 `created_at < createtime <= expire_at` 且不晚于 `snapshot_time` 的记录 |
| 当前订单 | 当前记录 `linename -> products.product_name -> 当前唯一 orders.product_name -> order_code` |
| 上一产品辅助校验 | 当前记录 `lastlinename`；非空时必须与保存的 `baseline_product_name` 一致 |
| 可观察切线时刻 | 能够证明绑定变化的 AGV `createtime`；不是精确物理换型时间 |
| 活动事件机台号 | 静态标准 `machine_master.machine_code` |

Pending 的数量口径是同一预警车间、预警区间产出侧工序、现有 `running` 状态口径和
被监控订单。断料预期机台数增加，确认方向是“其他订单切入监控订单”；溢满预期机台
数减少，确认方向是“监控订单切向合法目标订单”。数量变化只是辅助信息，活动事件按
基线绑定与窗口内新绑定逐台确认。

基线输出字段为 `observed_at`，截止点是 `created_at`；旧输入名 `agv_record_time`
仅作兼容校验别名。确认窗口严格为 `created_at < createtime <= expire_at`，并且记录
不能晚于本轮 `snapshot_time`。

`baseline_machine_bindings` 必须覆盖该车间和输出侧工序内所有可观察机台，不只覆盖
推荐候选。剩余确认名额可以由满足车间、工序、精确订单映射、时间窗口和严格切换方向
的非候选机台补足；不重新附加候选机台的 wafer/source-grade 影响筛选或全局优化。
溢满目标区间只作为持久化上下文，不能用当轮 `net_consumption_rate > 0` 否认已经观察到
的合法真实切换；上下文缺失或歧义必须明确报错。首轮方案只创建 Pending，不创建 Active 或混料；
只有真实确认后才创建 Active，由 Active 触发混料并进入 Return。

本仓库没有数据库或后端状态仓库。`POST /cutline/evaluate` 在原业务字段之外返回
`persistence_state`；调用方保存其中的 `pending_cutline_plans`、
`active_cutline_events`、`return_suggested_event_ids` 和
`mixed_cutline_event_ids`，并映射回下一轮请求同名字段。兼容
`CutlineAlgorithmResponse` 本身不增加 Pending、基线、确认状态或机台数量字段。

## Active 驱动混料与切回水位

| 算法语义 | 权威来源 |
| --- | --- |
| 混料计算入口 | 已确认并成功合并、来源上下文完整的 `ActiveCutlineEvent` |
| 混料基准时间 | Active 的 `cutline_start_time`，即观察到绑定变化的 AGV `createtime` |
| 混料跨轮去重 | 请求/响应累计 `mixed_cutline_event_ids` |
| 切回判断入口 | 状态为 `active` 且尚未给过建议的真实 Active |
| 切回跨轮去重 | 请求/响应累计 `return_suggested_event_ids` 及 Active `status=return_recommended` |

两个水位互相独立。同一事件混料计算成功后只写一次水位；混料失败不推进，可在数据
修复后重试。同一机台后续产生新的事件 ID 时仍可再次生成混料。切回建议只表示算法
建议，不表示现场已经切回，也不会创建 PendingReturnPlan。

同一 `process_code` 可在不同 `loop_code` 中重复，只要 `workshop_code` 相同。
如果映射到多个不同车间，解析器按编码排序列出冲突并报错。runtime 引用机台的工序
找不到路线时同样报错，不回退产线车间。

## Buffer、预警和结果

| 算法语义 | 权威来源 |
| --- | --- |
| Buffer 所属车间和上下游区间 | Adapter 根据 Buffer 与工艺路线生成的 `buffer_process_relations` |
| 断料/溢满预警车间 | 对应 Buffer 区间结果中的 `workshop_code` |
| 候选机台车间 | `MachineWorkshopResolver` 解析结果 |
| S2 R/P 兼容判断车间 | `MachineWorkshopResolver` 解析结果 |
| 丝网分组车间 | `MachineWorkshopResolver` 解析结果 |

## 兼容保留但不是机台状态权威的数据

以下字段和集合是可选兼容数据，不再决定机台所属车间或当前规格：

- `lines`
- `machine_lines`
- `lines.workshop_code`
- `lines.wafer_spec`
- `machine_lines.wafer_spec`

其中 `lines.workshop_code` 只表示产线自身所属车间；`line.wafer_spec` 和
`machine_lines.wafer_spec` 只作为兼容字段保留。`AlgorithmMachineRuntime` 不增加
`current_wafer_spec`。

`lines` 和 `machine_lines` 均可完全省略或显式传入空数组，Schema 会补成独立的
空列表。当前净速率、断料候选、溢满候选、丝网、切回和混料核心路径均不读取这些
集合。旧请求同时提供二者时，Adapter 继续执行产线及关系引用校验；仅提供
`machine_lines` 而 `lines` 为空时明确拒绝。
