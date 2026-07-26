# 算法请求字段与文档对照

## 目的

这份文档用于对照 `PaiChanDocs/链接.docx` 中的数据分类字段，与当前 `orchestrator -> algorithm service` 实际外发 JSON 字段之间的映射关系。

当前外发 DTO 定义位于：

- `backend/orchestrator/src/main/java/com/paichan/orchestrator/algo/CutlineAlgorithmRequest.java`

当前真实请求体可通过调试接口查看：

- `GET /api/algo-runs/{runId}/request`

## 顶层分组对照

| 文档分类 | 当前外发顶层字段 |
| --- | --- |
| 机台实时数据 | `machine_realtime` |
| 机台基础数据 | `machine_master` |
| 工艺时长数据 / 机台基础数据-工艺时长数据（中间表） | `machine_process_times` |
| 车间数据 | `workshops` |
| 产线数据 | `lines`（可选兼容） |
| 机台-产线（中间表） | `machine_lines`（可选兼容） |
| 订单数据 | `orders` |
| 产品型号数据 | `products` |
| 工艺路线数据 | `process_routes` |
| Buffer实时数据 | `buffer_realtime` |
| Buffer基础数据 | `buffer_master` |
| AGV查询接口数据 | `agv_relations` |
| 项目保留运行元数据 | `snapshot_meta` |

## `snapshot_meta`

说明：

- `snapshot_meta` 不属于 `链接.docx` 里的业务分类。
- 这是项目显式保留的运行元信息，用于追踪一次算法请求的生成上下文。
- 所有缺失字段、缺失数据集或降级都必须写入 `degraded_flags`。

| 含义 | 当前外发字段 |
| --- | --- |
| 运行编号 | `run_id` |
| 触发类型 | `trigger_type` |
| 车间编号 | `workshop_id` |
| 快照时间 | `snapshot_time` |
| 参数版本 | `params_version` |
| 静态目录版本 | `catalog_version` |
| 静态目录加载时间 | `catalog_loaded_at` |
| 降级标记列表 | `degraded_flags` |

## `machine_realtime`

对应文档分类：机台实时数据

| 文档字段 | 当前外发字段 |
| --- | --- |
| 机台编码 | `machine_code` |
| 当前生产状态 | `status` |
| 订单编号 | `order_code` |
| 切线时间 | `tangent_time` |
| 上料数量 | `input_quantity` |
| 出料数量 | `output_quantity` |
| 已完成数量 | `completed_quantity` |

补充说明：

- 当前实现额外保留 `period_quantity`，用于表达当前时段产量。
- 当前实现额外保留 `out_time`，用于表达运行态出料时间。
- 这两个字段属于设计明确保留的运行态补充，不是对文档字段的删除或替换。

## `machine_master`

对应文档分类：机台基础数据

| 文档字段 | 当前外发字段 |
| --- | --- |
| 机台编码 | `machine_code` |
| 机台名称 | `machine_name` |
| 所属工序编号.编码 | `process_code` |
| 所属工序编号.名称 | `process_name` |

## `machine_process_times`

对应文档分类：

- 工艺时长数据
- 机台基础数据-工艺时长数据（中间表）

| 文档字段 | 当前外发字段 |
| --- | --- |
| 机台编号.机台编码 | `machine_code` |
| 机台编号.机台名称 | `machine_name` |
| 产品型号编号.产品型号编码 | `product_code` |
| 产品型号编号.产品型号名称 | `product_name` |
| 工艺时间 | `proc_seconds` |

补充说明：

- 当前实现额外保留 `actual_capacity`，用于表达该机台对该产品的实际产能信息。
- 该分组本质上是“机台 × 产品型号”的工艺时长关系，不要求算法侧再自行拼表。

## `workshops`

对应文档分类：车间数据

| 文档字段 | 当前外发字段 |
| --- | --- |
| 车间编码 | `workshop_code` |
| 车间名称 | `workshop_name` |

## `lines`

对应文档分类：产线数据

| 文档字段 | 当前外发字段 |
| --- | --- |
| 产线编码 | `line_code` |
| 产线名称 | `line_name` |
| 绑定硅片规格 | `wafer_spec` |
| 所属车间编号.车间编码 | `workshop_code` |
| 所属车间编号.车间名称 | `workshop_name` |

补充说明：

- `lines` 顶层数组可完全省略或显式传入空数组，Schema 默认得到空列表。
- `lines.workshop_code` 只表示产线自身所属车间，作为兼容输入继续保留。
- 核心算法不再用该字段判断机台所属车间或当前生产规格。

## `machine_lines`

对应文档分类：机台-产线（中间表）

| 文档字段 | 当前外发字段 |
| --- | --- |
| 机台编码 | `machine_code` |
| 机台名称 | `machine_name` |
| 产线编码 | `line_code` |
| 产线名称 | `line_name` |
| 绑定硅片规格 | `wafer_spec` |

补充说明：

- `machine_lines` 顶层数组可完全省略或显式传入空数组，Schema 默认得到空列表。
- 同时提供完整 `lines` 和 `machine_lines` 时，现有引用完整性校验继续保留。
- 仅提供 `machine_lines` 而 `lines` 为空时明确报错。
- 机台所属车间不再通过 `machine_lines -> lines.workshop_code` 推导。
- 当前核心算法不依赖 `lines` 或 `machine_lines`；机台车间来自
  `machine_master.process_code -> process_routes.workshop_code`，当前订单和规格来自
  AGV。

## `orders`

对应文档分类：订单数据

| 文档字段 | 当前外发字段 |
| --- | --- |
| 订单编号 | `order_code` |
| 订单状态 | `order_status` |
| 订单总量 | `total_quantity` |
| 片源 | `piece_source` |
| 预计良率 | `estimated_yield` |
| 产品型号编号.产品型号编码 | `product_code` |
| 产品型号编号.产品型号名称 | `product_name` |
| 所属车间编号.车间编码 | `workshop_code` |
| 所属车间编号.车间名称 | `workshop_name` |
| 已生产量 | `produced_quantity` |
| 未生产量 | `remaining_quantity` |

补充说明：

- 当前实现中 `estimated_yield` 仍按字符串外发。
- 当前实现中 `produced_quantity` 与 `remaining_quantity` 按数值外发。

## `products`

对应文档分类：产品型号数据

| 文档字段 | 当前外发字段 |
| --- | --- |
| 产品型号编码 | `product_code` |
| 产品型号名称 | `product_name` |
| 硅片尺寸 | `wafer_size` |
| 硅片片源等级 | `source_grade` |
| 物料编码.编码 | `material_code` |
| 物料编码.名称 | `material_name` |

## `process_routes`

对应文档分类：工艺路线数据

| 文档字段 | 当前外发字段 |
| --- | --- |
| 工序编号.工序编码 | `process_code` |
| 工序编号.工序名称 | `process_name` |
| 工序顺序号 | `sequence` |
| 下料可缓存类型 | `cache_type` |
| 所属车间编号.车间编码 | `workshop_code` |
| 所属车间编号.车间名称 | `workshop_name` |
| 所属循环编号.循环编码 | `loop_code` |
| 所属循环编号.循环名称 | `loop_name` |
| 工序上游.工序编码 | `upstream_process_code` |
| 工序上游.工序名称 | `upstream_process_name` |
| 工序下游.工序编码 | `downstream_process_code` |
| 工序下游.工序名称 | `downstream_process_name` |

补充说明：

- 机台所属车间的权威链路为
  `machine_master.process_code -> process_routes.process_code
  -> process_routes.workshop_code`。
- 同一工序可在同一车间的多个循环中出现；如果映射到多个不同车间则明确报错。
- 本次快照中 runtime 引用机台的工序缺少路线时明确报错，不回退到产线车间。

## `buffer_realtime`

对应文档分类：Buffer实时数据

| 文档字段 | 当前外发字段 |
| --- | --- |
| mainID | `main_id` |
| bufferid / buffer编码 | `buffer_code` |
| 订单与物料绑定信息 | `bound_source_name` |
| 当前库存量 | `current_quantity` |
| 当前占用率 | `current_utilization_rate` |

## `buffer_master`

对应文档分类：Buffer基础数据

| 文档字段 | 当前外发字段 |
| --- | --- |
| buffer编码 | `buffer_code` |
| buffer名称 | `buffer_name` |
| buffer类型 | `buffer_type` |
| buffer类型_类型 | `buffer_type_title` |
| 最大容量 | `max_capacity` |
| 安全库存下限 | `safety_low` |
| 服务工序列表.工序编码 | `served_process_codes` |
| 服务工序列表.工序名称 | `served_process_names` |
| 所属循环编号.循环编码 | `loop_code` |
| 所属循环编号.循环名称 | `loop_name` |

补充说明：

- 文档里同时出现“buffer类型”和“buffer类型_类型”两层表达。
- 当前实现将第二层标题语义映射为 `buffer_type_title`。

## `agv_relations`

对应文档分类：AGV查询接口数据

| 甲方原始字段 | 算法标准字段 |
| --- | --- |
| `equipmentid` | `machine_code` |
| `equipmentname` | `machine_name` |
| `lastlinecode` | `order_code` |
| `lastlinename` | `order_name` |
| `waferspec` | `wafer_spec` |
| `createtime` | `binding_time` |

补充说明：

- 字段映射只在 `BackendRequestLoader` 中执行。
- AGV 原始记录中的 `processcode`、`processname` 及其他现场字段不进入算法契约。
- 机台工序始终来自 `machine_master.process_code/process_name`。
- `waferspec` 是必填且不可为 `null` 的字符串，并映射为 `wafer_spec`。当前业务数据
  和示例使用 `N`、`R`、`P`，本次变更不新增枚举校验。
- `binding_time` 不晚于快照时间的最新有效记录提供机台当前订单编码、订单名称和
  硅片规格。
- 当前订单硅片规格以 AGV 绑定为唯一权威；缺失时明确报错，不从产线字段回退。
- `AlgorithmMachineRuntime` 不保存 `current_wafer_spec`；产线规格字段仅保留兼容性，
  机台所属车间改由 `machine_master.process_code -> process_routes.workshop_code`
  解析。

## 额外说明

- 当前外发字段命名全部统一为英文 `snake_case`。
- 只有契约中明确声明可空的字段才允许 `null`；必填 AGV 业务字段（包括
  `waferspec`）不得缺失或为 `null`。允许为空的数据集可以传空数组，但必须在
  `snapshot_meta.degraded_flags` 中留下可诊断标记。
- 查看某次真实外发请求建议直接调用：

```bash
curl -sS http://127.0.0.1:8080/api/algo-runs/<runId>/request | jq
```
