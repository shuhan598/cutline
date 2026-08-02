# Pending 跨轮确认闭环实施计划

> 使用 Superpowers test-driven-development 执行。每一阶段都先写会因缺失行为而失败的测试，再写最小生产实现；用户明确禁止 commit/push。

**目标：** 推荐轮创建可持久化 Pending；确认轮由真实 AGV 变化创建 Active；只有 Active 触发一次混料并进入一次性切回建议闭环。

**架构：** 保持纯业务 `CutlineAlgorithmResponse`，为主评估接口增加只含 `persistence_state` 的增强响应；状态由请求回传、Pipeline 归并、响应输出，不引入服务端缓存。

## Task 1：契约与状态机

**修改：**

- `app/schemas/pending_cutline_schema.py`
- `app/schemas/request_schema.py`
- `app/schemas/common_schema.py`
- `app/schemas/result_schema.py`
- `app/schemas/response_schema.py`
- 对应 `tests/schemas/`

1. 写 Pending 五状态、终态幂等、基线 `machine_status/observed_at`、新上下文字段的失败测试。
2. 写 Active 状态和请求幂等水位独立默认值测试。
3. 写增强响应/持久化状态严格模型及原业务响应字段不变测试。
4. 运行聚焦测试确认 RED，再实现并确认 GREEN。

## Task 2：活动订单解析与 Pending 工厂

**新增/修改：**

- `app/adapters/snapshot_reference_index.py`
- `app/core/cutline_confirmation/pending_cutline_plan_factory.py`
- `app/core/cutline_confirmation/__init__.py`
- `tests/core/cutline_confirmation/test_pending_cutline_plan_factory.py`
- Adapter 相关测试

1. 写“只允许唯一活动订单”的正常、无活动订单、多个活动订单测试。
2. 写断料/溢满方案转 Pending、全范围基线、运行集合、候选上下文和失败隔离测试。
3. 确认 RED 后实现活动状态过滤和工厂；不改变现有方案计算。

## Task 3：检测生命周期与冲突

**修改：**

- `app/adapters/pending_cutline_plan_adapter.py`
- `app/core/cutline_confirmation/pending_cutline_detector.py`
- `tests/adapters/test_pending_cutline_plan_adapter.py`
- `tests/core/cutline_confirmation/test_pending_cutline_detector.py`

1. 写五状态往返、创建时基线、完成/过期终态安全重放测试。
2. 把跨 Pending 推荐优先测试改为同一物理变化歧义报错。
3. 补强精确窗 `(created_at, expire_at]`、边界先扫描、全业务去重键、客户自选方向测试。
4. RED 后统一使用枚举和 `CONFIRMED`，删除静默认领优先级。

## Task 4：Pipeline 持久化归并

**新增/修改：**

- `app/service/persistence_state_builder.py`
- `app/service/cutline_pipeline.py`
- `app/mappers/algorithm_response_mapper.py`
- `app/service/cutline_service.py`
- `app/api/cutline_api.py`
- 对应 Service/Mapper/API 测试

1. 写首轮返回 Pending、确认轮更新状态、过期/完成 id 和完整 Active 输出测试。
2. 写输入终态和 Active 状态跨轮原样保持、累计幂等水位测试。
3. RED 后加入工厂、方案评估归并和 persistence builder。
4. Mapper 输出增强响应；Stub 仍投影原业务响应。

## Task 5：Active 驱动单次混料

**修改：**

- `app/core/mixing_trace/mixing_trace_calculator.py`
- `app/service/cutline_pipeline.py`
- `tests/core/mixing_trace/test_mixing_trace_calculator.py`
- `tests/service/test_algorithm_pipeline_complete_flow.py`
- `tests/integration/test_v3_pending_cutline_flow.py`

1. 先反转旧断言：首轮有方案但无混料。
2. 写确认 Active 以 observed time 计算、同事件重放不重复、同机台新事件可再次生成测试。
3. RED 后抽取共享公式上下文并新增 event 入口；生产 Pipeline 删除 decision 入口。

## Task 6：切回幂等闭环

**修改：**

- `app/adapters/snapshot_adapter.py`
- `app/service/cutline_pipeline.py`
- `app/service/persistence_state_builder.py`
- Return/Service/Integration 测试

1. 写已建议 id/status 回传后不重复建议、其他事件正常评估、计时仍从 observed time 开始的测试。
2. RED 后保留 Active status，评估前过滤累计水位，输出累计 id 并推进 Pending 至 `RETURN_SUGGESTED`。
3. 保持 ReturnEvaluator 三条件实现不变。

## Task 7：文档、示例与完整验证

**修改：** README、后端接口文档、字段映射、V3 示例和生成脚本。

1. 更新首轮/确认轮/切回轮的请求响应样例和后端持久化职责。
2. 运行所有新增聚焦测试及旧警告、选机、S2、丝网、混料和 Return 回归。
3. 运行 API、示例校验、项目配置的静态检查、`python -m compileall -q app tests examples`、全量 `pytest -q`、`git diff --check`。
4. 发起独立规格/代码审查；对高、中风险结论补 RED 测试后修复并复验。
5. 最终按用户要求的 13 项顺序报告；明确未 commit/push。
