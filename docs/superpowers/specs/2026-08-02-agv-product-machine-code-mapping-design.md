# AGV 产品型号匹配与机台双编号归一设计

## 目标

在外部请求进入 `AlgorithmSnapshot` 前完成两类关联：AGV 当前产品型号名称解析为唯一当前订单，以及机台实时编号 `p166_jt_group` 归一为静态机台标准 `machine_code`。核心算法继续只使用 `order_code` 和标准 `machine_code`，公开 Response 契约不变。

## 已确认的旧链路

- `BackendRequestLoader` 将 `lastlinecode -> order_code`、`lastlinename -> order_name`。
- `SnapshotAdapter` 使用 AGV 的 `order_code` 查订单，再校验 `order_name`，把订单编码写入 `AlgorithmMachineRuntime.current_order_code`。
- Buffer 使用 `(workshop_code, order_name)` 匹配订单。
- `machine_realtime.machine_code` 直接匹配 `machine_master.machine_code`，尚无第二编号映射。

## 方案比较

1. **集中索引类（采用）**：在 Adapter 层建立机台双索引、产品双索引和当前订单双索引；所有关联和唯一性校验集中完成。边界清晰，可独立测试，不向核心算法传播外部编号。
2. 在 `SnapshotAdapter` 各转换方法内直接增加字典和条件分支：改动文件少，但重复校验、错误信息和双编号语义会继续堆积在已经较大的类中。
3. 在 Loader 中直接把所有外部数据改写为标准编号和订单编码：Loader 尚未拥有完整主数据关联上下文，会混合语法投影与业务校验，也不利于复用车间解析器。

## 组件与职责

- `MachineMasterIndex`：校验 `machine_code`、`p166_jt_group` 非空且各自唯一；提供 AGV 标准编号与实时编号的精确查找；返回的内部编号始终是静态 `machine_code`。
- `ProductCatalogIndex`：校验 `product_code`、`product_name` 非空且各自唯一，并提供精确查找。
- `CurrentOrderIndex`：校验 `order_code` 非空唯一、订单产品编码和名称与静态产品一致，以及一个 `product_name` 只对应一个当前订单。
- `BackendRequestLoader`：只做字段投影；AGV 的 `linename` 投影为标准请求中的 `product_name`，`lastlinename` 投影为可空的 `previous_product_name`。不再读取或映射 `lastlinecode`。
- `SnapshotAdapter`：按主数据、产品、订单、AGV、实时机台、Buffer 的顺序使用索引完成关联；复用 `MachineWorkshopResolver` 校验 AGV 机台与订单车间，复用现有 Buffer 工序关系解析校验 Buffer 与订单车间。

## 数据流

### AGV 当前订单

`equipmentid -> machine_master.machine_code -> 标准机台`

`linename -> product.product_name -> current_order.product_name -> order_code`

`lastlinename` 仅保存为上一产品诊断信息，不参与查找，也不作为兜底。相同最新时间记录比较 `equipmentname`、`linename`、`lastlinename`、`waferspec`；完全一致可去重，任一业务字段冲突即报错。

### 实时机台

`machine_realtime.machine_code -> machine_master.p166_jt_group -> machine_master.machine_code`

产能、机台产线关系和活动切线事件从现有 Schema、测试与样例可确认使用标准 `machine_code`，因此不重复转换。

### Buffer

`bound_source_name -> current_order.product_name -> order_code`，随后显式比较 Buffer 工序关系解析出的车间与订单车间。内部库存仍只保存 `order_code`。

## Schema 变化

- `BackendMachineMaster`、`MachineMasterRequest` 新增必需字符串 `p166_jt_group`。
- `BackendAgvRelation` 删除 `lastlinecode`，新增必需 `linename`，保留可空 `lastlinename`。
- `AgvRelationRequest` 删除 `order_code/order_name`，使用 `product_name/previous_product_name`。
- `OrderRequest`、`AlgorithmOrder` 删除 `order_name`。
- `AlgorithmAgvRelation` 使用 `product_name` 代替 `order_name`；候选结果的既有 `current_order_name` 字段继续输出该真实产品型号名称，Response 字段名不变。

## 错误处理

所有找不到、空值、重复、产品不一致、同时间 AGV 冲突、编号无法映射和车间冲突均抛出包含数据来源及关键编码的明确错误。不得默认取第一条、通过字典覆盖重复项、模糊匹配或大小写猜测。

## 测试策略

- Schema/Loader 契约先验证新字段、删除字段、可空上一产品名和旧字段不再控制结果。
- 索引及 SnapshotAdapter 覆盖双编号正常归一、全部唯一性/空值/未知引用、产品订单一致性、AGV 时间选择与冲突、AGV/Buffer 车间一致性。
- 更新共享工厂，使静态标准编号与实时编号明显不同；更新所有有效示例。
- 回归运行 Adapter、Schema、核心算法、服务、API、完整 pytest、编译检查、完整示例 Pipeline、Response Schema 和旧字段扫描。

## 非目标

不修改断料、溢满、预警、候选机台、切线、切回、丝网、混料公式或规则；不修改最终 Response Schema；不重新解释无法从现有 Schema/测试/样例确认的外部编号来源。
