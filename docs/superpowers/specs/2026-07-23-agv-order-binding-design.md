# AGV 当前订单绑定接入设计

**日期：** 2026-07-23  
**状态：** 已批准，按方案 A 实施  
**范围：** 外部请求 Schema、BackendRequestLoader、Backend Validator、SnapshotAdapter、FastAPI 接口、测试、fixture、示例和输入文档

## 1. 目标和边界

机台实时数据不再携带订单。甲方 AGV 原始记录通过统一接入映射提供机台当前订单，SnapshotAdapter 选择快照时刻前的最新有效绑定并写入 `AlgorithmMachineRuntime.current_order_code`。机台工序继续来自 `machine_master.process_code/process_name`。

本次不修改：

- `app/core/` 下的业务公式和规则；
- Buffer mainID、bufferID、库存、容量和工序关系聚合；
- 断料、溢满、候选机台、切线、切回、丝网和混料算法；
- 对外响应 Schema。

## 2. 修改前调用链

```text
FastAPI 直接解析 CutlineAlgorithmRequest
→ CutlineService
→ SnapshotAdapter
→ machine_realtime.order_code
→ AlgorithmMachineRuntime.current_order_code
→ orders.product_code
→ products
→ CutlinePipeline
```

`/backend/validate` 当前单独通过 `BackendRequestLoader.load_dict()` 解析 `BackendAlgorithmRequest`。

## 3. 修改后调用链

```text
原始 JSON
→ BackendRequestLoader.normalize_payload()
→ CutlineAlgorithmRequest
→ CutlineService
→ SnapshotAdapter
→ 选择 snapshot_time 前每台机台最新 AGV 绑定
→ AlgorithmMachineRuntime.current_order_code
→ orders.product_code
→ products
→ CutlinePipeline
```

`/backend/validate` 继续使用后端 ingestion Schema，但通过同一个 Loader 标准化 AGV 后再进行关联完整性检查。

## 4. 契约分层

### 4.1 后端原始 AGV 契约

`BackendAgvRelation` 只声明：

```text
equipmentid
equipmentname
lastlinecode
lastlinename
createtime
```

甲方原始记录被识别后，`processcode`、`processname`、`equipmentcode` 和其他现场字段由 Loader 过滤。

### 4.2 算法标准和内部 AGV 契约

`AgvRelationRequest` 与 `AlgorithmAgvRelation` 只声明：

```text
machine_code
machine_name
order_code
order_name
binding_time
```

标准格式记录仍使用严格的 `extra="forbid"`，防止拼写错误被吞掉。

### 4.3 机台实时契约

从 `BackendMachineRealtime` 和 `MachineRealtimeRequest` 删除 `order_code`。内部 `AlgorithmMachineRuntime.current_order_code` 保留。

### 4.4 BackendOrder 决策

当前正式算法请求、fixture 和接口文档已有 `orders.order_name`，因此 SnapshotAdapter 可以对最终绑定执行订单名称一致性校验。

当前 `BackendOrder` 和专门的 `backend_ingestion_request_sample.json` 没有 `order_name`；仓库不存在能按 `order_code` 唯一映射的等价原始字段。`buffer_realtime.bound_source_name` 只有名称、没有订单编码，不能可靠反查。因此本次不凭空给 `BackendOrder` 增加必填 `order_name`：

- `/backend/validate` 校验 AGV `order_code` 是否存在；
- 正式计算链路使用 `OrderRequest.order_name` 校验最终绑定名称。

## 5. Loader 唯一映射职责

`BackendRequestLoader` 定义唯一字段表：

```text
equipmentid   → machine_code
equipmentname → machine_name
lastlinecode  → order_code
lastlinename  → order_name
createtime    → binding_time
```

`normalize_payload(payload)`：

1. 深拷贝输入；
2. 只处理 `agv_relations`；
3. 识别包含任一原始五字段的原始记录；
4. 原始记录只提取五个业务字段；
5. 原始和标准字段并存时逐对比较；
6. 值一致时只保留标准字段；
7. 值冲突时抛出 `BackendRequestLoadError`，错误包含记录下标、字段名和双方值；
8. 不选择最新记录，不查询机台、订单或工序，不填默认值，不修改时间业务值。

正式计算接口调用 Loader 的标准请求加载方法。后端 validation 加载方法也复用相同的单记录标准化函数，不在路由、Validator 或 SnapshotAdapter 重写字段映射。

## 6. SnapshotAdapter 合并规则

SnapshotAdapter 接收的 AGV 已是标准五字段：

1. 将无时区的 `binding_time` 和用于比较的无时区 `snapshot_time` 按固定 UTC+08:00 解释；
2. 按 `machine_code` 分组；
3. 排除 `binding_time > snapshot_time` 的记录；
4. 选择最大有效 `binding_time`；
5. 最新时间完全相同记录去重；
6. 最新时间的 `order_code` 或 `order_name` 不一致时报转换错误；
7. 不依赖数组顺序；
8. 只对最终选中的绑定校验机台编码、机台名称、订单编码和订单名称；
9. 运行机台没有有效绑定时报错；
10. 非运行机台没有绑定时写入 `current_order_code=None`；
11. 非运行机台有绑定时保留该订单编码；
12. 快照中的 `AlgorithmAgvRelation` 只保存最终有效绑定。

名称只做精确一致性检查。编码是唯一关联键，不允许名称模糊匹配。

## 7. 工序来源

工序始终来自：

```text
machine_realtime.machine_code
→ machine_master.machine_code
→ machine_master.process_code/process_name
```

AGV 的 `processcode/processname` 即使存在也会被 Loader 过滤，不进入标准模型，不覆盖或参与工序一致性校验。

## 8. Validator 与错误边界

Backend Validator 删除 `machine_realtime.order_code` 的状态校验和外键校验，增加：

- 与 SnapshotAdapter 共用 UTC+08:00 和最新有效绑定选择器；
- 只对快照时刻最终选中的 AGV 校验
  `machine_code → machine_master.machine_code`；
- 只对最终选中的 AGV 校验 `order_code → orders.order_code`；
- 校验最终选中的 `machine_name` 与机台主数据精确一致；
- 报告最新同刻 `order_code` 或 `order_name` 冲突；
- 每台运行机台必须存在快照前有效且无冲突的 AGV 绑定。

`BackendOrder` 没有可靠订单名称字段，因此订单名称与正式订单数据的一致性仍由
SnapshotAdapter 精确校验。

Pydantic 请求格式错误和 Loader 字段冲突在 HTTP 接口转换为 422。Snapshot 数据关联或有效绑定错误继续使用项目的转换异常规范。

## 9. 测试和数据

测试遵循红灯、最小实现、回归顺序，覆盖：

- 三层 AGV 契约；
- Loader 深拷贝、原始字段映射、现场字段过滤、标准严格字段和冲突；
- 两个正式接口与 `/backend/validate` 共用 Loader；
- 最新有效记录、未来记录、重复、冲突、UTC+08:00；
- 运行/非运行机台缺失绑定；
- 机台和订单编码/名称一致性；
- runtime 订单来自 AGV、工序来自 machine master；
- 产品关联以及所有既有 V3 集成流程和响应结构。

fixture 和所有生成请求删除 `machine_realtime.order_code`，场景切换订单改为更新 AGV 原始记录。示例由共享生成器统一重建。

## 10. 依赖与 Git 约束

仓库仅有 `requirements.txt`，声明 `pydantic>=2.11,<3`、
`fastapi>=0.135`、`pytest>=8` 等依赖。测试环境先按该文件安装；FastAPI
TestClient 实例化还需要 HTTP 客户端，因此按已安装 FastAPI 的官方
`standard` 元数据约束补装 `httpx>=0.23,<1`，未安装无约束的 FastAPI 版本，
也未修改项目依赖声明。

本次不执行 `git add`、`git commit`、`git push`、`git merge`、`git rebase`、`git reset`、`git checkout` 或 `git switch`。
