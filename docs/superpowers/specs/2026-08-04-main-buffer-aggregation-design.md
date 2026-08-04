# 断料与溢满 mainID 聚合设计

**日期：** 2026-08-04  
**状态：** 已批准，待实施  
**范围：** Buffer 内部聚合、断料与溢满计算、候选查找、逐台影响校验和既有跨轮定位  
**Git 约束：** 不执行 commit 或 push

## 1. 目标与不可变边界

断料和溢满的库存计算对象从单个 `buffer_code` 改为实时 `mainID` 对应的订单库存组。一个 `mainID` 下的多个实时 `bufferID` 分别关联静态 Buffer 的 `bufferCode/number`，库存和容量只在该 `mainID` 实际包含的有效层内汇总。

正式输入字段、输出字段、输出层级、Response Schema、Warning、Decision、Pending、Active、`persistence_state` 和后端下一轮回传协议保持不变。`main_id`、物理 Buffer 键、层编码集合及聚合值只存在于内部模型，不进入最终 Response JSON。

请求级结构错误、必需顶层数据缺失、基础类型错误和无法建立全局工艺路线的错误继续通过现有 `BACKEND_DATA_INVALID` 或 `SNAPSHOT_CONVERSION_FAILED` 返回 HTTP 422。正式 Schema 已允许承载的单个 `mainID` 局部业务异常由聚合器隔离；即使全部组失效，接口仍返回 HTTP 200、空业务结果和既有 `errors`。

## 2. 集中式聚合架构

新增集中式内部 `MainBufferAggregator`。它在 Snapshot 基础转换完成后只执行一次，产出唯一的 `MainBufferAggregationBatch`。净速率、断料、溢满、候选查找、逐台模拟和跨轮定位共享该批次，任何下游模块不得重新聚合或自行推断 `mainID` 关系。

数据流为：

```text
合法正式请求
  -> SnapshotAdapter 基础转换和全局校验
  -> MainBufferAggregator 单次聚合及局部隔离
  -> AlgorithmSnapshot 持有 MainBufferAggregationBatch
  -> Pipeline 将 batch.issues 映射为现有 AlgorithmPipelineError
  -> NetRate / Depletion / Overflow / Candidate / Selection
  -> 现有 Plan / Pending / Active / Mapper / Response
```

聚合职责放在独立模块中，不堆入 `cutline_pipeline.py`。Pipeline 只编排批次消费者和错误映射。

## 3. 内部数据结构

### 3.1 稳定键

物理 Buffer 键严格保留服务工序顺序：

```python
PhysicalBufferKey = tuple[str, tuple[str, ...]]

physical_buffer_key = (
    workshop_code,
    tuple(ordered_service_process_codes),
)
```

库存组和虚拟状态使用等价的 frozen dataclass 或以下元组：

```python
GroupKey = tuple[PhysicalBufferKey, str, str]

group_key = (
    physical_buffer_key,
    main_id,
    order_code,
)
```

`representative_buffer_code` 不参与聚合、物理 Buffer 判断、净速率、候选目标、虚拟状态或防重复。

### 3.2 MainBufferGroup

内部组至少表达：

```text
group_key
main_id
workshop_code
ordered_service_process_codes
physical_buffer_key
order_code
product_code
buffer_codes
total_inventory
total_capacity: float | None
remaining_capacity: float | None
representative_buffer_code: str | None
stockout_eligible
overflow_eligible
stockout_warning_eligible
overflow_warning_eligible
auto_receive_eligible
auto_donate_eligible
```

`buffer_codes` 为标准化、去重、稳定排序后的真实静态层编码。能够形成有效组时，代表层为排序首项；无法选出真实代表层时允许为 `None`。

### 3.3 MainBufferAggregationBatch

批次至少包含：

```text
groups
issues
groups_by_main_id
main_id_by_buffer_code
main_id_by_representative_buffer_code
main_ids_by_physical_buffer_key
```

索引冲突不得覆盖已有值，必须产生内部 issue 并关闭受影响组的相关能力。可增加按 `group_key`、`(physical_buffer_key, order_code)` 或订单/工序查找的派生索引，但不得在消费者中重新扫描原始库存并重建聚合语义。

### 3.4 聚合 Issue

内部 issue 至少包含：

```text
code
main_id
representative_buffer_code
message
affected_capabilities
```

同类 issue 按 `(issue.code, issue.main_id)` 去重。同一 `mainID` 多层发生相同问题时，`message` 汇总所有相关 `buffer_code`，避免丢失定位信息。代表层不可用时，Pipeline 使用 `main_id` 作为现有错误结构中的 `warning_key`。

Pipeline 统一映射为：

```text
stage = "main_buffer_aggregation"
warning_type = None
warning_key = main_id
reason = issue.code
message = issue.message
```

下游不得重复报告 Aggregator 已识别的同类异常；候选、选机和方案构建阶段新产生的独立错误仍按现有机制报告。

## 4. 两遍聚合与校验

### 4.1 第一遍：单个 mainID

按 `main_id` 收集实时层，并依次执行：

1. 校验实时 `bufferID` 能唯一关联静态 Buffer。
2. 获取静态层的车间、有序服务工序和容量。
3. 通过现有订单索引唯一解析 `sourceName/bound_source_name`。
4. 校验同组只对应一个订单。
5. 校验同组所有层的车间一致。
6. 校验同组所有层的有序服务工序列表完全一致。
7. 对实时 `bufferID` 去重；重复记录不累计库存并使组失效。
8. 只累加有效数字库存，数字 `0` 是有效库存。
9. 只累加该 `mainID` 实际包含的静态层容量，每层最多一次。
10. 生成稳定真实代表层和所有批次索引。

实时 `bufferID` 无法唯一关联静态 Buffer 时产生 `static_buffer_mapping_unresolved`，关闭两项计算能力及四项角色能力。此类错误不能降级为“仅容量不可用”，因为车间、服务工序和物理归属均不可信。

“仅容量不可用”必须同时满足：静态层唯一关联、车间可确定、有序服务工序可确定、订单和库存可正常聚合，只有容量值无法安全参与计算。

### 4.2 第二遍：跨 mainID 冲突

单组聚合完成后，按 `(physical_buffer_key, order_code)` 检查同一物理 Buffer 内同一订单是否占用多个 `mainID`。检测到时：

- 不合并相关组；
- 不向多个组重复分配订单净速率；
- 关闭相关组的两项计算能力及四项角色能力；
- 不生成断料或溢满预警及自动方案；
- 每个相关 `mainID` 产生一条按 `(code, main_id)` 去重的 issue；
- 每条 issue 的 `message` 列出该冲突涉及的全部 `mainID`。

## 5. 能力矩阵

| 组状态 | 断料计算 | 溢满计算 | 断料预警 | 溢满预警 | 自动接收 | 自动借出 |
|---|---:|---:|---:|---:|---:|---:|
| 库存、订单、工序、容量完整 | 是 | 是 | 是 | 是 | 是 | 是 |
| 仅容量不可用 | 是 | 否 | 是 | 否 | 否 | 是 |
| 静态 Buffer 映射不唯一或不存在 | 否 | 否 | 否 | 否 | 否 | 否 |
| 库存、订单、车间或有序工序异常 | 否 | 否 | 否 | 否 | 否 | 否 |
| 重复实时 bufferID | 否 | 否 | 否 | 否 | 否 | 否 |
| 同物理 Buffer、同订单占多个 mainID | 否 | 否 | 否 | 否 | 否 | 否 |

正式字段的可空性和类型不改变。`null`、字段缺失或非法基础类型如果已被正式 Schema 拒绝，仍属于请求级 422；不会为了局部隔离放宽正式 Schema。

## 6. 净速率、断料与溢满

`stockout_eligible` 表示组可计算净速率和耗尽时间，`overflow_eligible` 表示组可计算容量、剩余容量和溢满时间。对应 warning 能力单独保留，避免计算资格与预警/自动方案角色混用。

每个有断料计算能力的组只计算一次上下游速率，并保留现有有符号净消耗公式：

```text
inventory_change_rate
= upstream_output_rate - downstream_input_rate

net_consumption_rate
= downstream_input_rate - upstream_output_rate
= -inventory_change_rate
```

断料时间使用聚合库存：

```text
depletion_minutes
= total_inventory / net_consumption_rate * 60
```

当聚合库存小于等于零且 `net_consumption_rate > 0` 时，耗尽时间为 `0`。净消耗率不为正时无继续断料趋势。一个组最多产生一条断料预警，原提前量和触发标准不变。

只有具备溢满预警能力的组进入溢满计算：

```text
remaining_capacity = total_capacity - total_inventory
overflow_minutes = remaining_capacity / inventory_change_rate * 60
```

剩余容量小于等于零时溢满时间为 `0`，并记录库存超容量问题；变化率不为正时无继续溢满趋势。一个组最多产生一条溢满预警。

## 7. 断料候选和影响校验

内部明确区分：

- `receiver_group`：断料预警对应的接收组；
- `donor_group`：候选机台当前订单对应的借出组。

候选和逐台结果优先使用 `receiver_group_key`、`donor_group_key` 和 `donor_main_id`，不使用含义模糊的 `source_group_key`。候选过滤、排序、产品兼容、车间、工序、运行状态和 S2 P/R 规则保持不变。

候选机台的当前订单通过 `receiver_group.physical_buffer_key + donor order_code` 定位唯一 `donor_group`。借出影响使用 donor 聚合库存和变化率，不读取单层库存。

`receiver_group.auto_receive_eligible` 为假时仍生成断料预警和候选列表，但选机结果固定为风险未解决；不得跳过目标溢满影响校验。PlanBuilder 使用现有 ManualIntervention，不生成自动 CutlinePlan，也不创建 Pending。

## 8. 溢满候选和目标组

溢满来源为产生预警的 `source_group`，且必须 `auto_donate_eligible=true`。目标只从 `main_ids_by_physical_buffer_key[source.physical_buffer_key]` 查找，并满足：

- `target.main_id != source.main_id`；
- `target.order_code != source.order_code`；
- `target.auto_receive_eligible=true`；
- `target_gap_before > 0` 或现有明确缺口条件；
- 现有订单、产品、尺寸、规格、片源、S2 P/R、车间、工序和机台状态规则。

禁止从 `warning.order_growth_details` 中寻找目标订单。来源与目标库存、容量、剩余容量和速率均取共享组。

## 9. 单预警虚拟状态

每条 warning 的选机调用独立创建：

```text
virtual_groups: dict[GroupKey, VirtualGroupState]
selected_machine_codes: set[str]
```

二者不得跨 warning 或 Pipeline 共享，当前不新增多预警冲突处理。

虚拟组只保存一个有符号速率：

```text
inventory_change_rate
= upstream_output_rate - downstream_input_rate
```

`total_inventory` 和 `total_capacity` 在单轮模拟中只读。每选择一台小时产能 `R` 的机台：

```text
donor/source inventory_change_rate -= R
receiver/target inventory_change_rate += R

net_consumption_rate = max(0, -inventory_change_rate)
target_gap = max(0, -inventory_change_rate)
```

每次更新后依次验证：

1. 来源溢满风险解除或延后到安全窗口外；
2. 来源不会在断料提前量内产生新断料；
3. 目标缺口严格改善；
4. 目标不会在溢满提前量内产生新溢满；
5. 同一机台未重复选择。

选中后立即提交该 warning 局部虚拟状态，再评估下一台。不同目标组使用独立 `GroupKey`，不得互相覆盖。

## 10. 代表层与跨轮定位

`representative_buffer_code` 仅用于：

- Warning、Decision 和 SelectedMachine 的现有 `buffer_code` 字段；
- Warning ID 和 Plan ID 的兼容生成；
- Pending/Active 现有字段；
- 下一轮定位入口。

来源和目标的既有 `buffer_code` 字段分别使用对应来源组和目标组的代表层，不能统一写入 warning 的代表层，也不能用 `mainID` 冒充层编码。

跨轮定位优先通过 `main_id_by_buffer_code` 将任意真实层编码反查到 `mainID`，代表层索引只作为受约束的兼容索引。找不到或映射冲突时不得按编码前缀猜测，也不得静默选择；应阻止自动方案并使用现有错误机制。

Pending/Active、混料、切回和持久化模型不重构。只在现有定位入口做最小调整：

```text
existing buffer_code
  -> main_id_by_buffer_code
  -> groups_by_main_id
  -> shared MainBufferGroup
```

## 11. 测试策略

实施采用 TDD，测试覆盖至少包括：

- 单 main 多层库存、容量、零值、去重和稳定代表层；
- 同 main 多订单、订单解析失败、车间和有序工序冲突；
- 静态映射无法解析与仅容量不可用的能力差异；
- 同物理 Buffer 同订单跨 main 冲突的第二遍校验；
- issue 聚合、相关层编码汇总和 `(code, main_id)` 去重；
- 每组上下游速率只计算一次；
- 单组最多一条断料或溢满预警；
- 缺容量组仍产生断料预警和候选，但固定人工且无 Pending；
- donor 聚合库存影响校验；
- 溢满目标来自同物理 Buffer 的其他 main，而非 warning 明细；
- 有序工序不同、相同 main、相同订单和无接收能力目标被排除；
- 多机逐台累计、只读库存容量、局部虚拟状态和机台防重；
- 来源、目标输出各自使用正确代表层；
- 任意真实层跨轮反查 mainID，冲突时不猜测；
- 单层旧场景、候选兼容、S2 P/R、Pending、Active、混料和切回回归；
- 正式响应顶层、Warning、Decision、Pending、Active 和 persistence 字段集快照不变；
- OpenAPI Response Schema、Mapper 和 API 层级不变。

完成后按目标模块、断料、溢满、Pipeline、API、完整 `pytest -q` 的顺序验证，并执行 `git diff --check`、`git status --short`、`git diff --stat` 及正式输出相关路径的定向 diff。

## 12. 非目标

- 不处理同一订单在同一物理 Buffer 占用多个 `mainID` 的自动合并；
- 不增加多预警之间的机台冲突协调；
- 不重构 Pending、Active、混料、切回或 PersistenceStateBuilder；
- 不改变正式请求字段、字段类型、可空性或正式输出结构；
- 不执行 commit 或 push。
