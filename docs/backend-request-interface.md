# 切线算法输入接口文档

> 更新时间：2026-07-23
>
> 本文档描述后端传给算法服务的请求 JSON。正式同步 HTTP 路由为
> `POST /stub/algo/run` 和 `POST /cutline/evaluate`；预校验路由为
> `POST /backend/validate`。

## 1. 输入 JSON 是哪一块

算法标准请求对象是：

```python
app.schemas.request_schema.CutlineAlgorithmRequest
```

HTTP 请求先以 JSON 对象进入 `BackendRequestLoader`，其中 AGV 原始六字段会被统一
映射为算法标准六字段，再校验为 `CutlineAlgorithmRequest`。因此正式计算接口可直接
接收甲方原始 AGV 字段，不会在映射前按标准字段返回 422。

HTTP 契约：

```http
POST /stub/algo/run
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

当前可参考输入样例：

- 简单合法样例：`examples/backend_request_sample.json`
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
  "active_cutline_events": []
}
```

请求中不要传 `config`。算法参数由内部默认配置 `AlgorithmConfig` 注入。

| 字段 | 类型 | 是否必填 | 含义 |
|---|---|---|---|
| `snapshot_meta` | object | 是 | 本次快照上下文 |
| `machine_realtime` | array | 是 | 机台实时运行数据 |
| `machine_master` | array | 是 | 机台主数据和工序归属 |
| `machine_process_times` | array | 是 | 机台-产品工艺时间和产能 |
| `workshops` | array | 是 | 车间基础数据 |
| `lines` | array | 是 | 产线和硅片规格 |
| `machine_lines` | array | 是 | 机台与产线关系 |
| `orders` | array | 是 | 订单基础和数量数据 |
| `products` | array | 是 | 产品型号基础数据 |
| `process_routes` | array | 是 | 工艺路线 |
| `buffer_realtime` | array | 是 | Buffer 实时库存 |
| `buffer_master` | array | 是 | Buffer 主数据 |
| `agv_relations` | array | 是 | AGV 机台当前订单绑定历史 |
| `active_cutline_events` | array | 否，默认空数组 | 后端回传的活动切线跟踪事件 |

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
  "machine_code": "ZR-02",
  "status": "运行",
  "tangent_time": null,
  "input_quantity": 300.0,
  "output_quantity": 300.0,
  "completed_quantity": 300.0,
  "period_quantity": 300.0,
  "out_time": "2026-07-16T08:25:00+08:00"
}
```

关键规则：

- `machine_code` 必须能在 `machine_master` 中找到。
- `status` 只有“运行”或大小写不同的 `running` 会进入算法映射为 `running`。
- 其它状态，包括“停机”“异常”“待机”等，统一映射为 `stopped`，算法不会调用这些机台。
- `machine_realtime` 不再提供 `order_code`；当前订单由快照时刻的有效 AGV 绑定提供。
- `input_quantity` 和 `output_quantity` 是当前 30 分钟数量，算法会乘以 2 折算小时速率。
- `period_quantity` 当前主要用于保留丝网相关统计值。
- `tangent_time`、`out_time` 没有值时传 `null`。

## 5. 机台主数据 `machine_master`

```json
{
  "machine_code": "ZR-02",
  "machine_name": "制绒二号",
  "process_code": "P-ZR",
  "process_name": "制绒"
}
```

`process_code` 是算法判断机台所属工序的核心字段。

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

- 每台机台必须有且只有一个有效产线关系。
- `lines.wafer_spec` 和 `machine_lines.wafer_spec` 作为兼容字段继续保留。
- 机台 -> 产线 -> 车间的归属链保持不变，但不再从产线推导当前订单的
  `wafer_spec`；当前订单规格只来自选中的 AGV 绑定。

## 8. 订单 `orders`

```json
{
  "order_code": "O-T",
  "order_name": "HG182T订单",
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
- `order_name` 必填，不允许缺失、`null`、空字符串或纯空格。
- Buffer 库存通过 `buffer_realtime.bound_source_name` 匹配订单的 `order_name`。
- `product_code` 必须能在 `products` 中找到。
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
  "sequence": 1,
  "cache_type": "BUFFER",
  "workshop_code": "WS-S1",
  "workshop_name": "S1测试车间",
  "loop_code": "LOOP-ZR-PK",
  "loop_name": "制绒到硼扩测试循环",
  "upstream_process_code": null,
  "upstream_process_name": null,
  "downstream_process_code": "P-PK",
  "downstream_process_name": "硼扩"
}
```

规则：

- 同一 `(workshop_code, loop_code, process_code)` 不允许重复。
- `sequence` 从 1 开始。
- Buffer 服务的两个工序必须能在同一 `loop_code` 下找到，并且相邻。

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
- 当前算法要求每个 Buffer 正好服务两个相邻工序。
- `max_capacity` 用于溢满预测。

### `buffer_realtime`

```json
{
  "main_id": "INV-T",
  "buffer_code": "BUF-ZR-PK",
  "bound_source_name": "HG182T订单",
  "current_quantity": 100.0,
  "current_utilization_rate": 0.001
}
```

规则：

- `buffer_code` 必须能在 `buffer_master` 中找到。
- `bound_source_name` 必须匹配同车间订单的 `order_name`。
- 同一个 Buffer 可以存在多个订单库存。
- 同一个订单可以存在于多个 Buffer。
- 同一 `(buffer_code, order_code)` 不允许重复。

## 12. AGV 当前订单绑定 `agv_relations`

甲方原始记录：

```json
{
  "equipmentid": "EA003",
  "equipmentname": "EA003制绒机",
  "lastlinecode": "ORD-S2-001",
  "lastlinename": "至上",
  "waferspec": "N",
  "createtime": "2026-07-23 10:23:39"
}
```

Loader 内部标准化结果：

```json
{
  "machine_code": "EA003",
  "machine_name": "EA003制绒机",
  "order_code": "ORD-S2-001",
  "order_name": "至上",
  "wafer_spec": "N",
  "binding_time": "2026-07-23 10:23:39"
}
```

唯一映射关系：

| 甲方原始字段 | 算法标准字段 |
|---|---|
| `equipmentid` | `machine_code` |
| `equipmentname` | `machine_name` |
| `lastlinecode` | `order_code` |
| `lastlinename` | `order_name` |
| `waferspec` | `wafer_spec` |
| `createtime` | `binding_time` |

关键规则：

- 原始 AGV 的 `equipmentcode`、`processcode`、`processname` 及其他现场字段会被过滤。
- 机台工序始终来自 `machine_master`，不使用也不校验 AGV 工序。
- `waferspec` 是必填且不可为 `null` 的字符串；Loader 将其映射为标准
  `wafer_spec`。当前业务数据和示例使用 `N`、`R`、`P`，本次变更不新增枚举校验。
- 无时区的 `binding_time` 按 UTC+08:00 解释。
- 每台机台选择 `binding_time <= snapshot_time` 的最新记录，不依赖数组顺序。
- 最新时间完全重复的记录可去重；同一最新时间的 `order_code` 或 `order_name`
  冲突时拒绝计算。
- 只校验最终选中的绑定：编码用于关联，名称只做精确一致性检查。
- 选中的 AGV 绑定是机台当前 `order_code`、`order_name` 和 `wafer_spec` 的唯一权威；
  `AlgorithmMachineRuntime` 只保存 `current_order_code`，没有
  `current_wafer_spec`。
- 订单库存或候选机台缺少可用 AGV `wafer_spec` 时明确报错，不回退到
  `lines.wafer_spec` 或 `machine_lines.wafer_spec`。
- 运行机台没有有效 AGV 绑定时拒绝计算；非运行机台允许没有绑定。
- `BackendOrder` 没有新增 `order_name`：当前后端 ingestion 原始订单没有该字段，
  也没有可按订单编码唯一映射的等价字段。`/backend/validate` 校验订单编码，
  正式计算请求中的 `OrderRequest.order_name` 用于最终名称一致性校验。

## 13. 活动切线跟踪事件 `active_cutline_events`

`active_cutline_events` 是后端上一轮从算法响应中保存的跟踪事件，在下一轮请求中回传给算法。

这类数据只用于算法跨轮次跟踪，不用于前端展示。

来源：

- 算法响应中的 `new_active_cutline_events`
- 算法响应中的仍需继续跟踪的 `updated_active_cutline_events`

后端回传规则：

1. 新方案产生后，保存响应里的 `new_active_cutline_events`。
2. 下一轮请求时，把仍需要跟踪的事件放到请求顶层 `active_cutline_events`。
3. 如果响应中的 `updated_active_cutline_events[].status == "return_recommended"`，说明算法已经给出切回建议，后端关闭该跟踪事件，下一轮不要再回传。
4. 如果事件状态是 `returned` 或 `cancelled`，也不再回传。

## 14. 最小有效请求样例

简单合法样例：

- `examples/backend_request_sample.json`

完整断料出方案样例：

- `examples/backend_request_stockout_plan_sample.json`

推荐后端联调优先使用完整断料样例，因为它能实际输出：

- `stockout_warnings`
- `cutline_decisions`
- `new_active_cutline_events`
- `mixing_trace_records`

## 15. 当前样例校验结果

当前两个输入样例均已通过 `BackendRequestLoader` 标准化及
`CutlineAlgorithmRequest` 校验：

```text
examples/backend_request_sample.json OK
examples/backend_request_stockout_plan_sample.json OK
```

完整断料样例当前输出摘要：

```text
stockout_warnings=1
cutline_decisions=1
new_active_cutline_events=1
mixing_trace_records=1
errors=0
```

