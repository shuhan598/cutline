# Buffer main_id 分组计算设计

**日期：** 2026-07-23  
**状态：** 已批准，按方案 A 实施  
**范围：** Buffer 内部库存模型、SnapshotAdapter、净速率、断料、溢满、内部告警传播、测试工厂、集成场景和示例

## 1. 目标和边界

甲方继续逐条提供物理 Buffer 层实时库存。`buffer_code` 对应 Buffer 主数据
中的物理 `bufferID`，`main_id` 标识多个物理层共同参与计算的 Buffer 组。

本次目标是：

- 保留每条物理层库存及其 `buffer_code`；
- 按 `main_id + 工序区间 + order_code` 聚合订单库存；
- 同组同订单只计算一次净速率和断料时间；
- 按 `main_id` 汇总所有订单库存、增长率和物理层容量；
- 继续用确定性的代表 `buffer_code` 兼容候选、方案和活动事件；
- 不修改核心公式、下游业务规则或对外响应。

没有实时库存记录的 Buffer 主数据无法提供 `main_id` 和订单，因此不生成
NetRate、Depletion、OverflowTime 或告警结果，不使用 `buffer_code` 伪造分组。

## 2. 外部契约保持不变

Buffer 实时请求继续使用：

```text
main_id
buffer_code
bound_source_name
current_quantity
current_utilization_rate
```

职责边界：

- `main_id`：实时库存计算分组编码；
- `buffer_code`：物理 Buffer 层编码，用于查询主数据、容量和工序关系；
- `bound_source_name`：继续按当前“车间 + 订单名称”规则精确匹配订单；
- `current_quantity`：当前订单在当前物理层中的库存；
- `current_utilization_rate`：外部实时传输字段，不进入现有核心库存公式。

不要求后端预聚合，不增加外部数据集，不修改请求或响应 Schema。

## 3. 内部模型

`AlgorithmBufferOrderInventory` 增加必填 `main_id: str`，继续保留
`buffer_code`、`order_code` 和 `current_quantity`。Snapshot 中仍是一条实时
记录对应一条内部物理库存。

以下现有内部结果增加必填分组字段：

```text
main_id: str
buffer_codes: list[str]
```

- `AlgorithmIntervalNetRateResult`
- `AlgorithmDepletionTimeResult`
- `AlgorithmBufferOverflowTimeResult`
- `AlgorithmStockoutWarningResult`
- `AlgorithmOverflowWarningResult`

`buffer_codes` 始终去重、排序。现有单值 `buffer_code` 固定为
`sorted(buffer_codes)[0]`，只用于区间定位、诊断和兼容现有链路。

不新增聚合库存 Pydantic 类，也不把分组字段扩散到不参与分组计算的候选、
方案、事件或公开响应模型。

## 4. SnapshotAdapter 转换和校验

转换顺序保持为：

```text
buffer_realtime.buffer_code
→ AlgorithmBufferMaster
→ AlgorithmBufferProcessRelation
→ relation.workshop_code + bound_source_name
→ AlgorithmOrder.order_code
→ AlgorithmBufferOrderInventory
```

每条结果保留原始 `main_id` 和物理 `buffer_code`。Adapter 不聚合、不模糊
匹配、不原地修改请求。

转换期间建立三类索引：

1. `buffer_code → main_id`：同一物理层只能属于一个组；
2. `(main_id, buffer_code, order_code)`：完全重复库存记录报错；
3. `main_id → 区间上下文`：同组物理层必须具有一致的
   `workshop_code`、`upstream_process_code`、
   `downstream_process_code` 和 `loop_code`。

`main_id` 为 `None`、空串或纯空白时直接报 `SnapshotConversionError`。
冲突错误包含 `main_id`、双方 `buffer_code`、冲突字段和实际值。

## 5. 净速率集中聚合

`NetRateCalculator` 在调用现有上下游速率函数前，按以下键集中分组：

```text
(
    main_id,
    workshop_code,
    upstream_process_code,
    downstream_process_code,
    order_code,
)
```

订单继续唯一关联产品和 `wafer_size`；`wafer_spec` 继续通过当前
machine → line 推断，已有多规格冲突检查不变。

每组：

```text
aggregated_current_quantity = sum(physical current_quantity)
buffer_codes = sorted(unique physical buffer_code)
buffer_code = buffer_codes[0]
```

然后只调用一次现有上游产出和下游消耗计算：

```text
net_consumption_rate
= downstream_input_rate - upstream_output_rate
```

每个聚合组只生成一条结果，不跨物理层累加净速率。不同 `main_id` 即使区间
和订单相同也分别计算。

## 6. 断料计算

Depletion 不再自行聚合，直接消费已聚合的 NetRateResult：

```text
depletion_minutes
= aggregated_current_quantity / net_consumption_rate * 60
```

仅在净消耗率大于零时计算，其他既有边界不变。`main_id` 和排序后的
`buffer_codes` 原样传递，因此同组同订单只产生一条断料结果和最多一条告警。

## 7. 溢满计算

OverflowTime 按 `main_id` 对 NetRateResult 分组，并校验组内车间和上下游工序
一致。每个订单已经由 NetRate 聚合，因此：

```text
total_inventory = sum(each aggregated order current_quantity)
buffer_growth_rate = sum(-each order net_consumption_rate)
```

同一订单不会因多个物理层重复累计增长率。

容量来源仍是 Buffer 主数据：

```text
buffer_codes = sorted(unique codes across the main_id group)
main_capacity = sum(buffer_master[code].max_capacity for code in buffer_codes)
remaining_capacity = main_capacity - total_inventory
```

每个物理 `buffer_code` 只累计一次容量，即使它包含多个订单。

溢满时间的现有边界和公式保持不变：

- 库存已达到或超过容量：`overflow_minutes = 0`；
- 增长率大于零：`remaining_capacity / buffer_growth_rate * 60`；
- 否则：`overflow_minutes = None`。

每个 `main_id` 只生成一条 OverflowTimeResult 和最多一条告警。

## 8. 下游兼容

Stockout/Overflow Warning 复制 `main_id` 和 `buffer_codes`，内部去重键以
`main_id` 为分组身份，不再以某个物理层作为计算身份。

候选、逐台选机、切线方案和活动事件继续读取代表 `buffer_code`。Adapter 已
保证组内区间一致，且代表值固定为最小物理编码，所以它可以稳定定位共同车间
和上下游工序。候选筛选、排序、贡献产能、自动/人工决策、切回、丝网和混料
规则均不改变。

响应映射继续只输出原有 `buffer_code`，不输出 `main_id` 或 `buffer_codes`。

## 9. 测试策略

严格按红灯、最小实现、回归顺序覆盖：

- Schema 必填字段和内部传播字段；
- Adapter 保留、唯一性、非空和四项区间一致性；
- `3600 + 7200 = 10800`、代表值和排序去重；
- 同组净速率只计算一次；
- 单条断料结果/告警；
- 多订单库存和增长率；
- 物理容量去重求和；
- 单组单条溢满结果/告警；
- 不同 `main_id` 分开；
- 无实时库存无空结果；
- 候选、方案、切回、丝网、混料和公开响应回归。

共享 V3 fixture 将 `main_id` 改为与订单无关的 Buffer 组编号；同一物理
`buffer_code` 的多个订单使用同一 `main_id`。新增真实双层场景，固定
`3600 + 7200 = 10800` 并覆盖同组不同订单。

## 10. Git 约束

本次不执行 `git add`、`git commit`、`git push`、`git merge`、
`git rebase`、`git reset`、`git checkout` 或 `git switch`。只执行
`git status`、`git diff` 和 `git diff --check`。
