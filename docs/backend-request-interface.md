# 切线算法输入接口文档

> 更新时间：2026-08-15
>
> 本文档描述后端传给算法服务的请求 JSON。主闭环路由为
> `POST /cutline/evaluate`，兼容业务路由为 `POST /stub/algo/run`；预校验路由为
> `POST /backend/validate`。

## 1. 输入 JSON 是哪一块

算法标准请求对象是：

```python
app.schemas.request_schema.CutlineAlgorithmRequest
```

HTTP 请求先以 JSON 对象进入 `BackendRequestLoader`，其中 AGV 原始六字段会被统一
映射为算法标准六字段，再校验为 `CutlineAlgorithmRequest`。因此正式计算接口可直接
接收甲方原始 AGV 字段，不会在映射前按标准字段返回 422。

两个计算路由接收同一请求，但响应用途不同：

```http
POST /cutline/evaluate
Content-Type: application/json
```

请求体：

```text
CutlineAlgorithmRequest
```

主闭环响应体：

```text
CutlineEvaluateResponse
  = CutlineAlgorithmResponse 原有业务字段
  + persistence_state
```

`POST /stub/algo/run` 仍按原 `CutlineAlgorithmResponse` 输出，不包含
`persistence_state`，用于兼容只消费业务字段的调用方。需要 Pending、Active、混料和
切回跨轮闭环时必须使用 `/cutline/evaluate`。工序循环内部化只调整 Request 的解释：
正式 Response 的字段、层级和业务语义均不变化。

当前可参考输入样例：

- 省略产线兼容字段的标准样例：`examples/backend_request_standard.json`
- 显式传空产线数组的简单样例：`examples/backend_request_sample.json`
- 完整断料出方案样例：`examples/backend_request_stockout_plan_sample.json`

## 2. 请求顶层结构

```json
{
  "snapshot_meta": {},
  "machine_realtime": [],
  "machine_master": [],
  "machine_process_times": [],
  "workshops": [],
  "lines": [],
  "machine_lines": [],
  "orders": [],
  "products": [],
  "process_routes": [],
  "buffer_realtime": [],
  "buffer_master": [],
  "agv_relations": [],
  "pending_cutline_plans": [],
  "active_cutline_events": [],
  "return_suggested_event_ids": [],
  "mixed_cutline_event_ids": []
}
```

请求中不要传 `config`。算法参数由内部默认配置 `AlgorithmConfig` 注入。
上例显式写出 `lines: []` 和 `machine_lines: []`；也可以完全省略这两个键。

| 字段 | 类型 | 是否必填 | 含义 |
|---|---|---|---|
| `snapshot_meta` | object | 是 | 本次快照上下文 |
| `machine_realtime` | array | 是 | 机台实时运行数据 |
| `machine_master` | array | 是 | 机台主数据和工序归属 |
| `machine_process_times` | array | 是 | 机台-产品工艺时间和产能 |
| `workshops` | array | 是 | 车间基础数据 |
| `lines` | array | 否，默认空数组 | 可选兼容产线和硅片规格 |
| `machine_lines` | array | 否，默认空数组 | 可选兼容机台与产线关系 |
| `orders` | array | 是 | 订单基础和数量数据 |
| `products` | array | 是 | 产品型号基础数据 |
| `process_routes` | array | 是 | 工艺路线 |
| `buffer_realtime` | array | 是 | Buffer 实时库存 |
| `buffer_master` | array | 是 | Buffer 主数据 |
| `agv_relations` | array | 是 | AGV 机台当前订单绑定历史 |
| `pending_cutline_plans` | array | 否，默认空数组 | 后端持久化并跨轮回传的待执行切线方案 |
| `active_cutline_events` | array | 否，默认空数组 | 后端回传的活动切线跟踪事件 |
| `return_suggested_event_ids` | array | 否，默认空数组 | 已输出过切回建议的累计事件 ID 水位 |
| `mixed_cutline_event_ids` | array | 否，默认空数组 | 已成功生成真实混料记录的累计事件 ID 水位 |

两个水位数组都拒绝空字符串和重复 ID。它们分别防止切回建议和混料记录跨轮重复，
彼此独立，不能用其中一个代替另一个。

## 3. 快照信息 `snapshot_meta`

```json
{
  "run_id": "RUN-STOCKOUT-PLAN-001",
  "trigger_type": "manual_test",
  "workshop_id": "WS-S1",
  "snapshot_time": "2026-07-16T08:30:00+08:00",
  "params_version": 1,
  "catalog_version": "FAKE-CATALOG-001",
  "catalog_loaded_at": "2026-07-16T08:00:00+08:00",
  "degraded_flags": []
}
```

`snapshot_time` 是算法本轮计算时间，输出中的 `calculation_time` 会使用该时间。

## 4. 机台实时数据 `machine_realtime`

```json
{
  "machine_code": "P166-ZR-02",
  "status": "运行",
  "tangent_time": null,
  "input_quantity": 300.0,
  "output_quantity": 300.0,
  "out_time": "2026-07-16T08:25:00+08:00"
}
```

关键规则：

- `machine_code` 是 P166 集团机台编号，必须唯一匹配
  `machine_master.p166_jt_group`；进入 Snapshot 后统一转换为静态标准
  `machine_master.machine_code`。
- `status` 只有“运行”或大小写不同的 `running` 会进入算法映射为 `running`。
- 其它状态，包括“停机”“异常”“待机”等，统一映射为 `stopped`，算法不会调用这些机台。
- `machine_realtime` 不再提供 `order_code`；当前订单由快照时刻的有效 AGV 绑定提供。
- `input_quantity` 和 `output_quantity` 是当前 30 分钟数量，算法会乘以 2 折算小时速率。
- 当前算法只使用 `input_quantity` 和 `output_quantity` 作为机台实时数量；后端与甲方必须确认真实接口的统计窗口确为最近 30 分钟。
- `tangent_time`、`out_time` 没有值时传 `null`。

## 5. 机台主数据 `machine_master`

```json
{
  "machine_code": "ZR-02",
  "p166_jt_group": "P166-ZR-02",
  "machine_name": "制绒二号",
  "process_code": "P-ZR",
  "process_name": "制绒"
}
```

`machine_code` 对应 AGV `equipmentid`，是核心算法内部唯一使用的标准编号；
`p166_jt_group` 对应 `machine_realtime.machine_code`。两个字段都必须非空且各自唯一，
共同表示同一物理机台。`process_code` 是算法判断机台所属工序的核心字段。

## 6. 机台工艺时间和产能 `machine_process_times`

```json
{
  "machine_code": "ZR-02",
  "machine_name": "制绒二号",
  "product_code": "PROD-T",
  "product_name": "HG182T",
  "proc_seconds": 120.0,
  "actual_capacity": 600.0
}
```

用途：

- `machine_code` 已经使用静态标准 `machine_master.machine_code`，不执行 P166 二次转换。
- `proc_seconds` 用于混料追溯计算。
- `actual_capacity` 当前作为机台-产品能力数据保留；主链净速率目前按实时 30 分钟数量折算。

## 7. 车间、产线和机台产线关系

### `workshops`

```json
{
  "workshop_code": "WS-S1",
  "workshop_name": "S1测试车间"
}
```

### `lines`

```json
{
  "line_code": "LINE-N",
  "line_name": "N型测试线",
  "wafer_spec": "N",
  "workshop_code": "WS-S1",
  "workshop_name": "S1测试车间"
}
```

`wafer_spec` 当前只允许 `N`、`R`、`P`。

### `machine_lines`

```json
{
  "machine_code": "ZR-02",
  "machine_name": "制绒二号",
  "line_code": "LINE-N",
  "line_name": "N型测试线",
  "wafer_spec": "N"
}
```

规则：

- `lines` 和 `machine_lines` 是可选兼容数据，当前核心算法不依赖产线。
- 两者都省略或都传空数组时正常运行，不生成虚拟产线或占位关系。
- 只提供 `lines` 时正常运行，不要求 runtime 机台存在产线关系。
- 只提供 `machine_lines` 而 `lines` 为空时，Adapter 明确报错
  `machine_lines were provided but lines are empty`。
- 同时提供完整旧数据时，继续校验产线编码唯一、未知机台、未知产线、重复关系及
  同一机台绑定多条不同产线。
- `lines.wafer_spec` 和 `machine_lines.wafer_spec` 作为兼容字段继续保留。
- 产线的 `workshop_code` 只表达产线自身所属车间，不再作为机台所属车间的算法依据。
- 当前订单规格只来自选中的 AGV 绑定，不从产线规格回退。

## 8. 订单 `orders`

```json
{
  "order_code": "O-T",
  "order_status": "IN_PROGRESS",
  "total_quantity": 10000.0,
  "piece_source": "A",
  "estimated_yield": "98.5%",
  "product_code": "PROD-T",
  "product_name": "HG182T",
  "workshop_code": "WS-S1",
  "workshop_name": "S1测试车间",
  "produced_quantity": 2000.0,
  "remaining_quantity": 8000.0
}
```

关键规则：

- `order_code` 是订单唯一编码。
- 新契约不包含 `order_name`；不得用 `product_name` 复制出兼容别名。
- `product_code` 和 `product_name` 必须与 `products` 中同一产品记录完全一致。
- AGV 当前订单只允许状态为 `RUNNING`、`OPEN` 或 `生产中` 的订单参与匹配；
  `product_name` 必须唯一对应其中一个当前有效订单。找不到或匹配多个都会明确报错，
  不模糊匹配、不默认取第一条。Buffer 的现有映射仍按其适用规则解析产品名称。
- `workshop_code` 必须能在 `workshops` 中找到。
- `remaining_quantity` 必须等于 `total_quantity - produced_quantity`，允许极小浮点误差。

## 9. 产品 `products`

```json
{
  "product_code": "PROD-T",
  "product_name": "HG182T",
  "wafer_size": "182",
  "source_grade": "A",
  "material_code": "MAT-T",
  "material_name": "182N硅片T"
}
```

用途：

- `wafer_size` 用于候选机台兼容判断。
- `source_grade` 用于片源兼容判断。

## 10. 工艺路线 `process_routes`

```json
{
  "process_code": "P-ZR",
  "process_name": "制绒",
  "sequence": 100,
  "cache_type": "BUFFER",
  "workshop_code": "WS-S1",
  "workshop_name": "S1测试车间",
  "upstream_process_code": null,
  "upstream_process_name": null,
  "downstream_process_code": "P-PK",
  "downstream_process_name": "硼扩"
}
```

规则：

- 同一 `(workshop_code, process_code)` 不允许重复；外部 loop 不能用于绕过该唯一性。
- 机台所属车间通过
  `machine_master.process_code -> process_routes.process_code
  -> process_routes.workshop_code` 解析。
- `process_code` 继续作为路线、机台和 Buffer 的关联主键；`process_name` 只用于识别
  内部所属循环。
- 本次快照中 `machine_realtime` 引用的机台，其 `machine_master.process_code`
  必须能在工艺路线中找到；缺失时明确报错，不回退 `lines.workshop_code`。
- 未被本次 runtime 引用的静态机台不因缺少本次路线而被无条件拒绝。
- `sequence` 完全采用后端输入，每项仍须为正整数，在同一 `workshop_code` 内唯一并可排序；
  不写死顺序，车间最小值不必等于 1，也不要求连续。
- 完整路线按 `workshop_code` 校验。首尾和相邻节点仍须形成完整串行链，但其
  `upstream_process_code` / `downstream_process_code` 可以跨内部循环。
- 每个 workshop 的完整路线必须且只能有一个 trim 后精确名称为 `丝网` 的工序，且其
  `sequence` 为该 workshop 最大值；不会对 `LOOP1` 至 `LOOP4` 分别要求丝网。
- `loop_code`、`loop_name` 均可省略或传 `null`。旧请求传入旧值或错误值仍兼容，
  Snapshot 会忽略它们并按 `process_name` 重新生成内部 loop。

内部循环目录只有下列 12 个规范名称：

| `process_name` | 内部 `loop_code` / `loop_name` |
|---|---|
| 发料机 | `LOOP1` / 一循环 |
| 制绒、硼扩、氧化 | `LOOP2` / 二循环 |
| 碱抛、`POLY`、退火 | `LOOP3` / 三循环 |
| `RCA` | `LOOP4` / 四循环 |
| `ALD`、正膜、背膜、丝网 | `LOOP5` / 五循环 |

所有名称先 trim；中文随后精确匹配，只有 `POLY`、`RCA`、`ALD` 兼容大小写。未知
`process_name` 会按现有错误体系报告对应 `process_code`、原始名称和无法识别循环的原因，
不增加别名或模糊匹配。

## 11. Buffer 主数据和实时库存

### `buffer_master`

```json
{
  "buffer_code": "BUF-ZR-PK",
  "buffer_name": "制绒硼扩间Buffer",
  "buffer_type": "LINE",
  "buffer_type_title": "线边库",
  "max_capacity": 100000.0,
  "safety_low": 100.0,
  "served_process_codes": ["P-ZR", "P-PK"],
  "served_process_names": ["制绒", "硼扩"],
  "loop_code": "LOOP-ZR-PK",
  "loop_name": "制绒到硼扩测试循环"
}
```

规则：

- `served_process_codes` 和 `served_process_names` 长度必须一致。
- 当前算法要求 `served_process_codes` 恰好包含两个工序编码；编码在同一 workshop
  完整路线中解析，并按后端 route `sequence` 确定上游和下游，不依赖数组排列顺序。
- 两个服务工序可以跨内部循环，也不要求固定相邻；无法在同一 workshop 唯一解析、
  两者 sequence 相同或引用不存在时会明确报错。
- `served_process_names` 保留现有基础结构校验，但不用于决定区间方向。
- Buffer 的 `loop_code` / `loop_name` 继续作为兼容/描述字段保留，不用于限制服务工序、
  判断上下游、禁止跨循环或决定断料/溢满工序区间。
- `max_capacity` 用于溢满预测。

### `buffer_realtime`

```json
{
  "main_id": "INV-T",
  "buffer_code": "BUF-ZR-PK",
  "bound_source_name": "HG182T",
  "current_quantity": 100.0,
  "current_utilization_rate": 0.001
}
```

规则：

- `buffer_code` 必须能在 `buffer_master` 中找到。
- `bound_source_name` 表示当前绑定的产品型号名称，必须精确匹配唯一的
  `orders.product_name`；解析出的订单必须与 Buffer 所属车间一致。
- 同一个 Buffer 可以存在多个订单库存。
- 同一个订单可以存在于多个 Buffer。
- 同一 `(buffer_code, order_code)` 不允许重复。

## 12. AGV 当前订单绑定 `agv_relations`

甲方原始记录：

```json
{
  "equipmentid": "EA003",
  "equipmentname": "EA003制绒机",
  "linename": "182N至上产品",
  "lastlinename": null,
  "waferspec": "N",
  "createtime": "2026-07-23 10:23:39"
}
```

Loader 内部标准化结果：

```json
{
  "machine_code": "EA003",
  "machine_name": "EA003制绒机",
  "product_name": "182N至上产品",
  "previous_product_name": null,
  "wafer_spec": "N",
  "binding_time": "2026-07-23 10:23:39"
}
```

唯一映射关系：

| 甲方原始字段 | 算法标准字段 |
|---|---|
| `equipmentid` | `machine_code` |
| `equipmentname` | `machine_name` |
| `linename` | `product_name` |
| `lastlinename` | `previous_product_name` |
| `waferspec` | `wafer_spec` |
| `createtime` | `binding_time` |

关键规则：

- 原始 AGV 的 `equipmentcode`、`processcode`、`processname` 及其他现场字段会被过滤。
- 机台工序始终来自 `machine_master`，不使用也不校验 AGV 工序。
- `waferspec` 是必填且不可为 `null` 的字符串；Loader 将其映射为标准
  `wafer_spec`。当前业务数据和示例使用 `N`、`R`、`P`，本次变更不新增枚举校验。
- 无时区的 `binding_time` 按 UTC+08:00 解释。
- 每台机台选择 `binding_time <= snapshot_time` 的最新记录，不依赖数组顺序。
- 最新时间完全重复的记录可去重；同一最新时间的 `equipmentname`、`linename`、
  `lastlinename` 或 `waferspec` 任一冲突时拒绝计算。
- `equipmentid` 精确匹配静态标准 `machine_code`；`linename` 先精确匹配唯一产品，
  再精确匹配唯一当前订单并取得 `order_code`。
- `lastlinename` 允许为 `null` 或空字符串，只表示上一产品；它不参与当前订单匹配，
  也不在 `linename` 为空或未知时兜底。
- 选中的 AGV 绑定是机台当前产品型号和 `wafer_spec` 的唯一权威；
  `AlgorithmMachineRuntime` 只保存 `current_order_code`，没有
  `current_wafer_spec`。
- 订单库存或候选机台缺少可用 AGV `wafer_spec` 时明确报错，不回退到
  `lines.wafer_spec` 或 `machine_lines.wafer_spec`。
- 运行机台没有有效 AGV 绑定时拒绝计算；非运行机台允许没有绑定。
- `lastlinecode` 和订单 `order_name` 已从新输入契约及生产映射中删除，旧字段不会作为
  隐藏别名继续生效。

## 13. 待执行切线方案 `pending_cutline_plans`

`pending_cutline_plans` 由算法在首轮自动方案产生时创建，并通过
`CutlineEvaluateResponse.persistence_state.pending_cutline_plans` 返回；后端持久化后在
下一轮请求中原样回传。算法服务本身不保存跨轮状态。首轮业务响应中的预警和
`cutline_decisions[].plan` 仍只是建议，不代表现场已经执行；首轮不会创建 Active 或
混料记录。人工介入结果不会创建 Pending。

单个 Pending 顶层字段：

| 字段 | 含义 |
|---|---|
| `plan_id` | 原切线方案标识；跨轮全局唯一 |
| `warning_id` | 产生方案的预警标识 |
| `warning_type` | `stockout` 或 `overflow` |
| `warning_time` | 预警计算时间 |
| `created_at` | 算法创建方案的 `snapshot_time` |
| `expire_at` | 确认窗口截止时间；默认严格等于 `created_at + 30 分钟` |
| `status` | `PENDING`、`PARTIALLY_CONFIRMED`、`CONFIRMED`、`EXPIRED` 或 `RETURN_SUGGESTED` |
| `workshop_code` | 预警车间 |
| `process_code` | 待确认切换机台所属的输出侧工序 |
| `buffer_code` | 预警 Buffer |
| `upstream_process_code` | 预警区间产出侧工序，也是监控机台工序 |
| `downstream_process_code` | 预警区间下游工序 |
| `monitored_order_code` | 断料时需要增加机台的订单；溢满时需要减少机台的订单 |
| `source_order_code` / `target_order_code` | 方案源/目标订单摘要；多候选内容不唯一时可为空 |
| `source_product_code` / `target_product_code` | 方案源/目标产品摘要；多候选内容不唯一时可为空 |
| `before_machine_count` | 预警时统计口径内运行且绑定监控订单的机台数 |
| `before_machine_codes` | 上述机台的标准 `machine_code` 集合 |
| `expected_machine_count` | 推荐方案全部执行后的预期机台数 |
| `expected_delta_direction` | 断料为 `increase`，溢满为 `decrease` |
| `candidate_machines` | 推荐机台及其预期换型上下文 |
| `candidate_machine_codes` | 与 `candidate_machines[].machine_code` 顺序一致的标准机台号 |
| `baseline_machine_bindings` | 监控范围内全部相关机台的预警时绑定，不只包含候选机台 |
| `confirmed_machine_codes` | 此方案此前已经确认并创建事件的标准机台编码 |

`candidate_machines[]` 完整字段：

| 字段组 | 字段 |
|---|---|
| 标识和范围 | `machine_code`、`process_code`、`workshop_code` |
| 切线前绑定 | `baseline_order_code`、`baseline_product_code`、`baseline_product_name`、`baseline_wafer_size`、`baseline_wafer_spec`、`baseline_source_grade` |
| 预期切线后绑定 | `expected_target_order_code`、`expected_target_product_code`、`expected_target_product_name`、`expected_target_wafer_size`、`expected_target_wafer_spec`、`expected_target_source_grade` |
| 区间上下文 | 可空 `source_buffer_code`、`target_buffer_code`、`target_upstream_process_code`、`target_downstream_process_code` |

`baseline_machine_bindings[]` 完整字段为 `machine_code`、`order_code`、
`product_code`、`product_name`、`wafer_size`、`wafer_spec`、`source_grade`、
`process_code`、`workshop_code`、`machine_status` 和 `observed_at`。输入兼容旧名
`agv_record_time`，但算法输出统一使用 `observed_at`。机台数统计范围固定为“预警车间、
预警区间产出侧工序、现有 running 状态口径和 monitored_order_code”；但基线集合要
覆盖该车间和工序内所有可观察绑定，才能识别现场自行选择的非候选机台。
每条 `observed_at` 必须 `<= created_at`，表示方案创建时算法已经观察到的绑定状态。

后端保存与回传规则：

1. 首轮从 `persistence_state` 保存完整 Pending，初始
   `confirmed_machine_codes=[]`；不要从业务方案自行拼装 Pending。
2. 下一轮同时回传 Pending 和完整 AGV 历史；不得只保留每台机台的最新一条记录。
3. 算法只在 `created_at < createtime <= expire_at` 且不晚于本轮
   `snapshot_time` 的记录中确认绑定变化，并先检测边界记录再处理到期。
4. 后端以同轮 `persistence_state` 为权威完整状态，不自行解析事件 ID 或推导
   `confirmed_machine_codes`。
5. 只完成部分机台时状态为 `PARTIALLY_CONFIRMED` 并继续监控至截止时间；全部完成为
   `CONFIRMED`；未完成部分到期为 `EXPIRED`。已确认 Active 不因 Pending 到期而删除。
6. 同一业务键（预警类型、车间、Buffer、上下游工序、监控订单）已有有效 Pending
   或带完整来源元数据的 Active 时，不要再次建立等价 Pending。

`linename` 始终用于精确解析当前产品和当前唯一订单；`lastlinename` 只验证它是否与
保存的基线产品一致。`lastlinename` 为空不妨碍用明确的新 AGV 记录确认；非空但与基线
冲突时请求会被拒绝。当前把 `createtime` 解释为算法可观察到的绑定记录时间，接口方
仍需确认它是否就是现场实际换型时间。

合法非候选机台只按保存的车间、工序、精确订单映射、时间窗口和严格切换方向确认，
不重新执行候选机台的 wafer/source-grade 影响筛选或全局优化。溢满目标区间只作为
持久化上下文；不能以当轮 `net_consumption_rate > 0` 否认已经发生的合法真实切换，
但目标上下文缺失或歧义仍会明确报错。

## 14. 活动切线跟踪事件 `active_cutline_events`

`active_cutline_events` 是后端上一轮从
`persistence_state.active_cutline_events` 保存的完整跟踪事件，在下一轮请求中回传给算法。

事件中的 `machine_code` 已经是算法标准 `machine_master.machine_code`，不使用 P166 实时码。

这类数据只用于算法跨轮次跟踪，不用于前端展示。

来源只有算法确认真实 AGV 绑定变化后产生的 Active。业务响应仍通过：

- `new_active_cutline_events`：保持原有 12 字段，供旧业务调用方消费
- `persistence_state.active_cutline_events`：包含完整生命周期和来源上下文，供后端保存

`updated_active_cutline_events` 只包含已有事件的计时增量，不是一份可替换完整事件的
新对象；后端应按 `event_id` 合并 `negative_start_time`。

后端回传规则：

1. Pending 确认后，保存 `persistence_state.active_cutline_events` 的完整集合；方案生成
   本身不会输出 Active。
2. 下一轮请求时，把该完整集合放到请求顶层 `active_cutline_events`。
3. 按 `updated_active_cutline_events[].event_id` 合并计时；显式
   `negative_start_time: null` 表示清空计时。
4. 将 `persistence_state.return_suggested_event_ids` 和
   `persistence_state.mixed_cutline_event_ids` 分别回传到请求同名字段。
5. `return_recommendations` 是面向业务的本轮切回建议；完整 Active 同轮更新为
   `return_recommended`。算法不检测现场实际切回，现场可继续更新为 `returned` 或
   `cancelled`。

活动事件的公开 12 字段保持不变。完整持久化对象还包含 `plan_id`、`warning_id`、
`status`、`source_buffer_code`、原硅片信息、贡献产能、预警类型/区间、
`process_code` 和 `is_recommended_candidate` 等来源元数据。由真实确认产生的新事件会
填满混料所需上下文；缺少这些上下文的历史兼容事件仍可做原有跟踪，但不会被猜测性地
补全后创建混料。所有事件机台号必须是标准 `machine_master.machine_code`，不能传
`p166_jt_group`。`cutline_start_time` 是确认绑定变化的 AGV `createtime`，不是计划时间。

Active 状态支持 `active`、`return_recommended`、`returned`、`cancelled`。只有尚未
进入 `return_suggested_event_ids` 且状态为 `active` 的事件进入 ReturnEvaluator；只有
尚未进入 `mixed_cutline_event_ids`、状态为 `active` 或 `return_recommended` 且来源
上下文完整的事件进入混料计算。混料成功才推进水位，失败保持可重试。

## 15. 最小有效请求样例

省略 `lines`、`machine_lines` 的标准样例：

- `examples/backend_request_standard.json`

显式传入两个空数组的简单合法样例：

- `examples/backend_request_sample.json`

完整断料出方案样例：

- `examples/backend_request_stockout_plan_sample.json`

推荐后端联调依次运行首轮断料样例和确认轮样例。首轮能实际输出：

- `stockout_warnings`
- `cutline_decisions`
- `persistence_state.pending_cutline_plans`

首轮 `new_active_cutline_events` 和 `mixing_trace_records` 必须都为空。多轮确认样例
`examples/scenarios/v3_return_round_2.json` 回传 Pending 和新 AGV 绑定，可实际输出
一条 `new_active_cutline_events`、一条 `mixing_trace_records`，并在
`persistence_state` 推进 Pending、Active 和混料水位。

## 16. 当前样例校验结果

当前三个输入样例均已通过 `BackendRequestLoader` 标准化及
`CutlineAlgorithmRequest` 校验：

```text
examples/backend_request_standard.json OK
examples/backend_request_sample.json OK
examples/backend_request_stockout_plan_sample.json OK
```

完整断料样例当前输出摘要：

```text
stockout_warnings=1
cutline_decisions=1
pending_cutline_plans=1
new_active_cutline_events=0
mixing_trace_records=0
errors=0
```

