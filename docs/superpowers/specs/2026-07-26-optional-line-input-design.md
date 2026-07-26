# 可选产线输入与核心算法解耦设计

## 目标

保留 `Line`、`MachineLine` 相关 Schema 和旧请求兼容能力，同时允许后端完全省略
`lines`、`machine_lines` 或显式传入空数组。核心算法不生成占位产线，也不依赖产线
数据存在。

## 输入契约

`BackendAlgorithmRequest`、`CutlineAlgorithmRequest` 和 `AlgorithmSnapshot` 的
`lines`、`machine_lines` 使用独立的空列表默认工厂。数组中的单条记录仍保持原有
严格字段约束。

SnapshotAdapter 的组合规则：

- 两个集合均为空：通过。
- 仅 `lines` 非空：通过。
- 仅 `machine_lines` 非空：抛出 `SnapshotConversionError`。
- 两个集合均非空：执行原有唯一性、未知机台、未知产线和重复绑定校验。

runtime 不再被要求必须存在 machine-line 关系。运行机台的工艺路线和 AGV 完整性
校验保持不变。

## 核心权威来源

```text
机台工序：machine_code -> machine_master.process_code
机台车间：machine_master.process_code -> process_routes.workshop_code
当前订单：AGV.lastlinecode -> order_code
订单名称：AGV.lastlinename -> order_name
当前规格：AGV.waferspec -> wafer_spec
```

净速率、断料候选、溢满候选和丝网模块不再建立 line 或 machine-line 索引。
`CandidateContext.machine_context()` 只返回 runtime 和 machine master。切回、混料、
计划、Pipeline 和响应映射不引入产线依赖。

## 兼容与验证

共享测试工厂继续生成完整旧产线数据，用于兼容回归。正式示例分别展示完全省略和
显式空数组，场景 JSON 使用显式空数组运行完整算法链。
