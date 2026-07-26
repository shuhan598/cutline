# 后端字段到算法权威来源映射

本文只说明会影响算法判断的权威来源。完整请求字段定义见
`docs/backend-request-interface.md`，原始文档字段对照见
`docs/2026-07-14-algo-request-document-field-mapping.md`。

## 机台当前生产信息

| 算法语义 | 原始字段 | 标准/内部字段 | 权威来源 |
| --- | --- | --- | --- |
| 当前订单编码 | `agv_relations.lastlinecode` | `order_code` | 最新有效 AGV 绑定 |
| 当前订单名称 | `agv_relations.lastlinename` | `order_name` | 最新有效 AGV 绑定 |
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
