# 工序所属循环内部化设计

**日期：** 2026-08-14  
**状态：** 已批准，待实施  
**范围：** ProcessRoute 输入、Snapshot 内部化、完整路线校验、Buffer 上下游解析、必要的物理 Buffer 方向适配、测试与示例  
**Git 约束：** 不切换分支，不执行 commit 或 push

## 1. 目标与权威数据

本次修改将“工序属于哪个循环”的权威来源从外部 `loop_code / loop_name` 改为算法内部的 `process_name -> loop` 目录，同时严格保持以下职责边界：

- `process_code` 是跨数据集关联工序的主键；
- `process_name` 只用于识别工序所属循环；
- `sequence` 完全来自本轮后端 ProcessRoute，算法目录不保存、生成或校验固定顺序号；
- ProcessRoute 的外部 loop 字段只保留兼容性，不参与任何内部判断；
- Buffer 的 loop 字段只保留兼容和描述，不参与服务工序解析、方向或业务区间判断。

正式 Response Schema、字段层级、Warnings、Decisions、Pending、Active、Mixing、Return 和 `persistence_state` 均保持不变。

## 2. 当前实现与修改边界

当前仓库中 loop 的行为性使用集中在以下位置：

1. 两套外部 ProcessRoute Schema 把 loop 字段定义为必填；
2. SnapshotAdapter 原样复制外部 route loop，并以 `(workshop, loop, process)` 建索引；
3. BackendRequestValidator 按 `(workshop, loop)` 拆分路线、执行丝网和上下游校验，并用 Buffer.loop 校验服务工序；
4. BufferProcessResolver 用 Buffer.loop 过滤路线、信任 served 数组顺序并要求路线固定相邻；
5. MainBufferAggregator 已接收 Resolver 生成的 relation，但物理键仍读取原始 served 数组顺序。

其余净速率、断料、溢满、候选、选机、Pending、Active、Return、Mixing 和持久化模块没有直接使用 route loop，不因本任务重写。

本设计取代 2026-07-14 输入设计中“route loop 必填、按 workshop+loop 分组、Buffer 必须同 loop”的相关条款。历史设计文档保留为历史记录；当前接口文档和映射文档更新为本设计语义。

## 3. 唯一中央工序循环目录

新增一个独立且无状态的中央目录模块，例如：

```text
app/core/workshop/process_loop_catalog.py
```

目录只保存工序名称和循环描述，不保存 sequence：

| 工序名称 | loop_code | loop_name |
|---|---|---|
| 发料机 | LOOP1 | 一循环 |
| 制绒 | LOOP2 | 二循环 |
| 硼扩 | LOOP2 | 二循环 |
| 氧化 | LOOP2 | 二循环 |
| 碱抛 | LOOP3 | 三循环 |
| POLY | LOOP3 | 三循环 |
| 退火 | LOOP3 | 三循环 |
| RCA | LOOP4 | 四循环 |
| ALD | LOOP5 | 五循环 |
| 正膜 | LOOP5 | 五循环 |
| 背膜 | LOOP5 | 五循环 |
| 丝网 | LOOP5 | 五循环 |

名称匹配规则严格限定为：

- 所有名称先做首尾空格 trim，仅用于目录查询；
- 中文名称 trim 后精确匹配，不做简繁、同义词、子串或模糊匹配；
- `POLY`、`RCA`、`ALD` trim 后仅做大小写兼容；
- 不接受 `多晶硅沉积`、`RCA清洗` 或其他未列出的别名；
- 内部 ProcessRoute 保留后端传入的原始 `process_name`，标准化结果不覆盖展示和错误定位数据。

目录提供单一解析入口，Validator 和 SnapshotAdapter 共用，避免两处映射漂移。目录错误只表达“名称无法映射”；调用方负责补充 `process_code` 和数据集上下文。

## 4. Request Schema 与 Snapshot 内部化

两条正式输入链路中的 ProcessRoute 均改为：

```python
loop_code: str | None = None
loop_name: str | None = None
```

兼容规则如下：

- 旧请求仍可传这两个字段；
- 新请求可以同时省略，也可传 `null`；
- 已传值无论正确、旧值、错误值或空字符串，均不作为校验和转换权威；
- 通用空编码检查明确跳过 `process_routes.loop_code`，避免被已忽略的空兼容值误拒绝；
- 不新增 camelCase alias，既有 snake_case 正式接口保持不变。

内部 `AlgorithmProcessRoute.loop_code / loop_name` 继续必填。SnapshotAdapter 转换每条路线时，根据原始 `process_name` 查询中央目录并写入内部 loop；`process_code`、`process_name`、`sequence` 和上下游引用均原样保留。

Snapshot 的路线唯一索引从 `(workshop_code, loop_code, process_code)` 改为 `(workshop_code, process_code)`。同一工序编码不能借不同外部 loop 在同一车间重复出现；不同车间仍可各自拥有相同工序编码。

## 5. 未知工序错误

正式 `/cutline/evaluate` 继续将完整性问题映射为 HTTP 422 `BACKEND_DATA_INVALID`；`/backend/validate` 保持当前 HTTP 200、`valid=false` 和 `issues` 的校验响应。两条入口共用现有 `BackendValidationIssue` 体系。未知名称产生可定位 issue：

```text
code = unknown_process_name
dataset = process_routes
field = process_name
record_key = 原始 process_code
message = 同时包含原始 process_code、原始 process_name、无法识别所属循环的原因
```

SnapshotAdapter 仍执行同一目录解析，以覆盖跳过完整性 Validator 的 stub 或直接 service 调用；此时沿用现有 `SnapshotConversionError`，同样包含上述三类定位信息。不得静默使用外部 loop 兜底，也不得猜测循环。

## 6. 完整工艺路线校验

ProcessRoute 从“每个 workshop+loop 一条路线”调整为“每个 workshop 一条完整路线”。Validator 按 workshop 分组后：

- 保留 sequence 的类型和下界等现有 Schema 基础约束；
- sequence 在同一 workshop 内唯一；
- 不要求 sequence 从 1 开始或连续；
- 不与任何算法固定顺序比较；
- 按后端 sequence 排序后执行既有完整串行路线的首尾和上下游引用一致性校验；
- `upstream_process_code / downstream_process_code` 在同一 workshop 完整路线中查找，允许引用跨 loop 工序；
- 每个 workshop 的完整路线恰好一个丝网，且丝网位于该 workshop 最大 sequence；
- 丝网身份使用中央目录解析后的规范工序身份判断，使首尾 trim 规则同样生效，不以未经标准化的原始字符串另做一套判断；
- LOOP1 至 LOOP4 不再分别要求丝网。

外部 route loop 不参与分组、唯一键、引用查找、丝网校验或错误定位。

## 7. Buffer 服务工序与方向解析

Buffer master 的 `loop_code / loop_name` 字段保持当前外部和内部结构，不改变必填性；它们只作为兼容和描述数据保留。

BufferProcessResolver 的新算法是：

1. 保留 `served_process_codes` 恰好两个元素等现有必要结构保护；
2. 分别按 `process_code` 查找 ProcessRoute；
3. 只接受两个工序能在同一个 workshop 中唯一组成一对的结果；
4. 以两条后端 route 的 sequence 比较方向，较小者为 upstream，较大者为 downstream；
5. 输入 served 数组顺序不参与方向判断；
6. 不使用 Buffer.loop 或 Route.loop 过滤；
7. 不要求两个工序同 loop；
8. 不检查两者之间是否存在其他 sequence，即不要求固定相邻。

无法在同一 workshop 解析、存在多个可行 workshop、缺少工序或 sequence 无法确定唯一方向时，继续使用现有 Resolver 错误体系明确失败。

`served_process_names` 继续作为输入中的描述数据；本任务不新增 code/name 一致性、固定工位或其他三层严格校验。

Validator 中 Buffer 服务工序的存在性检查同步去掉 loop 条件；最终 workshop 唯一解析仍由 Resolver 负责。

## 8. MainBufferAggregator 的最小必要适配

当前 Aggregator 同时拥有：

- 原始 `AlgorithmBufferMaster.served_process_codes`；
- Resolver 已产出的 `AlgorithmBufferProcessRelation`。

如果外部 served 数组倒序，Resolver 可以得到正确方向，但 Aggregator 仍会用原始倒序构造 `PhysicalBufferKey.ordered_service_process_codes`，导致同一物理 Buffer 被错误拆组或产生冲突。

因此只将物理键的方向来源改为：

```text
(relation.upstream_process_code, relation.downstream_process_code)
```

不改写原始 Buffer master，不改变 `PhysicalBufferKey`、`GroupKey` 的结构，也不修改 mainID 聚合口径、库存、容量、剩余容量、六项 capability、冲突隔离、净速率或断料/溢满公式。

该适配由核心单测和 Adapter 端到端测试双层保护：前者证明原始数组倒序不会拆组，后者证明 sequence 定向结果一路传入物理键。

## 9. Fixture 与 examples

共享全路线 fixture 更新为当前 12 工序并加入 ALD。sequence 仍由 fixture 作为模拟后端输入显式提供，生产目录不保存该顺序。

为控制回归范围：

- 现有工序机台编码保持稳定；
- 制绒支援机 EA023/EA024 保持不变；
- fixture 中按 `PROCESS_CODES` 数组位置自动生成机台编码的逻辑改为显式稳定映射；
- ALD 使用新的不冲突测试机台编码 EA025/EA026；
- 不因数组位置重新编号全部机台；
- 既有断料、溢满和 Pending 场景的关键 Buffer、机台、订单及业务参数尽量保持；
- 只对表达新路线和 ALD 所需的数据做最小增补。

示例必须从共享 fixture 和生成器重新生成，不手工修改派生 JSON。正式标准输入可省略 route loop 字段；保留部分携带旧值或错误值的兼容样例，用输出证明这些值被忽略。

示例生成器停止把 `POLY` 和 `RCA` 的 ProcessRoute 名称替换成未经批准的中文别名；ALD 使用 `ALD`。Response、debug 和标准输出重新生成并做差异审查。

## 10. TDD 覆盖

实施先写并观察失败测试，再做最小生产修改。覆盖至少包括：

1. 12 个工序到五个循环的精确映射；
2. `POLY/RCA/ALD` trim 和大小写兼容，中文仅 trim 后精确匹配；
3. 未知名称通过既有错误体系定位 code、原始 name 和原因；
4. 两套外部 Route Schema 均允许省略或传 null loop，Snapshot 仍生成内部 loop；
5. 错误外部 loop 被忽略，例如氧化始终生成 LOOP2/二循环；
6. 100/200/300 等非连续 sequence 原样保留，不重编号；
7. LOOP1 至 LOOP4 无丝网不报错，完整 workshop 的唯一末序丝网仍受保护；
8. 氧化到碱抛、RCA 到 ALD 等跨 loop 上下游引用合法；
9. Buffer 跨 loop 服务氧化和碱抛并正确解析；
10. served 数组倒序且 sequence 为 40/50 时仍解析正确，存在中间工序也不因非相邻失败；
11. 完整断料场景的 warning、candidate、selection、plan 和 Pending 回归；
12. 完整溢满场景的 warning、candidate、selection、plan 和 Pending 回归；
13. 首轮实际输出的 Pending/persistence_state 注入下一轮，真实 AGV 确认后形成 Confirmed/Active，并保持既有 mixing 行为。

另保留正式 Response 字段集、Mapper、OpenAPI 和示例输出结构冻结测试。

## 11. 非目标与保护清单

本任务不修改：

- 净速率、断料耗尽时间或溢满时间公式；
- Stockout/Overflow Warning 判定；
- Candidate Finder 或 MachineSelectionEvaluator 业务规则；
- Pending、ConfirmedTransition、Active、Return、Mixing 或 PersistenceStateBuilder 业务语义；
- mainID 聚合口径、GroupKey、能力矩阵或冲突隔离规则；
- 正式 Response、甲方预警展示、丝网输出、docNo 或推送字段；
- Buffer code/name 一致性、固定邻接或固定位置等新严格校验。

若实施中的测试显示还需触及保护模块，必须先证明它是 loop 来源变化的直接必要适配，并将原因和最小改动补充到本设计；否则不扩大范围。

## 12. 验证与交付

依次执行并记录：

1. 新增专项测试；
2. Schema、Validator、Snapshot、Resolver、Aggregator 相关模块测试；
3. 断料、溢满和跨轮集成回归；
4. 完整 `pytest`；
5. `python -m compileall -q app tests examples`；
6. `git diff --check`；
7. `git diff --stat`；
8. `git status --short`。

交付报告明确列出 Request 兼容方式、Response 是否变化、每个 loop 使用点的处理、Aggregator 最小适配原因，以及受保护业务模块是否发生逻辑改动。全程不 commit、不 push。

## 13. 设计自审记录

2026-08-14 按批准边界完成实现前自审：

- 映射表恰含获批的 12 个标准名称和五个循环，没有 sequence 或额外别名；
- 外部 Route loop 的 Optional/忽略语义与内部 Route loop 的必填/重建语义已分离；
- sequence 仅保留后端原值及车间内基础唯一性，不含起始值、连续性或目录顺序约束；
- Route 的完整车间语义、跨 loop 引用和全车间丝网约束没有与 Buffer 的“非固定相邻”规则混淆；
- Buffer.loop 已从合法性、方向和业务区间中排除，Resolver 的必要失败边界仍然明确；
- Aggregator 改动被限制为物理键方向来源，未扩展到聚合口径、能力或计算公式；
- 未知名称在正式 Validator 和直接 Snapshot 两条入口都有明确错误路径；
- fixture、生成器、13 类测试、真实 Pending 跨轮和正式 Response 冻结均有对应验证项；
- 设计中没有待定占位符，也没有授权 commit、push、分支切换或无关重构。
