# Pending 跨轮确认与持久化状态设计

**日期：** 2026-08-02  
**状态：** 已批准实施（依据本轮用户需求）

## 目标与不变量

切线推荐只是候选方案，不代表现场已经执行。首轮风险计算只产生业务预警、切线方案和一个可回传的 `PendingCutlinePlan`；后续轮次只有在 AGV 历史中观察到符合方案基线、范围和时间窗的真实订单绑定变化后，才创建 `ActiveCutlineEvent`。混料追溯与切回跟踪均以该真实事件为入口。

本次改造保持以下业务不变量：

- 断料/溢满计算、逐台选机、S2 P/R 兼容、丝网及切回三条件公式不变。
- `CutlineAlgorithmResponse` 的现有业务字段、字段含义和映射不变。
- 算法服务仍不持有进程内状态；后端持久化并在下一轮回传状态。
- AGV `createtime` 仅表示算法首次观察到绑定变化的时间，不宣称等于现场物理切线时刻。
- 禁止用机台数量变化代替逐台绑定集合变化，也禁止用 `lastlinename` 决定当前订单。

## 当前实现差距

仓库已经具备 Pending 请求模型、窗口化 AGV 历史、确认检测器和 Active 事件合并，但闭环尚未完成：

1. Pending 只能接收 `PENDING`/`PARTIALLY_CONFIRMED`，没有完整终态，也没有算法侧首轮创建工厂。
2. Pipeline 丢弃检测器的方案评估结果，响应没有可供后端保存的 Pending/Active 完整状态。
3. 混料仍由当轮推荐方案直接触发，导致“推荐即执行”。
4. Active 回传时状态被重置，已经给过的切回建议可能在后续轮次重复。
5. 当前订单索引没有限定为唯一活动订单。
6. 多 Pending 对同一物理变化的竞争存在静默优先级，与“歧义必须报错”冲突。

## 响应兼容与状态分层

保留 `CutlineAlgorithmResponse` 作为纯业务响应，不向其中塞入生命周期字段。新增 `CutlineEvaluateResponse`，继承所有原业务字段并仅增加一个明确隔离的 `persistence_state`：

```text
CutlineEvaluateResponse
├── 原 CutlineAlgorithmResponse 全部业务字段（原语义不变）
└── persistence_state
    ├── pending_cutline_plans
    ├── active_cutline_events
    ├── expired_pending_plan_ids
    ├── completed_pending_plan_ids
    ├── return_suggested_event_ids
    ├── mixed_cutline_event_ids
    └── new_mixing_trace_records
```

`/cutline/evaluate` 返回增强响应；兼容 Stub 继续声明并投影为原 `CutlineAlgorithmResponse`。这样旧业务模型保持严格且可单独验证，新接口又能在每轮给出后端下一次请求所需的完整状态。

请求新增两个独立空列表默认值：`return_suggested_event_ids` 和 `mixed_cutline_event_ids`。它们是后端回传的幂等水位，不是进程内缓存。

## Pending 领域模型与状态机

`PendingCutlinePlanStatus` 是字符串枚举：

```text
PENDING -> PARTIALLY_CONFIRMED -> CONFIRMED -> RETURN_SUGGESTED
   |              |
   +--------------+-------------------------> EXPIRED
```

- `PENDING`：未确认任何所需机台。
- `PARTIALLY_CONFIRMED`：确认数量大于零但小于方案所需变化数。
- `CONFIRMED`：所需逐台绑定变化全部确认，真实 Active 已创建。
- `EXPIRED`：窗口结束且仍未全部确认；已经确认的 Active 不回滚。
- `RETURN_SUGGESTED`：该方案对应的 Active 已产生切回建议。

终态方案再次回传时安全幂等，不再认领新变化。Pending 增加 `process_code`、源/目标订单与产品摘要、`candidate_machine_codes`。每台候选的丰富上下文仍是权威数据，摘要字段在多机台内容不一致时允许为空。

`BaselineMachineBinding` 保存标准机台号、基线订单/产品、工序、车间、`machine_status` 和 `observed_at`。旧输入字段 `agv_record_time` 仅作为兼容校验别名；输出统一为 `observed_at`。基线是在方案创建时观察到的状态，因此要求 `observed_at <= created_at`。

## 首轮 Pending 创建

新增 `PendingCutlinePlanFactory`，只处理自动切线方案，人工介入结果不会创建 Pending。工厂在当轮 Snapshot 上完成：

1. 以 `snapshot.current_time` 作为 `created_at`，按配置的 30 分钟得到 `expire_at`。
2. 精确解析方案车间和输出侧工序，保存该范围内所有可观察机台的最新 AGV 基线与运行状态。
3. 以运行中且绑定监控订单的机台集合生成 `before_machine_codes`，集合长度决定 `before_machine_count`。
4. 将方案逐台选择结果转换为候选明细，并显式保存候选标准机台号集合。
5. 任一机台、订单、产品、Buffer、工序缺失或映射不唯一时，产生具名的 `pending_cutline_creation` 错误；业务预警和方案仍正常输出。

同一轮及跨轮按业务键抑制仍处于有效期的等价 Pending，不抑制风险预警本身。

## 真实变化确认

确认窗严格为 `(created_at, expire_at]`，且记录不能晚于本轮 `snapshot.current_time`。检测器必须先扫描边界记录，再判定过期，保证正好发生在 `expire_at` 的变化可被确认。

当前订单解析链固定为：

```text
AGV.linename（精确 product_name）
  -> 唯一产品
  -> 唯一活动订单（RUNNING / OPEN / 生产中）
```

找不到或多于一个活动订单时明确报错。`lastlinename` 仅在非空时用于校验是否与保存的基线产品一致，绝不用于选择当前订单。

确认依据是机台绑定集合：

- 推荐机台必须从保存的基线订单变到保存的目标订单。
- 客户自选机台必须满足保存的车间/工序/兼容约束；断料严格为“其他订单 -> 监控目标订单”，溢满严格为“监控源订单 -> 可承接的其他订单”。
- 机台总数只作为诊断信息。即使一进一出导致总数不变，两个真实变化仍按各自绑定确认。
- Active 记录 `is_recommended_candidate`，区分算法推荐与客户自选。

物理变化去重键至少包含 `plan_id + warning_id + machine_code + baseline_order_code + current_order_code + observed_at`。同一物理变化若能被多个开放 Pending 认领，整批确认报包含全部 plan id、机台和观察时间的冲突，不做推荐优先或首次命中猜测。

## Active、混料与切回闭环

确认后的转换通过现有 Tracker 生成稳定 Active，`cutline_start_time` 使用 AGV `observed_at`。输入 Active 的 `status` 和内部追踪元数据必须原样回传，不能在 Adapter 中强制重置为 `active`。

混料入口改为 `calculate_for_event`：

- 只处理已确认并合并成功的真实 Active；首轮方案不再生成混料。
- 切线基准时间改用事件的 `cutline_start_time`，不再额外叠加“计划执行延迟”。
- 残余片数、AGV 配送、工艺时间、篮数、S2 和配方公式全部复用原实现。
- 成功后将 event id 加入累计 `mixed_cutline_event_ids`；同一事件跨轮不重复，同一机台后续新事件仍可生成。
- 计算失败不推进幂等水位，数据修正后可以重试。

切回评估继续使用原三条件和计时规则，但只处理未出现在累计 `return_suggested_event_ids` 且状态仍为 active 的事件。产生建议后同轮更新 Active 状态，并把 event id 加入累计水位；后端原样回传后不会重复建议。切回计时起点始终是真实观察时间。

## 每轮持久化输出

Pipeline 汇总输入状态、方案评估、新建 Pending、新建/更新 Active、混料及切回结果，生成下一轮的完整状态：

- 开放、部分确认及终态 Pending（终态至少在本轮明确输出，同时分别列出完成/过期 id）。
- 合并并应用同轮切回状态后的完整 Active 集合。
- 累计的切回/混料幂等水位。
- 本轮新生成的混料记录。

后端保存 `persistence_state` 并在下一轮把对应请求字段回传。算法服务不访问数据库，也不读取服务器墙钟。

## 错误与验证策略

测试先覆盖模型状态机、工厂基线、活动订单唯一性、窗边界、跨 Pending 歧义、首轮无混料、确认轮单次混料、切回单次建议和响应往返，再修改生产代码。验证顺序为聚焦测试、相关回归、API/示例、静态检查、全量 pytest、`compileall`、`git diff --check` 和独立审查。用户明确禁止 commit/push，本次只保留工作区改动。
