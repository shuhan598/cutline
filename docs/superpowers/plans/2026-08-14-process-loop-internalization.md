# 工序所属循环内部化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 ProcessRoute 的工序循环归属改为由算法内部按 `process_name` 生成，同时让完整路线和 Buffer 区间跨循环工作，并保持现有业务算法与正式 Response 不变。

**Architecture:** 新增一个无 sequence 的中央工序循环目录，由 BackendRequestValidator 和 SnapshotAdapter 共同调用。路线校验按 workshop 聚合；BufferProcessResolver 只用服务工序编码和后端 sequence 解析方向；MainBufferAggregator 仅将物理键方向来源切换到已解析 relation。fixture、生成器和测试同步表达新契约。

**Tech Stack:** Python 3.12、Pydantic v2、pytest、FastAPI TestClient、现有 JSON 示例生成器。

**Execution constraints:** 当前分支原地修改，不创建或切换 worktree/branch；用户明确禁止 commit 和 push，因此本计划不含提交步骤。每个生产改动都必须先有失败测试。

---

## 文件结构

新增：

- `app/core/workshop/process_loop_catalog.py`：唯一的名称标准化与工序循环查询入口。
- `tests/core/workshop/test_process_loop_catalog.py`：完整映射、大小写、trim 和未知名称测试。
- `tests/core/workshop/test_buffer_process_resolver.py`：Resolver 的跨循环、倒序、非相邻和歧义契约。

主要修改：

- `app/schemas/backend_request_schema.py`、`app/schemas/request_schema.py`：外部 Route loop Optional。
- `app/adapters/backend_request_validator.py`：未知名称、全车间路线、全车间丝网、跨循环引用和 Buffer 引用。
- `app/adapters/snapshot_adapter.py`：内部 loop 重建和车间内工序唯一键。
- `app/core/workshop/buffer_process_resolver.py`：按同车间 route sequence 定向。
- `app/core/buffer_aggregation/main_buffer_aggregator.py`：物理键使用 relation 方向。
- `tests/fixtures/v3_full_route_factory.py`：12 工序、ALD、稳定机台映射和最小 Buffer 增补。
- 相应 Schema、Adapter、Core、Integration 和 Examples 测试。
- `examples/generate_v3_scenarios.py`、`examples/generate_cutline_standard_examples.py` 及其生成物。
- 当前正式接口和字段映射文档；历史 spec/plan 保留。

## Task 1: 中央工序循环目录

**Files:**

- Create: `tests/core/workshop/test_process_loop_catalog.py`
- Create: `app/core/workshop/process_loop_catalog.py`

- [ ] **Step 1: 写完整映射和标准化失败测试**

测试使用表驱动覆盖 12 个名称，并明确只允许三个英文名称大小写兼容：

`test_resolve_process_loop_uses_approved_mapping` 的参数表逐项断言：发料机→LOOP1/一循环；制绒、硼扩、氧化→LOOP2/二循环；碱抛、POLY、退火→LOOP3/三循环；RCA→LOOP4/四循环；ALD、正膜、背膜、丝网→LOOP5/五循环。

`test_resolve_process_loop_normalizes_only_approved_english_names` 使用 `" poly "`、`"Poly"`、`" rCa "`、`" ald "`，断言返回对应规范英文名和循环。`test_resolve_process_loop_rejects_unapproved_aliases` 使用 `多晶硅沉积`、`RCA清洗`、`氧 化`、`unknown`，逐项断言 `UnknownProcessNameError` 并包含原始名称。

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/core/workshop/test_process_loop_catalog.py -q`

Expected: FAIL，因为模块尚不存在。

- [ ] **Step 3: 实现最小目录 API**

实现并只导出以下职责：

```python
@dataclass(frozen=True, slots=True)
class ProcessLoopAssignment:
    process_name: str
    loop_code: str
    loop_name: str

class UnknownProcessNameError(ValueError):
    pass

def normalize_process_name(process_name: str) -> str:
    stripped = process_name.strip()
    if stripped.casefold() in {"poly", "rca", "ald"}:
        return stripped.upper()
    return stripped

def resolve_process_loop(process_name: str) -> ProcessLoopAssignment:
    normalized = normalize_process_name(process_name)
    try:
        return _PROCESS_LOOPS[normalized]
    except KeyError as exc:
        raise UnknownProcessNameError(
            f"process_name {process_name!r} cannot be mapped to an internal loop"
        ) from exc
```

`_PROCESS_LOOPS` 只含获批 12 项，不含 sequence、别名或模糊规则。

- [ ] **Step 4: 运行目录测试并确认 GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/core/workshop/test_process_loop_catalog.py -q`

Expected: PASS。

## Task 2: 外部 Route loop Optional

**Files:**

- Modify: `tests/schemas/test_backend_request_schema.py`
- Modify: `tests/schemas/test_cutline_algorithm_request_schema.py`
- Modify: `app/schemas/backend_request_schema.py`
- Modify: `app/schemas/request_schema.py`

- [ ] **Step 1: 写两套 Schema 的失败测试**

在现有最小合法 payload 上分别删除 `process_routes[0].loop_code` 和 `loop_name`，再覆盖显式 `None` 与明显错误旧值：

新增 `test_backend_process_route_allows_omitted_compatibility_loop_fields`、`test_cutline_process_route_allows_omitted_compatibility_loop_fields` 和 `test_process_route_compatibility_loop_fields_allow_null_and_legacy_values`。每条测试都从该文件既有合法 fixture 深拷贝，只改 route loop 字段，并断言解析后的两个属性为 `None` 或保留所传兼容值。

断言模型能解析；Buffer master loop 仍保持当前必填契约。

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/schemas/test_backend_request_schema.py tests/schemas/test_cutline_algorithm_request_schema.py -q`

Expected: omission 用例因字段 required 而 FAIL。

- [ ] **Step 3: 最小修改外部 Schema**

将两套 ProcessRoute 的字段改为：

```python
loop_code: str | None = Field(
    default=None,
    description="兼容字段；内部循环由 process_name 重新生成",
)
loop_name: str | None = Field(
    default=None,
    description="兼容字段；内部循环由 process_name 重新生成",
)
```

Backend 模型可用等价的 `str | None = None`。不修改内部 `AlgorithmProcessRoute` 或 Buffer loop 类型。

- [ ] **Step 4: 运行两套 Schema 测试并确认 GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/schemas/test_backend_request_schema.py tests/schemas/test_cutline_algorithm_request_schema.py -q`

Expected: PASS。

## Task 3: Snapshot 内部重建循环

**Files:**

- Modify: `tests/adapters/test_snapshot_adapter.py`
- Modify: `app/adapters/snapshot_adapter.py`

- [ ] **Step 1: 写 Snapshot 失败测试**

新增或重写测试，证明：

新增 `test_snapshot_derives_all_process_route_loops_from_process_names`、`test_snapshot_ignores_wrong_external_loop_for_oxidation`、`test_snapshot_preserves_nonconsecutive_backend_sequences`、`test_snapshot_reports_process_code_raw_name_and_reason_for_unknown_name` 和 `test_snapshot_rejects_duplicate_process_code_in_same_workshop_even_with_different_external_loops`。

第一条覆盖 12 项映射；第二条给氧化传 `S2-LOOP01/旧循环`，断言内部仍是 `LOOP2/二循环`；第三条断言 100/200/300 原样保留；未知名称断言 `SnapshotConversionError` 文本包含 code、原始 name、`cannot be mapped`。

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/adapters/test_snapshot_adapter.py -q`

Expected: 新映射、错误 loop 忽略、未知名称和新唯一键测试 FAIL。

- [ ] **Step 3: 实现最小 Snapshot 改动**

在 `_convert_process_routes()` 中调用 `resolve_process_loop(item.process_name)`：

```python
try:
    assignment = resolve_process_loop(item.process_name)
except UnknownProcessNameError as exc:
    raise SnapshotConversionError(
        f"process_code={item.process_code!r}, process_name={item.process_name!r} "
        f"cannot be mapped to an internal loop: {exc}"
    ) from exc
```

构造 `AlgorithmProcessRoute` 时只用 `assignment.loop_code/loop_name`；其他字段原样复制。

将 `_index_process_routes()` 的键改为：

```python
key = (route.workshop_code, route.process_code)
```

错误文案不再依赖 loop，返回类型同步为 `dict[tuple[str, str], AlgorithmProcessRoute]`。

- [ ] **Step 4: 运行 Snapshot 测试并确认 GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/adapters/test_snapshot_adapter.py -q`

Expected: PASS；若旧测试锁死 same-loop、数组方向或邻接契约，只改为已批准的新期望，不放宽其他断言。

## Task 4: Validator 按 workshop 校验完整路线

**Files:**

- Modify: `tests/adapters/test_backend_request_validator.py`
- Modify: `tests/integration/test_v3_validated_api_flow.py`
- Modify: `app/adapters/backend_request_validator.py`

- [ ] **Step 1: 写 Validator 失败测试**

覆盖以下独立行为：

新增 `test_validator_reports_unknown_process_name_with_existing_issue_shape`、`test_validator_ignores_empty_or_wrong_process_route_loop_code`、`test_route_sequence_must_be_unique_within_workshop_not_loop`、`test_one_to_four_loops_do_not_each_require_silk_screen`、`test_cross_loop_route_edges_are_valid_within_one_workshop`、`test_buffer_served_process_reference_does_not_depend_on_buffer_loop` 和 `test_evaluate_maps_unknown_process_name_to_backend_data_invalid`。

跨循环链至少包含氧化→碱抛和 RCA→ALD；sequence 使用非连续值。API 测试断言 422 envelope，`/backend/validate` 单测断言 `valid=false/issues`，不改变端点状态码语义。

- [ ] **Step 2: 运行 Validator/API 测试并确认 RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/adapters/test_backend_request_validator.py tests/integration/test_v3_validated_api_flow.py -q`

Expected: 旧 per-loop 丝网、same-loop 引用、空 loop 和未知名称行为导致 FAIL。

- [ ] **Step 3: 添加目录错误 issue 和兼容空值排除**

在 `validate()` 的 route 校验路径调用共享目录。未知名称追加：

```python
self._issue(
    code="unknown_process_name",
    dataset="process_routes",
    field="process_name",
    record_key=route.process_code,
    message=(
        f"process_code={route.process_code!r}, "
        f"process_name={route.process_name!r} cannot be mapped "
        "to an internal loop"
    ),
)
```

`_validate_empty_codes()` 对 `dataset == "process_routes" and field == "loop_code"` 直接跳过；其他 code 字段规则不变。

- [ ] **Step 4: 把路线分组和辅助函数改为 workshop 级**

`_validate_routes()` 使用 `dict[str, list[tuple[int, Any]]]`：

```python
grouped[route.workshop_code].append((index, route))
```

duplicate sequence、route code 集合、引用查找、route record key、邻接错误文案和丝网检查均去掉 loop 维度。`_validate_route_adjacency()` 仍按后端 sequence 排序检查完整串行链，不新增连续数值要求。

丝网识别使用：

```python
normalize_process_name(route.process_name) == "丝网"
```

从而接受首尾 trim，但不增加别名。

- [ ] **Step 5: 删除 Buffer 引用的 loop 条件**

`_validate_served_processes()` 只建立非空 `process_code` 集合：

```python
route_codes = {
    route.process_code
    for route in request.process_routes
    if route.process_code != ""
}
```

错误只说明工序编码不存在，不提 Buffer.loop；同 workshop 唯一配对留给 Resolver。

- [ ] **Step 6: 运行 Validator/API 测试并确认 GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/adapters/test_backend_request_validator.py tests/integration/test_v3_validated_api_flow.py -q`

Expected: PASS。

## Task 5: BufferProcessResolver 按 sequence 规范定向

**Files:**

- Create: `tests/core/workshop/test_buffer_process_resolver.py`
- Modify: `app/core/workshop/buffer_process_resolver.py`
- Modify: `tests/adapters/test_snapshot_adapter.py`

- [ ] **Step 1: 写 Resolver 失败测试**

使用简单 dataclass route/buffer view 覆盖：

新增 `test_resolves_cross_loop_processes_in_same_workshop`、`test_reversed_served_codes_are_ordered_by_backend_sequence`、`test_intermediate_route_does_not_make_interval_invalid`、`test_buffer_loop_does_not_filter_route_candidates`、`test_requires_exactly_two_served_process_codes`、`test_rejects_processes_without_one_common_workshop`、`test_rejects_ambiguous_common_workshops` 和 `test_rejects_equal_sequences_without_guessing_direction`。

Adapter 端到端用氧化 sequence=40、碱抛 sequence=50、served 输入 `[碱抛, 氧化]`，断言 relation 为氧化→碱抛。

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/core/workshop/test_buffer_process_resolver.py tests/adapters/test_snapshot_adapter.py -q`

Expected: same-loop、输入顺序和邻接限制导致 FAIL。

- [ ] **Step 3: 实现最小 Resolver 算法**

从两个 Protocol 删除 loop 属性要求。按两个输入 code 分别查全量 route，组合同 workshop pair，并要求唯一 pair。对唯一 pair：

```python
if first.sequence == second.sequence:
    raise BufferProcessResolutionError(
        f"Buffer {buffer.buffer_code} served process routes have equal sequence"
    )
upstream, downstream = sorted((first, second), key=lambda route: route.sequence)
return BufferProcessResolution(
    workshop_code=upstream.workshop_code,
    upstream_process_code=upstream.process_code,
    downstream_process_code=downstream.process_code,
)
```

删除 loop 过滤、`upstream.sequence >= downstream.sequence` 的输入顺序假设和 intermediate route 扫描。缺失、不同车间和多配对错误仍明确包含 Buffer/code 上下文。

- [ ] **Step 4: 运行 Resolver/Adapter 测试并确认 GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/core/workshop/test_buffer_process_resolver.py tests/adapters/test_snapshot_adapter.py -q`

Expected: PASS。

## Task 6: Aggregator 使用 relation 的规范方向

**Files:**

- Modify: `tests/core/buffer_aggregation/test_main_buffer_aggregator.py`
- Modify: `app/core/buffer_aggregation/main_buffer_aggregator.py`

- [ ] **Step 1: 写倒序 master 的核心失败测试**

扩展测试 helper 允许 relation 自定义上下游。新增：同一个 MAIN 的 BUF-1 master 为 `[P1,P2]`、BUF-2 master 为 `[P2,P1]`，但两条 relation 都是 P1→P2；断言：

```python
assert len(batch.groups) == 1
assert group.physical_buffer_key.ordered_service_process_codes == ("P1", "P2")
assert group.buffer_codes == ("BUF-1", "BUF-2")
assert group.total_inventory == expected_inventory
assert group.total_capacity == expected_capacity
assert not any(issue.code == "service_process_conflict" for issue in batch.issues)
```

把旧“process order is key”测试改为第二条 relation 真正 P2→P1，继续证明 relation 方向不同会隔离。

- [ ] **Step 2: 运行聚合测试并确认 RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/core/buffer_aggregation/test_main_buffer_aggregator.py -q`

Expected: 倒序 master 被错误视为冲突，新增测试 FAIL。

- [ ] **Step 3: 修改唯一方向来源**

将 `_aggregate_main()` 中现有的 `process_lists.add` 调用改为：

```python
process_lists.add(
    (
        self._normalize(relation.upstream_process_code),
        self._normalize(relation.downstream_process_code),
    )
)
```

不改聚合器其他分支、模型或公式。

- [ ] **Step 4: 运行聚合及 Adapter 端到端测试并确认 GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/core/buffer_aggregation/test_main_buffer_aggregator.py tests/adapters/test_snapshot_adapter.py -q`

Expected: PASS，且 Adapter 倒序用例的 `main_buffer_batch` 物理键为规范顺序。

## Task 7: 更新受旧 loop 契约约束的单元测试数据

**Files:**

- Modify: `tests/adapters/test_snapshot_adapter.py`
- Modify: `tests/adapters/test_backend_request_validator.py`
- Modify: `tests/adapters/test_agv_order_binding_validator.py`
- Modify: `tests/service/test_cutline_algorithm_service.py`
- Modify: `tests/core/workshop/test_machine_workshop_resolver.py`
- Modify: any additional test helper identified by focused failures

- [ ] **Step 1: 运行 Adapter/Service/Workshop 相关集合，记录旧契约失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/adapters tests/service tests/core/workshop -q`

Expected: 使用 `工序一/P01/下一工序` 等未知 route 名称及 same-loop 旧断言的测试 FAIL；保存失败清单。

- [ ] **Step 2: 只修正测试输入和过期期望**

将经过正式 Adapter/Validator 的泛化 route 名称替换为获批标准名称，同时保持 process_code 不变。直接构造内部 `AlgorithmProcessRoute` 且不经过目录的纯核心测试可保留泛名。

旧断言按新契约改写：

- 同一 workshop/process 不能借不同外部 loop 重复；
- Buffer.loop 错误不再导致失败；
- served 数组倒序按 sequence 规范化；
- Buffer 服务工序非固定相邻合法；
- MachineWorkshopResolver 仍只按 process/workshop 工作，不新增 loop 限制。

不删除仍保护有效结构错误的测试。

- [ ] **Step 3: 重跑相关集合并确认 GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/adapters tests/service tests/core/workshop -q`

Expected: PASS。

## Task 8: 12 工序共享 fixture 与业务回归

**Files:**

- Modify: `tests/test_v3_fake_data_contract.py`
- Modify: `tests/fixtures/v3_full_route_factory.py`
- Modify: `tests/test_current_examples.py`
- Modify: `tests/integration/test_v3_stockout_flow.py`
- Modify: `tests/integration/test_v3_overflow_flow.py`

- [ ] **Step 1: 先更新 fixture 契约测试并确认 RED**

契约测试要求：

```python
assert len(PROCESS_CODES) == 12
assert "ALD" in PROCESS_CODES
assert MACHINE_CODES_BY_PROCESS["ALD"] == ("EA025", "EA026")
assert MACHINE_CODES_BY_PROCESS["丝网"] == ("EA021", "EA022")
```

并断言 route 的每个 sequence 是 fixture 输入生成值、每个内部 loop 由正式转换得到正确五循环，不再断言所有 route 是单 loop。Buffer relation 断言使用 route sequence 方向，不把外部 loop 当权威。

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_v3_fake_data_contract.py -q`

Expected: 缺 ALD 和旧单 loop 断言导致 FAIL。

- [ ] **Step 2: 最小更新共享 fixture**

在现有 route 顺序中将 ALD 插入氧化与正膜之间；这只是 fixture 的后端输入，不进入生产目录。显式定义旧机台稳定映射：

```python
MACHINE_CODES_BY_PROCESS = {
    "发料机": ("EA001", "EA002"),
    "制绒": ("EA003", "EA004"),
    "碱抛": ("EA005", "EA006"),
    "背膜": ("EA007", "EA008"),
    "硼扩": ("EA009", "EA010"),
    "POLY": ("EA011", "EA012"),
    "RCA": ("EA013", "EA014"),
    "退火": ("EA015", "EA016"),
    "氧化": ("EA017", "EA018"),
    "正膜": ("EA019", "EA020"),
    "丝网": ("EA021", "EA022"),
    "ALD": ("EA025", "EA026"),
}
```

保留 EA023/EA024 制绒支援机。将 310110309 最小调整为氧化→ALD，新增不冲突的 310110311 为 ALD→正膜，保留目标 310110302、310110310 及其他业务参数。

- [ ] **Step 3: 运行 fixture 契约并确认 GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_v3_fake_data_contract.py tests/test_current_examples.py -q`

Expected: PASS。

- [ ] **Step 4: 加强断料与溢满集成回归**

在现有集成测试中补齐关键 warning type/key、候选、选机、plan、Pending 数量，并继续断言无意外 Active/混料。测试只观察现有结果，不改业务期望以迁就实现。

- [ ] **Step 5: 运行完整业务回归并确认 GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_v3_stockout_flow.py tests/integration/test_v3_overflow_flow.py tests/test_current_examples.py -q`

Expected: PASS；若业务结果变化，先定位 fixture 增补是否影响既有参数，禁止修改核心公式消除失败。

## Task 9: 真实 Pending → Confirmed/Active 跨轮回归

**Files:**

- Modify: `tests/integration/test_v3_pending_cutline_flow.py`

- [ ] **Step 1: 添加真实两轮回归测试**

测试执行两次真实 evaluate：

1. 第一次使用 stockout payload，取得 Response 中 Pending 和 `persistence_state.pending_cutline_plans`；
2. 深拷贝下一轮请求并注入第一轮实际 persistence state，而非 fixture 预制 Pending；
3. 添加与所选机台和目标订单一致的真实 AGV transition；
4. 第二次 evaluate；
5. 断言原 Pending 完成/确认、出现对应 Active，且既有 mixing 只出现一次；
6. 不改 Pending/Active/Mixing 生产逻辑。

- [ ] **Step 2: 运行测试并记录结果**

Run: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_v3_pending_cutline_flow.py -q`

Expected: 回归能力若已存在则直接 PASS；若因测试拼接错误或边界内部化暴露问题，先以现有模型协议修正测试输入。只有出现由本任务生产改动造成的真实回归时，才在已批准模块范围内做最小修复。

## Task 10: 示例生成器与派生 JSON

**Files:**

- Modify: `tests/examples/test_cutline_standard_examples.py`
- Modify: `examples/generate_v3_scenarios.py`
- Modify: `examples/generate_cutline_standard_examples.py`
- Regenerate: `examples/backend_request_*.json`
- Regenerate: `examples/scenarios/*.json`
- Regenerate: `examples/cutline_standard_*.json`
- Regenerate: `examples/debug_outputs/*.json`
- Modify: `examples/README.md`

- [ ] **Step 1: 写生成物契约失败测试**

新增断言：

- 标准完整输入包含 ALD；
- 标准 ProcessRoute 名称使用 `POLY/RCA/ALD`，没有 `多晶硅沉积/RCA清洗`；
- 至少一份正式标准输入省略 route loop 字段并可成功 evaluate；
- 至少一份兼容样例保留旧/错误 route loop，内部结果仍来自名称；
- Response 顶层和既有字段集合不变。

Run: `.\.venv\Scripts\python.exe -m pytest tests/examples/test_cutline_standard_examples.py -q`

Expected: 旧标准输入缺 ALD、含本地化别名或仍依赖 loop 字段，测试 FAIL。

- [ ] **Step 2: 修改生成器源而非派生 JSON**

移除 ProcessRoute 的 POLY/RCA 中文本地化；为标准输入提供一个只删除 `process_routes[*].loop_code/loop_name` 的 helper。保留 Buffer loop 字段。兼容样例继续带旧值以证明被忽略。

标准下一轮示例改为使用同次首轮 stockout 输出的 `persistence_state.pending_cutline_plans` 构造确认输入；不改 Response 映射。

- [ ] **Step 3: 重新生成全部示例**

Run: `.\.venv\Scripts\python.exe examples/generate_v3_scenarios.py`

Run: `.\.venv\Scripts\python.exe examples/generate_cutline_standard_examples.py`

Expected: 生成器正常退出并打印所有生成路径。

- [ ] **Step 4: 运行示例测试并审查 Response 差异**

Run: `.\.venv\Scripts\python.exe -m pytest tests/examples/test_cutline_standard_examples.py tests/test_current_examples.py -q`

Expected: PASS。定向 `git diff` 确认 Response 仅有由测试时间/输入必要变化带来的值差异，没有字段新增、删除或层级变化。

## Task 11: 当前接口文档同步

**Files:**

- Modify: `README.md`
- Modify: `docs/backend-request-interface.md`
- Modify: `docs/cutline_algorithm_input_output_spec.md`
- Modify: `docs/backend-field-source-mapping.md`
- Modify: `docs/2026-07-14-algo-request-document-field-mapping.md`
- Modify: `examples/README.md`

- [ ] **Step 1: 搜索当前文档中的旧语义**

Run: `rg -n "workshop.*loop|loop_code|loop_name|同循环|相邻|丝网" README.md docs examples/README.md`

Expected: 找到 route loop 必填、按 workshop+loop、Buffer same-loop/邻接和每 loop 丝网等旧描述。

- [ ] **Step 2: 最小更新当前契约文档**

文档明确：

- route loop Optional 且忽略；
- 内部按严格 12 名目录生成；
- sequence 后端权威且可不连续；
- 完整路线和丝网按 workshop；
- Buffer 以 served codes + route sequence 定向，可跨 loop、非固定相邻；
- Buffer loop 仅兼容描述；
- Request 兼容、Response 不变、Pending persistence 下一轮回传。

历史 `docs/superpowers/specs` 和 `plans` 不追改，只由已批准设计声明 supersede。

- [ ] **Step 3: 复查文档无新增别名和固定 sequence**

Run: `rg -n "多晶硅沉积|RCA清洗|ProcessCatalog.*sequence|同循环|每个循环.*丝网" README.md docs/backend-request-interface.md docs/cutline_algorithm_input_output_spec.md docs/backend-field-source-mapping.md docs/2026-07-14-algo-request-document-field-mapping.md examples/README.md`

Expected: 不再有作为当前契约的别名、固定 sequence 或旧 loop 限制；若术语只出现在明确的兼容/废止说明中则保留上下文。

## Task 12: 全量审查与验证

**Files:**

- Review: all modified production, tests, docs and generated artifacts

- [ ] **Step 1: 运行新增专项测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/core/workshop/test_process_loop_catalog.py `
  tests/core/workshop/test_buffer_process_resolver.py `
  tests/adapters/test_snapshot_adapter.py `
  tests/adapters/test_backend_request_validator.py `
  tests/core/buffer_aggregation/test_main_buffer_aggregator.py -q
```

Expected: PASS。

- [ ] **Step 2: 运行相关模块与业务集成测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/schemas `
  tests/adapters `
  tests/core/workshop `
  tests/core/buffer_aggregation `
  tests/integration/test_v3_validated_api_flow.py `
  tests/integration/test_v3_stockout_flow.py `
  tests/integration/test_v3_overflow_flow.py `
  tests/integration/test_v3_pending_cutline_flow.py `
  tests/examples/test_cutline_standard_examples.py -q
```

Expected: PASS。

- [ ] **Step 3: 运行完整 pytest**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: 全部 PASS；只允许已知基线 Pydantic deprecation warnings，不新增 warning。

- [ ] **Step 4: 编译检查**

Run: `.\.venv\Scripts\python.exe -m compileall -q app tests examples`

Expected: exit 0，无输出。

- [ ] **Step 5: Git 完整性检查**

Run: `git diff --check`

Run: `git diff --stat`

Run: `git status --short`

Expected: 无空白错误；只显示本任务文件；无 commit、无 push。

- [ ] **Step 6: 两阶段代码审查**

先做规格符合性审查，逐项映射设计和 20 条批准边界；全部通过后再做代码质量审查。发现问题先补失败测试，再做最小修复并复审。

- [ ] **Step 7: 准备交付报告**

报告包含：基线与最终测试数字、Request 旧/新兼容、Response 是否变化、所有 loop 使用点处理、Aggregator 最小适配理由、fixture/example 变化、核心业务逻辑未改证明、`git diff --stat/status`，并明确未 commit/push。

## 计划自审

- 设计中的 20 条边界均有对应 Task 和验证命令；
- 新生产函数先由 Task 1/3/4/5/6 的失败测试驱动；
- fixture、生成器和纯回归测试不以修改核心业务实现为目标；
- Task 4 的 Route 邻接与 Task 5 的 Buffer 非固定相邻是两套不同规则，没有混淆；
- `ProcessLoopAssignment`、`normalize_process_name()`、`resolve_process_loop()` 在后续 Task 中名称一致；
- Buffer loop 未改 Schema 必填性，Route loop 才改 Optional；
- 没有固定生产 sequence、未经批准别名、Response 修改或保护模块扩张；
- 计划不含 TBD/TODO、commit、push 或分支切换步骤。
