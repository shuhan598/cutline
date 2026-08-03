# 删除无来源机台实时数量字段设计

## 目标

从后端原始请求、标准化算法请求和算法内部快照中硬删除三个无真实来源且无算法读取的数量字段，同时保留 `input_quantity`、`output_quantity` 及现有 30 分钟统计口径。

## 现状结论

- `BackendMachineRealtime` 定义 `completed_quantity`，Loader 会临时删除 `period_quantity` 后再校验。
- `MachineRealtimeRequest` 同时定义 `completed_quantity` 与 `period_quantity`。
- `SnapshotAdapter` 仅把 `period_quantity` 投影为 `AlgorithmMachineRuntime.period_quantity_30m`。
- `app/core` 和 `app/service` 没有读取上述三个字段；核心算法读取的是 `input_quantity_30m` 与 `output_quantity_30m`。
- 净速率、候选机台贡献产能和丝网输出速率均把最近 30 分钟数量乘以 2 换算为小时速率。

## 方案比较

1. 硬删除（采用）：从全部 Schema、Loader、Adapter、Fixture、JSON 和文档删除；旧字段由现有 `extra="forbid"` 拒绝。契合正式契约，不保留虚假兼容性。
2. Loader 忽略旧字段（拒绝）：上线更平滑，但会保留专门兼容层，违反本次要求。
3. 仅从内部快照删除（拒绝）：核心算法虽不受影响，但外部接口仍会宣称后端必须提供无来源字段。

## 数据流

删除后调用链为：

`JSON machine_realtime(input_quantity, output_quantity)` → `BackendRequestLoader` → `CutlineAlgorithmRequest` → 完整性校验 → `SnapshotAdapter` → `AlgorithmMachineRuntime(input_quantity_30m, output_quantity_30m)` → Pipeline。

Loader 继续保留与本任务无关的 AGV 字段归一化和 `out_time` 过渡处理，不再对本次删除字段做读取、删除或补值。

## 错误与兼容行为

后端原始模型、标准化请求模型均保持 `extra="forbid"`。因此旧 JSON 携带 `completed_quantity` 或 `period_quantity` 时：

- `/cutline/evaluate` 返回 HTTP 422，错误类型为 `extra_forbidden` 并进入既有 `BACKEND_DATA_INVALID` 错误封装；
- `/backend/validate` 返回 FastAPI/Pydantic HTTP 422；
- Loader 直接抛出 Pydantic `ValidationError`，不再静默删除。

不修改全局 extra 策略，不增加别名、默认值或兼容属性。

## 测试设计

- 请求 Schema 与内部 Schema 的 `model_fields` 不包含被删字段。
- 仅提供上料/出料数量的后端模型、Loader、完整性校验、SnapshotAdapter 和正式 API 均成功。
- OpenAPI 对应机台实时模型不暴露被删字段。
- 旧字段按当前严格模型行为被拒绝。
- 全部标准输入与场景 JSON 的 `machine_realtime` 记录无残留。
- 现有断料、溢满、候选、Pending、Active、混料、切回和丝网测试继续验证业务结果未改变。

## 范围边界

不修改任何核心算法公式、统计窗口、业务判断、输出 Schema、持久化状态、工艺路线规则或全局 Pydantic 配置。

