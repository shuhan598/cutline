# 机台所属车间来源切换至工艺路线设计

**日期：** 2026-07-26  
**状态：** 已批准，按方案 A 实施  
**范围：** 统一车间解析、快照前置校验、净速率、候选机台、丝网模块、测试与输入文档

## 1. 目标与权威链路

机台所属车间的唯一算法权威链路调整为：

```text
machine_code
  -> machine_master.process_code
  -> process_routes.process_code
  -> process_routes.workshop_code
```

核心算法不再通过以下链路判断机台所属车间：

```text
machine_code
  -> machine_lines.line_code
  -> lines.workshop_code
```

`lines`、`machine_lines`、`line.workshop_code`、`line.wafer_spec` 及相关 Schema
继续保留。后续《可选产线输入与核心算法解耦设计》已将两个顶层集合改为默认空列表；
当完整旧数据同时提供时，本设计规定的转换和引用校验仍继续执行。

## 2. 统一解析器

新增单一职责的 `MachineWorkshopResolver`，由 `snapshot.process_routes` 建立：

```text
process_code -> workshop_code
```

解析规则：

1. 同一 `process_code` 只出现一次时，直接建立映射。
2. 同一 `process_code` 因不同 `loop_code` 出现多次，但所有
   `workshop_code` 相同时，允许并解析为该车间。
3. 同一 `process_code` 对应多个不同 `workshop_code` 时，按编码排序后在错误中
   列出全部冲突车间，不依赖输入顺序选择结果。
4. 查询不存在的 `process_code` 时明确报错，不回退 `line.workshop_code`。
5. 解析机台时，错误信息保留 `machine_code` 和 `process_code`；冲突错误同时保留
   全部冲突的 `workshop_code`。

解析器提供：

```text
resolve_by_process_code(process_code)
resolve_machine_workshop(machine)
```

所有核心模块复用该类，不在各模块复制工序到车间的索引规则。

## 3. SnapshotAdapter 前置校验范围

`SnapshotAdapter` 在工艺路线转换完成后创建解析器，并校验本次快照中实际参与算法的
机台。前置校验至少覆盖 `machine_realtime` 转换出的每台运行时记录所引用的机台：

1. 通过 `machine_code` 找到已转换的 `AlgorithmMachineMaster`；
2. 读取 `machine.process_code`；
3. 通过统一解析器解析唯一车间；
4. 缺少路线或跨车间冲突时转为 `SnapshotConversionError`。

不无条件要求静态 `machine_master` 全量数据都必须能在本次
`process_routes` 中找到。其他参与范围继续沿用现有 runtime、machine-line、产能、
AGV 等引用完整性规则。

## 4. 模块异常边界

统一解析器抛出 `MachineWorkshopResolutionError`，调用模块保留现有异常边界：

- `SnapshotAdapter` 转为 `SnapshotConversionError`；
- 净速率转为 `NetRateCalculationError`；
- 候选上下文转为 `CandidateMachineCalculationError`；
- 丝网模块转为 `SilkScreenTransitionCalculationError`。

错误转换保留原始诊断信息，不吞掉机台、工序或冲突车间编码。

## 5. 净速率

净速率上下游运行机台的匹配字段为：

- `runtime.status`：实时运行状态；
- runtime 投入、产出字段：30 分钟实时数据；
- `AGV.order_code`：当前订单；
- `AGV.wafer_spec`：当前订单规格；
- `machine_master.process_code`：机台工序；
- `process_routes.workshop_code`：机台所属车间。

现有 `machine_line_by_code` 和 `line_by_code` 索引及引用校验保留，但
`_matching_runtimes` 不再读取 `line.workshop_code`。净速率公式、订单规格解析、
`main_id` 与多物理 Buffer 聚合全部保持不变。

## 6. 候选机台

`CandidateContext` 创建统一解析器，并提供：

```text
machine_workshop_code(machine_code)
```

该方法先定位 machine master，再按其 `process_code` 解析车间。现有
`machine_context()`、line 和 machine-line 索引继续保留兼容。

断料和溢满 Finder 使用解析出的车间：

- 与 `warning.workshop_code` 比较；
- 传给 ProductCompatibilityChecker；
- 写入候选结果的 `workshop_code`。

候选机台当前订单编码、订单名称、硅片规格继续从 AGV 获取。尺寸、片源、S2 丝网前
R/P 兼容、排序、产能贡献、空闲度、利用率及溢满同 Buffer 目标拒绝规则保持不变。

## 7. 丝网模块

丝网模块仍保留 machine-line 和 line 引用校验，但分组、订单查找、结果车间及错误上下文
统一使用 `machine.process_code -> process_routes.workshop_code`。丝网识别、实时产能、
清台时间和准备判断不变。

## 8. AGV 与其他不变项

上一轮 AGV 权威链路完整保留：

```text
equipmentid/equipmentname/lastlinecode/lastlinename/waferspec/createtime
  -> machine_code/machine_name/order_code/order_name/wafer_spec/binding_time
  -> SnapshotAdapter 选择最新有效绑定
  -> AlgorithmAgvRelation
  -> 净速率与候选
```

`AlgorithmMachineRuntime` 不增加规格字段，不读取或回退 `line.wafer_spec`。
断料、溢满、切回、混料业务规则均不修改。

## 9. 测试策略

严格按 TDD 增加以下回归：

1. 解析单工序单车间。
2. 同工序多循环同车间。
3. 同工序跨车间冲突，错误稳定列出冲突车间。
4. 参与机台工序缺少路线，且不回退产线。
5. 未参与 runtime 的静态机台不被 Adapter 无条件拒绝。
6. 净速率在线车间和路线车间相反时的正、反例。
7. 断料与溢满候选以路线车间为准。
8. S2 R/P 兼容的正、反例使用路线车间。
9. 丝网分组和结果使用路线车间。
10. `main_id` 聚合与 AGV 规格来源回归。
11. 非 mock FastAPI 全链路中故意制造 line 与 route 车间不一致。

## 10. 文档

更新：

- `README.md`
- `docs/backend-request-interface.md`
- `docs/2026-07-14-algo-request-document-field-mapping.md`
- `docs/superpowers/specs/2026-07-26-agv-wafer-spec-source-design.md`

新增：

- `docs/backend-field-source-mapping.md`

文档明确区分机台当前生产信息的 AGV 权威来源、机台所属车间的工艺路线权威来源，
以及暂时保留的产线兼容字段。
