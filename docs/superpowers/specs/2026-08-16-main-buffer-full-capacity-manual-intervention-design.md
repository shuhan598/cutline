# 物理 Main Buffer 满仓人工干预设计

## 目标

物理 Main Buffer 当前总库存达到或超过总容量时，无论库存增长率为正、零或负，当前满仓风险都不能被判定为已经解除。算法应输出 `manual_intervention`，原因码为 `current_buffer_already_over_capacity`，而不是生成 `selected_machines=[]` 的自动方案。

## 当前问题

`MachineSelectionEvaluator._physical_main_resolved()` 先以 `total_rate <= 0` 判定风险解除。满仓且所有机台停机时，总增长率为零，因此选择结果错误地携带 `risk_resolved=True`。`CutlinePlanBuilder` 随后生成空自动方案，`PendingCutlinePlanFactory` 又因自动方案没有机台而报错。

## 设计

只调整物理 main 路径的风险判定顺序：

1. 读取 `PhysicalMainBufferState`。
2. 若容量可用且 `total_inventory >= total_capacity`，立即返回未解除。
3. 仅在未满仓时，继续使用现有规则：总增长率不大于零，或预计溢满时间严格大于预警提前量，才视为风险解除。

不修改 Warning、PlanBuilder、Pending、Response Schema 或原因码。现有 `_overflow_failure_reason()` 会把满仓未解除结果映射为 `current_buffer_already_over_capacity`，PlanBuilder 会自然生成 `manual_intervention`。

## 边界

- 库存等于容量：未解除。
- 库存超过容量：未解除。
- 库存低于容量且增长率不大于零：保持已解除。
- 库存低于容量且预计溢满时间大于提前量：保持已解除。
- 正常选中机台并把未满仓风险移出窗口：继续生成自动方案。

## 验证

新增物理 main 回归测试，覆盖满仓、零增长、无候选时选择结果未解除且原因正确，并断言 PlanBuilder 输出人工干预。运行 cutline plan 专项测试、service 决策流测试，并用当前 `request-to-cutline-current-format.json` 验证正式接口返回人工干预且不再产生空方案 Pending 错误。
