# mainID 物理 Buffer + 多订单库存 + 同池溢满平衡设计

## 目标

将 `main_id` 定义为唯一的物理 Buffer 身份；同一 `main_id` 下允许多个当前有效订单，库存按订单聚合、产能速率按 `(main_id, order_code)` 唯一计算，断料保持订单粒度，溢满改为物理 `main_id` 粒度，并且溢满自动切线只能在同一 `main_id` 的订单之间平衡。

## 现状与约束

- 现有 `MainBufferGroup` 同时承载物理容量和单订单状态，且 `multiple_orders_in_main` 会使整个 main 失效。
- `PhysicalBufferKey(workshop, ordered_processes)` 当前被用于跨 main 索引和 target 搜索；本轮仅保留为工艺区间诊断/兼容索引，不再定义物理身份。
- `SnapshotReferenceIndex` 对产品名到多个当前订单的映射在构建全局索引时直接失败；该严格性必须继续用于 AGV/机台等唯一引用，Buffer realtime 映射则改为 main 局部 issue。
- Request/Response 顶层结构、断料/溢满数学公式、`<= lead` 风险边界、Pending/Active/Return/Mixing/Silk 业务语义均冻结。

## 内部模型

`PhysicalMainBufferState` 表示一个 main 的物理状态：`main_id`、工艺区间、真实 `buffer_codes`、去重后的 `total_capacity`、订单库存总和、总 rate、代表 buffer code 与 capability。`OrderBufferState` 表示 `(main_id, order_code)` 子状态：产品、库存、唯一 signed rate 及其机器明细。现有 `MainBufferGroup` 保留为兼容视图/订单索引，但不再代表完整物理容量副本；Batch 新增按 main 和 `(main, order)` 的索引。

## 聚合与映射

1. 按 realtime `main_id` 分桶；同 main 的多个 realtime row 汇总为一个物理状态。
2. `buffer_id` 仅用于 Buffer Master、容量、工艺解析、代表值和跨轮 lookup；同订单多 buffer 的库存相加，机器扫描只执行一次。
3. `bound_source_name -> product -> 当前有效 order`。无订单或多订单不猜测，生成 `order_mapping_not_found/ambiguous` main 局部 issue；其他 main 继续计算。
4. relation 冲突、Master 缺失、容量缺失等仍只隔离对应 main。不同 main 即使 PhysicalBufferKey 相同也保持独立，不再生成跨 main duplicate-order 禁用逻辑。

## Rate、断料与溢满

- NetRate 先输出每个 `(main_id, order_code)` 的唯一 signed rate，machine 必须同时匹配 process、order、route/process workshop 和 running；同订单多 buffer 不重复计入。
- Depletion/Stockout 使用订单子状态库存和 rate，粒度为 `(main_id, order_code)`，沿用现有公式及 lead 边界。
- OverflowTime 按 main 汇总订单库存和 rate，容量为 unique buffer id capacity 之和，每个 main 最多一个物理结果，`order_growth_details` 保留各订单贡献。

## 同池溢满候选与虚拟评估

Overflow source 按正增长 rate 降序选择；target 只来自同一 main 的其他订单，按 rate 升序排序。只有兼容性通过的 machine 才形成 candidate。每选择一台 machine，重新计算所有订单 rate、main 总 rate、main overflow time，并检查 source depletion；只有 main 总增长严格下降、最终退出 overflow 风险窗口且不制造 source stockout 的方案才可自动计划。无安全方案返回 ManualIntervention，不创建 Pending；安全方案仍走 Plan → Pending → Confirmed → Active。

## 错误与兼容

正式 Response schema 不增加字段；内部 `GroupKey`、`representative_buffer_code`、Pending/Active lookup 继续可用。`lines/machine_lines` 不进入权威 workshop/wafer_spec 解析，分别继续使用 route/process 与最新 AGV binding。

## 验证策略

先增加聚合、局部 order mapping、rate 去重、物理 overflow、同 main target、跨 main 禁止、虚拟 improvement 和状态闭环测试，再逐步改造 aggregator、NetRate、OverflowTime/Finder、MachineSelectionEvaluator，最后运行相关模块、compileall、diff 检查和完整 pytest（记录环境依赖导致的基线问题）。
