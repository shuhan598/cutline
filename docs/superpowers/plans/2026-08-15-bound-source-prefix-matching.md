# Bound Source Prefix Matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 保留后端原始字段，并在算法内部固定取 `bound_source_name` 第一个英文连字符前的内容用于订单映射。

**Architecture:** `app.utils.buffer_binding` 提供无状态的首段截取函数。SnapshotAdapter 和 MainBufferAggregator 共享该函数，现有订单唯一性检查继续负责 not-found 和 ambiguous 结果。

**Tech Stack:** Python 3.13、Pydantic、pytest、Pyright

---

### Task 1: 用失败测试固定匹配语义

**Files:**
- Modify: `tests/core/buffer_aggregation/test_main_buffer_aggregator.py`
- Modify: `tests/adapters/test_snapshot_adapter.py`

- [ ] 添加实际示例后缀映射测试，断言库存归属标准产品订单且无 mapping issue。
- [ ] 通过聚合公开行为证明算法固定选择第一个连字符前的内容。
- [ ] 运行新增测试，确认因当前仅支持精确匹配而失败。

### Task 2: 实现共享归一化

**Files:**
- Modify: `app/utils/buffer_binding.py`
- Modify: `app/adapters/snapshot_adapter.py`
- Modify: `app/core/buffer_aggregation/main_buffer_aggregator.py`

- [ ] 简化 `normalize_bound_source_product_name`，只取第一个英文连字符前的内容；中文 docstring 说明规则。
- [ ] SnapshotAdapter 只对 `buffer_realtime.bound_source_name` 使用归一化结果。
- [ ] MainBufferAggregator 使用相同归一化结果执行现有订单映射。
- [ ] CurrentOrderIndex 和 AGV 产品名保持精确匹配。
- [ ] 运行新增测试并确认通过。

### Task 3: 完整回归

**Files:**
- No additional file changes.

- [ ] 运行 adapters、buffer aggregation 和 utils 专项测试。
- [ ] 运行完整 `pytest`。
- [ ] 运行 Pyright 和 `python -m compileall -q app tests examples`。
- [ ] 使用实际示例格式执行 `/cutline/evaluate` 冒烟测试。
- [ ] 运行 `git diff --check` 和 `git status --short`。
- [ ] 不执行 `git add`、`git commit` 或 `git push`。
