# 机台当前硅片规格来源切换至 AGV 设计

**日期：** 2026-07-26  
**状态：** 已批准，按方案 A 实施  
**范围：** AGV 请求契约与转换、净速率、候选机台、测试数据、示例和输入文档

## 1. 目标和不变项

机台当前生产订单、订单名称和硅片规格由快照中的最新有效 AGV 绑定提供。
`line.wafer_spec` 保留为兼容字段，但不再表示机台当前实际生产规格。

以下逻辑保持不变：

- `AlgorithmMachineRuntime` 结构不增加 `current_wafer_spec`；
- `lines`、`machine_lines` 的必传与转换规则；
- `machine_code -> machine_lines -> lines -> workshop_code` 车间链路；
- 净速率公式与 `main_id`、订单、物理 Buffer 库存聚合规则；
- ProductCompatibilityChecker 的一般规格相等、S2 丝网前 R/P 兼容规则；
- 尺寸、片源等级、候选排序、空闲度、利用率和贡献产能规则；
- 溢满同 Buffer 目标订单拒绝规则；
- 后续净速率、预警、候选、计划、事件和响应中的规格字段。

## 2. AGV 契约与传递链

三层契约增加一个必填字符串字段：

```text
BackendAgvRelation.waferspec
    ↓ BackendRequestLoader: waferspec -> wafer_spec
AgvRelationRequest.wafer_spec
    ↓ SnapshotAdapter 选择每台机台快照时刻前最新有效绑定
AlgorithmAgvRelation.wafer_spec
```

最终原始映射为：

```text
equipmentid   -> machine_code
equipmentname -> machine_name
lastlinecode  -> order_code
lastlinename  -> order_name
waferspec     -> wafer_spec
createtime    -> binding_time
```

Loader 的原始记录识别、原始/标准字段冲突检查、后端校验字段投影共用同一映射表。
原始和标准 `waferspec/wafer_spec` 同时出现且值不同时继续使用现有显式冲突错误。

## 3. SnapshotAdapter

继续使用现有 `select_latest_effective_bindings`：

1. 排除快照时刻之后的记录；
2. 按机台选择最新有效时刻；
3. 保留现有订单编码、订单名称、机台编码和机台名称校验；
4. 构造最终 `AlgorithmAgvRelation` 时写入所选记录的 `wafer_spec`；
5. `AlgorithmMachineRuntime.current_order_code` 继续由最终 AGV 绑定填写；
6. 不给 runtime 增加规格字段。

同一机台最新同刻出现不同 `wafer_spec` 时不报规格冲突。为避免依赖输入顺序，
在订单编码和名称已经一致的记录中按 `wafer_spec` 排序稳定选取一条。业务保证同一
订单只有一种规格，因此这只是确定性选择，不是新增业务校验。

## 4. 净速率

在现有 `_AlgorithmNetRateContext` 中增加：

- `agv_by_machine_code`：按机台定位当前 AGV 绑定；
- 按订单从 `snapshot.agv_relations` 选择规格的内部查询。

订单规格解析规则：

1. 找出 `order_code` 相同的 AGV 关系；
2. 按 `machine_code` 升序稳定选择第一条；
3. 读取 `relation.wafer_spec`；
4. 完全找不到时抛出 `NetRateCalculationError`；
5. 不检查同订单多个规格，不回退 `line.wafer_spec`。

上下游运行机台匹配同时要求：

- `runtime.status == "running"`；
- 对应 AGV 的 `order_code` 等于当前订单；
- 对应 AGV 的 `wafer_spec` 等于当前规格；
- 产线推导出的车间等于当前车间；
- 机台主数据工序等于当前上游或下游工序。

`runtime.current_order_code` 和 `line.wafer_spec` 均不再作为净速率中的当前生产身份。
公式仍为上游产出量之和乘 2、下游投入量之和乘 2、两者相减。

## 5. 候选上下文与候选筛选

`CandidateContext` 保留全部现有索引和 `machine_context`，新增：

```text
machine_code -> AlgorithmAgvRelation
```

以及统一的机台当前 AGV 查询方法。`snapshot.agv_relations` 已由 Adapter 筛选，
这里不再次比较时间。

断料和溢满 Finder 对每台运行机台：

1. 通过 CandidateContext 获取 AGV；
2. 用 AGV `order_code` 查当前订单和产品；
3. 用 AGV `wafer_spec` 与预警规格调用现有兼容检查；
4. 用 AGV `order_code`、`order_name`、`wafer_spec` 填写候选结果；
5. 车间仍从 `machine_context` 返回的产线获取。

`AlgorithmStockoutCandidateMachine` 和 `AlgorithmOverflowCandidateMachine`
新增必填 `current_order_name`，所有生产和测试构造位置同步更新。

## 6. 错误边界

- 缺少需要计算订单的 AGV 规格：明确数据错误；
- 运行候选机台缺少当前 AGV：明确候选数据错误；
- 不新增同订单多个规格冲突；
- 不新增同机台最新同刻多个规格冲突；
- 不使用产线规格降级。

## 7. 测试与数据

测试遵循 RED-GREEN-REFACTOR，覆盖：

- 三层 Schema 和 `waferspec -> wafer_spec` 映射、字段冲突和后端投影；
- SnapshotAdapter 最新有效规格传递及 runtime 无规格字段；
- 净速率规格来源、AGV 机台筛选、缺失错误、确定性多关系选择；
- 断料正反例、溢满当前生产信息、S2 R/P 兼容；
- `main_id` 多物理 Buffer 聚合；
- FastAPI 原始请求完整链路；
- 候选结果 `current_order_name` 的所有构造位置。

共享工厂的 AGV 绑定同时支持机台、订单、订单名称、规格和绑定时间。所有原始
AGV 示例增加 `waferspec`，标准示例增加 `wafer_spec`，并同步 README 与接口文档。

## 8. Git 约束

本次在当前工作区原地实施，不执行 `git commit`、`git push`，不创建或切换分支。

