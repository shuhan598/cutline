# mainID 物理 Buffer + 多订单库存 + 同池溢满平衡 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 mainID 成为物理 Buffer，支持同 main 多订单库存/速率，并将 overflow 平衡限制在同 main 内。

**Architecture:** 在现有兼容视图上增加物理 main 状态和订单子状态索引；聚合阶段完成局部映射与容量去重，NetRate 产出订单级唯一 rate，OverflowTime/Finder/Evaluator 使用 main 物理状态和同 main 订单候选。正式 Request/Response 与既有状态机保持不变。

**Tech Stack:** Python 3.13, dataclasses, Pydantic v2, pytest。

---

### Task 1: 固化模型与聚合索引

**Files:** `app/core/buffer_aggregation/models.py`, `app/core/buffer_aggregation/main_buffer_aggregator.py`, `tests/core/buffer_aggregation/test_main_buffer_aggregator.py`

- [ ] 写失败测试：同 main 多订单合法、同订单多 buffer 库存相加、unique capacity、重复 realtime 不重复容量、不同 main 相同 PhysicalBufferKey 独立、relation 冲突局部 issue。
- [ ] 增加 PhysicalMainBufferState/OrderBufferState 及 Batch 的 main/order 索引，保留 GroupKey 兼容 lookup。
- [ ] 重写 aggregator：按 main 聚合物理层，按 `(main, order)` 聚合子状态；去除 `multiple_orders_in_main` 和跨 main PhysicalBufferKey 禁用。
- [ ] 运行聚合测试并修正仅由新语义导致的旧断言。

### Task 2: 局部 Buffer→Product→Order 映射

**Files:** `app/adapters/snapshot_reference_index.py`, `app/adapters/snapshot_adapter.py`, `tests/adapters/test_snapshot_reference_index.py`, `tests/adapters/test_snapshot_adapter.py`

- [ ] 写失败测试：产品无当前订单/多个当前订单只隔离对应 main，其他 main 正常；AGV/机台唯一引用仍严格失败。
- [ ] 保留 CurrentOrderIndex 的严格 `resolve_product_name`，新增候选查询；Buffer realtime 转换对异常跳过并由 aggregator 生成定位 issue。
- [ ] 验证正式 errors schema 和请求顶层结构不变。

### Task 3: 订单级 NetRate 与 Stockout

**Files:** `app/core/net_rate/net_rate_calculator.py`, `app/core/prediction_time/depletion_time/depletion_time_calculator.py`, tests under `tests/core/net_rate`, `tests/core/prediction_time`, `tests/core/warning`

- [ ] 写失败测试：同订单多 buffer rate 不重复；同工序不同订单机台隔离；Resolver 两端之外的工序不计入；A/B 独立 stockout。
- [ ] 从 order child state 建立唯一 machine set/rate，补齐 main/order 索引 lookup。
- [ ] 运行相关测试，确认公式和 lead 边界未变。

### Task 4: 物理 main Overflow

**Files:** `app/core/prediction_time/overflow_time/overflow_time_calculator.py`, `app/core/warning/overflow_warning.py`, tests under `tests/core/prediction_time` and `tests/core/warning`

- [ ] 写失败测试：同 main 多订单只产生一个 overflow，库存/rate/capacity 使用物理总量，order details 保留贡献。
- [ ] 按 main 汇总订单 rate，容量按 unique buffer id，保持公式和 Response 字段。
- [ ] 运行 overflow 测试。

### Task 5: 同 main Overflow Candidate 与虚拟安全评估

**Files:** `app/core/candidate_machine/overflow_candidate_finder.py`, `app/core/cutline_plan/machine_selection_evaluator.py`, relevant candidate/plan tests

- [ ] 写失败测试：跨 main 永不 target；同 main target 按 rate 升序；source 按正增长降序；单订单 ManualIntervention；每台 machine 后 main rate 严格下降并重新排序/重算风险。
- [ ] 将 target 索引改为 `group_keys_by_main_id`/order state，保留 compatibility 规则；Evaluator 用 main aggregate overflow 和 source order depletion 判断。
- [ ] 运行候选与选择测试，确认 stockout 分支不改业务规则。

### Task 6: 状态、兼容 lookup 与回归

**Files:** `app/core/cutline_confirmation`, `app/core/return_judge`, `app/core/mixing_trace`, `app/core/silk_screen`, integration/service tests as needed

- [ ] 写/调整同 main Pending→Confirmed→Active 与 stockout 回归测试。
- [ ] 仅适配内部 key lookup；不改变 Return/Mixing/Silk 业务语义。
- [ ] 验证 lines/machine_lines 可省略、AGV wafer_spec 与 route/process workshop 权威性。

### Task 7: 全量验证与报告

- [ ] 运行专项与相关模块 pytest。
- [ ] 运行 `pytest`、`python -m compileall -q app tests examples`、`git diff --check`。
- [ ] 输出 `git diff --stat`, `git diff --name-status`, `git status --short`；不 add/commit/push。
