# 可选产线输入实施计划

1. 先补三层 Schema、Loader、SnapshotAdapter 和核心模块失败测试。
2. 为 `lines`、`machine_lines` 增加空列表默认工厂。
3. 在 SnapshotAdapter 集中实现四种输入组合，删除 runtime 强制产线关系校验。
4. 删除净速率、CandidateContext、断料/溢满候选和丝网的产线索引与读取。
5. 补 FastAPI、切回、混料、S2 R/P、main_id 和 AGV 回归测试。
6. 更新生成器、标准请求、场景 JSON、README、接口和字段来源文档。
7. 全项目审计产线关键词并运行全量测试、compileall 和 `git diff --check`。

本计划不包含 commit、push、分支切换、虚拟产线生成或业务公式调整。
