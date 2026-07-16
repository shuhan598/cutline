# 后端请求接收、清洗与完整性校验设计

- 日期：2026-07-14
- 范围：真实后端 JSON 的结构建模、兼容性清洗和业务完整性校验
- 明确非目标：不映射 `CutlineSnapshot`，不调用算法，不修改任何算法内部对象或逻辑

## 1. 背景与目标

当前项目只有 `MockAdapter -> SnapshotAdapter -> CutlineSnapshot` 的算法样例链路，尚无独立的真实后端请求边界。旧 `CutlineSnapshot` 还会忽略额外字段并为多数数据集提供默认空数组，不能承担真实后端契约的严格校验。

本次新增一条与现有算法入口完全隔离的链路：

```text
UTF-8 JSON 文件 / Python dict
        |
        v
BackendRequestLoader
  - 文件与 JSON 读取
  - deepcopy
  - 仅删除 machine_realtime.period_quantity / out_time
        |
        v
BackendAlgorithmRequest.model_validate
  - 字段是否存在
  - null 是否允许
  - 类型和单字段数值约束
  - extra="forbid"
        |
        v
BackendRequestCompletenessValidator
  - 空数据集
  - 必需业务值为 null
  - 空字符串编码
  - 跨数据集引用和路线完整性
        |
        v
BackendRequestValidationResult
        |
        X  本阶段到此停止，不进入算法
```

目标是严格区分以下四种状态：

1. 字段缺失：Schema 校验失败并抛出 Pydantic `ValidationError`。
2. 字段存在但值为 `null`：仅声明为可空的字段能通过 Schema；业务必需值由完整性校验生成 issue。
3. 字段存在但编码值为 `""`：Schema 保留原值，完整性校验生成 issue。
4. 顶层数据集存在但为空数组：Schema 接受，关键数据集由完整性校验生成 issue。

任何一层都不得补值、猜测数据、重算数值或静默忽略未知字段。

## 2. 方案选择

采用“独立严格外部模型 + 最小兼容清洗 + 独立完整性报告”方案。

未采用的方案：

- 对所有字符串使用非空 `str`：会在 Schema 层拒绝当前真实请求，无法达到“能读取但完整性失败”的目标。
- 在 Loader 中把 `null` 替换为空字符串、默认名称或推断编码：混淆原始数据状态，违反不补值、不猜测原则。
- 再增加一套宽松 Raw DTO：会产生两套几乎重复的外部模型；本次通过“字段必传但指定值可为 null”即可同时满足结构保真和业务报告要求。

## 3. Schema 设计

### 3.1 全局规则

新增 `app/schemas/backend_request_schema.py`，定义 14 个模型。所有模型使用 Pydantic v2，并统一设置：

```python
model_config = ConfigDict(extra="forbid")
```

可以通过私有公共基类继承该配置，但每个公开模型的最终配置都必须是 `extra="forbid"`。

所有约定字段都不设置默认值。顶层列表同样不使用 `default_factory`。允许 `null` 的写法必须是：

```python
field: str | None
```

禁止写成：

```python
field: str | None = None
```

因此，“允许值为 `null`”不等于“允许字段缺失”。

Pydantic 保持默认的类型解析行为，不额外启用 strict mode。整数和小数输入都可以解析到 `float` 字段；本阶段不做状态标准化、字符串 trim、编码大小写转换、单位转换或时间时区改写。

### 3.2 模型与字段

#### `BackendSnapshotMeta`

- `run_id: str`
- `trigger_type: str`
- `workshop_id: str`
- `snapshot_time: datetime`
- `params_version: int`
- `catalog_version: str`
- `catalog_loaded_at: datetime`
- `degraded_flags: list[str]`

#### `BackendMachineRealtime`

- `machine_code: str`
- `status: str`
- `order_code: str`
- `tangent_time: datetime | None`
- `input_quantity: float`，`>= 0`
- `output_quantity: float`，`>= 0`
- `completed_quantity: float`，`>= 0`

Schema 严格只保留以上七个字段。`tangent_time` 是业务上真正可空的字段，不因 `null` 产生完整性 issue。

#### `BackendMachineMaster`

- `machine_code: str`
- `machine_name: str`
- `process_code: str`
- `process_name: str`

#### `BackendMachineProcessTime`

- `machine_code: str`
- `machine_name: str`
- `product_code: str`
- `product_name: str`
- `proc_seconds: float`，`> 0`
- `actual_capacity: float`，`> 0`

`proc_seconds` 保持后端原始秒单位，不转换成分钟。

#### `BackendWorkshop`

- `workshop_code: str`
- `workshop_name: str | None`

`workshop_name` 必须出现；`null` 仅用于兼容当前请求，并会生成完整性 issue。

#### `BackendLine`

- `line_code: str`
- `line_name: str`
- `wafer_spec: str`
- `workshop_code: str`
- `workshop_name: str`

#### `BackendMachineLine`

- `machine_code: str`
- `machine_name: str`
- `line_code: str`
- `line_name: str`
- `wafer_spec: str`

#### `BackendOrder`

- `order_code: str`
- `order_status: str`
- `total_quantity: float`，`>= 0`
- `piece_source: str`
- `estimated_yield: str`
- `product_code: str`
- `product_name: str`
- `workshop_code: str`
- `workshop_name: str`
- `produced_quantity: float`，`>= 0`
- `remaining_quantity: float`，`>= 0`

不重新计算或修正 `remaining_quantity`。

#### `BackendProduct`

- `product_code: str`
- `product_name: str`
- `wafer_size: str`
- `source_grade: str`
- `material_code: str`
- `material_name: str`

不增加 `shape_code`，也不从名称或尺寸推断 N/R/P。

#### `BackendProcessRoute`

- `process_code: str`
- `process_name: str`
- `sequence: int`
- `cache_type: str`
- `workshop_code: str`
- `workshop_name: str`
- `loop_code: str`
- `loop_name: str`
- `upstream_process_code: str | None`
- `upstream_process_name: str | None`
- `downstream_process_code: str | None`
- `downstream_process_name: str | None`

四个上下游字段必须出现。按同一 `(workshop_code, loop_code)` 路线判断：首工序允许上游代码和名称为 `null`，末工序允许下游代码和名称为 `null`；单工序路线同时是首尾。其他位置的 `null` 属于完整性问题。

#### `BackendBufferRealtime`

- `main_id: str | None`
- `buffer_code: str`
- `bound_source_name: str`
- `current_quantity: float`，`>= 0`
- `current_utilization_rate: float`，`>= 0`

`main_id` 必须出现；`null` 仅用于兼容当前请求，并会生成完整性 issue。不增加或解析订单、产品、物料、源/目标工序、车间字段。

#### `BackendBufferMaster`

- `buffer_code: str`
- `buffer_name: str`
- `buffer_type: str`
- `buffer_type_title: str`
- `max_capacity: float`，`> 0`
- `safety_low: float`，`>= 0`
- `served_process_codes: list[str]`，至少一项
- `served_process_names: list[str]`，至少一项
- `loop_code: str`
- `loop_name: str`

#### `BackendAgvRelation`

- `buffer_code: str | None`
- `machine_code: str`
- `line_code: str`
- `line_name: str | None`
- `last_line_code: str | None`
- `last_line_name: str | None`
- `process_code: str | None`
- `process_name: str | None`

以上六个可空字段都必须出现。它们的 `null` 仅用于兼容当前请求，并会生成完整性 issue。

#### `BackendAlgorithmRequest`

- `snapshot_meta: BackendSnapshotMeta`
- `machine_realtime: list[BackendMachineRealtime]`
- `machine_master: list[BackendMachineMaster]`
- `machine_process_times: list[BackendMachineProcessTime]`
- `workshops: list[BackendWorkshop]`
- `lines: list[BackendLine]`
- `machine_lines: list[BackendMachineLine]`
- `orders: list[BackendOrder]`
- `products: list[BackendProduct]`
- `process_routes: list[BackendProcessRoute]`
- `buffer_realtime: list[BackendBufferRealtime]`
- `buffer_master: list[BackendBufferMaster]`
- `agv_relations: list[BackendAgvRelation]`

所有顶层字段必须出现且没有默认值；所有列表在 Schema 层允许为空。

### 3.3 真实请求 null 核对结果

完整扫描当前 145 KB `algo-request.json` 后，实际 `null` 只出现在：

- 439 条 `machine_realtime.tangent_time`
- 1 条 `workshops.workshop_name`
- 1 条 `buffer_realtime.main_id`
- 76 条 AGV 记录的 `buffer_code`
- 76 条 AGV 记录的 `line_name`
- 76 条 AGV 记录的 `last_line_code`
- 76 条 AGV 记录的 `last_line_name`
- 76 条 AGV 记录的 `process_code`
- 76 条 AGV 记录的 `process_name`

未发现其他实际为 `null` 的字段，因此不扩大 Optional 范围。

## 4. Loader 设计

新增 `app/adapters/backend_request_loader.py`：

- `BackendRequestLoadError` 继承 `ValueError`。
- `BackendRequestLoader.load_dict(payload: dict) -> BackendAlgorithmRequest`。
- `BackendRequestLoader.load_json_file(file_path: str | Path) -> BackendAlgorithmRequest`。

### 4.1 `load_dict`

1. 使用 `deepcopy(payload)` 创建工作副本。
2. 不修改调用方传入的顶层或任何嵌套对象。
3. 如果副本的 `machine_realtime` 是列表，则遍历其中的字典记录，并按过渡兼容策略删除 `period_quantity`、`out_time`。
4. 不删除其他位置的同名字段，也不删除任何其他未知字段。
5. 不把 `null`、空字符串或空数组转换成其他值。
6. 调用 `BackendAlgorithmRequest.model_validate(cleaned_payload)`。
7. 原样返回模型；Pydantic `ValidationError` 不包装、不吞掉。

如果输入结构本身不是预期的字典/列表/记录类型，清洗过程不得先产生无关的 `AttributeError`；应尽量保持原值并交由 Pydantic 报告结构错误。

### 4.2 `load_json_file`

1. 使用 `Path(file_path)` 和 UTF-8 编码读取。
2. 使用标准库 `json` 解析。
3. 将解析结果交给与 `load_dict` 相同的清洗和 Schema 路径。
4. 文件不存在、权限/IO 错误、UTF-8 解码错误或 JSON 语法错误统一包装为 `BackendRequestLoadError`。
5. 错误消息包含文件路径和原始原因。
6. 合法 JSON 的 Schema 问题仍传播 Pydantic `ValidationError`。
7. 合法 JSON 的根节点若不是对象，不归类为文件或语法错误；不执行字典清洗，直接由 `BackendAlgorithmRequest.model_validate` 产生结构 `ValidationError`。

### 4.3 `period_quantity` / `out_time` 过渡兼容策略

这两个字段的处理是有退出条件的临时兼容层，不是 Python 新正式输入合同的一部分：

1. 当前 orchestrator 的真实请求仍会在每条 `machine_realtime` 中外发 `period_quantity` 和 `out_time`。
2. `2026-07-14-algo-request-document-field-mapping.md` 描述的是“当前外发 DTO/请求体”，因此把它们记录为当前实现明确保留的运行态补充字段。
3. 本设计描述的是新的 Python 正式输入合同。该合同明确不定义这两个字段，`BackendMachineRealtime` 只包含七个正式字段。
4. 为让迁移期间的当前真实请求能够进入新合同，Loader 仅在 `machine_realtime` 记录的深拷贝上删除这两个已确认字段。
5. 它们不进入 `BackendAlgorithmRequest`，不进入完整性校验的业务关系，也不参与任何算法计算。
6. 其他未知字段不享受该兼容处理，仍由 `extra="forbid"` 拒绝。
7. 后端停止外发这两个字段后，应删除 Loader 中对应的兼容清理逻辑及专用兼容测试；Schema 和算法无需变化。

因此，字段映射文档中的“保留”与本设计中的“删除”并不矛盾：前者记录迁移前的当前后端外发事实，后者定义迁移后的 Python 目标合同和临时接入方式。

## 5. 完整性校验设计

新增 `app/adapters/backend_request_validator.py`。

### 5.1 结果模型

`BackendValidationIssue`：

- `code: str`
- `dataset: str`
- `field: str | None`
- `record_key: str | None`
- `message: str`

`BackendRequestValidationResult`：

- `valid: bool`
- `issues: list[BackendValidationIssue]`

两个模型同样使用 `extra="forbid"`。包括可空字段在内，所有结果字段均无默认值。

`BackendRequestCompletenessValidator.validate(request)` 汇总全部问题；`valid` 严格等于 `not issues`。业务数据问题不通过异常表达，也不提前返回。

### 5.2 固定 issue code

| code | 含义 |
| --- | --- |
| `empty_dataset` | 必须存在的顶层数据集是空数组 |
| `null_field` | Schema 为兼容接收 `null`，但该位置的业务值必需 |
| `empty_code` | 编码字段存在但值严格等于空字符串 `""` |
| `missing_reference` | 非空主外键在目标数据集中找不到 |
| `duplicate_sequence` | 同一 `(workshop_code, loop_code)` 工艺路线分组中有重复顺序号 |
| `invalid_value` | 已构造模型中的业务值违反完整性规则，例如 `max_capacity <= 0` |

问题按固定规则顺序和原始记录顺序输出，便于测试和调用方稳定展示。`record_key` 优先使用记录自身代码；代码不可用时使用 `index:<n>`，复合关系使用可读的代码组合。

### 5.3 空关键数据集

以下九个数据集为空时各生成一个 `empty_dataset`：

- `machine_realtime`
- `machine_master`
- `machine_process_times`
- `workshops`
- `orders`
- `products`
- `process_routes`
- `buffer_realtime`
- `buffer_master`

`lines`、`machine_lines`、`agv_relations` 仍必须作为顶层字段出现，但本阶段不要求非空。

### 5.4 null 业务字段

以下兼容性可空字段值为 `null` 时生成 `null_field`：

- `workshops.workshop_name`
- `buffer_realtime.main_id`
- `agv_relations.buffer_code`
- `agv_relations.line_name`
- `agv_relations.last_line_code`
- `agv_relations.last_line_name`
- `agv_relations.process_code`
- `agv_relations.process_name`

以下是真正允许为空的语义，不自动生成 issue：

- `machine_realtime.tangent_time`
- 首工序的两个上游字段
- 末工序的两个下游字段

路线中非首工序的上游字段或非末工序的下游字段为 `null` 时生成 `null_field`。

### 5.5 空编码

除 `machine_realtime.order_code` 外，检查所有标量 `*_code` 字段，以及 `served_process_codes` 中每个元素。值为 `""` 时生成 `empty_code`；`null` 与空字符串保持不同 code，不进行 trim 或替换。`machine_realtime.order_code` 使用下一节的状态感知规则。

`run_id`、`workshop_id`、`main_id` 不是 `*_code` 字段，不混入这条规则；其中 `main_id=null` 已由 null 规则处理。

### 5.6 `machine_realtime.order_code` 状态感知规则

`order_code` 是否允许为空必须结合机台状态判断，不对所有状态机械应用同一规则：

1. 本阶段明确识别的运行状态是 `"运行"`，以及英文大小写不敏感的 `"running"`。比较只用于校验判断，不改写原始 `status`。
2. 运行机台的 `order_code == ""` 时生成 `empty_code`。任何 issue 都会使 `valid=false`，因此该问题是阻断性的。
3. 非运行机台允许 `order_code == ""`，不生成 `empty_code`，也不对该空值生成 `missing_reference`。当前真实请求中的 `"异常"` 按非运行状态处理。
4. 未被上述运行谓词识别的状态，本阶段不猜测为运行状态；按非运行状态执行本条规则。状态枚举和标准化不属于本次范围。
5. 只要 `order_code` 非空，无论机台状态如何，都必须执行 `machine_realtime.order_code -> orders.order_code` 引用检查。

当前真实请求的状态分布为：137 条 `"运行"` 记录且 `order_code` 均为空，301 条 `"异常"` 记录且 `order_code` 均为空，1 条 `"RUNNING"` 记录且订单编码非空。按上述口径，137 条运行记录生成阻断性 `empty_code`，301 条异常记录的空订单编码不产生 issue。

### 5.7 引用、去重与路线规则

仅对非 `null` 且非空字符串的源编码执行引用检查。同一字段已经产生 `null_field` 或 `empty_code` 后，不再为该字段额外生成 `missing_reference`：

1. `machine_realtime.machine_code -> machine_master.machine_code`
2. `machine_realtime.order_code -> orders.order_code`
3. `orders.product_code -> products.product_code`
4. `orders.workshop_code -> workshops.workshop_code`
5. `machine_process_times.machine_code -> machine_master.machine_code`
6. `machine_process_times.product_code -> products.product_code`
7. `buffer_realtime.buffer_code -> buffer_master.buffer_code`
8. 工艺路线上下游代码必须在同一 `(workshop_code, loop_code)` 分组的 `process_routes.process_code` 中存在。
9. `buffer_master.served_process_codes` 的每个代码必须能在同一 `loop_code` 的工艺路线中找到。

此外：

- `process_routes` 严格按 `(workshop_code, loop_code)` 分组。
- `process_routes.sequence` 只在同一分组内检查重复；不同分组可以使用相同 sequence。
- 首尾位置按同一 `(workshop_code, loop_code)` 分组后依 `sequence` 的最小值/最大值判定。
- 仅组内最小 sequence 的记录允许两个上游字段为 `null`；仅组内最大 sequence 的记录允许两个下游字段为 `null`。
- `buffer_master.max_capacity` 在完整性层仍显式检查 `> 0`，即使正常 Schema 路径已经有相同约束。
- 本阶段不额外校验 `lines`、`machine_lines`、`agv_relations` 的外键，不去重数据，也不标准化编码。

issue 去重只消除同一字段、同一根因的重复报告，不掩盖独立问题。例如关键目标数据集为空可以生成 `empty_dataset`，非空源编码找不到该目标记录仍可生成对应的 `missing_reference`；二者分别描述数据集级缺口和记录级断链。

## 6. 当前真实请求的预期行为

Loader 应能成功解析当前真实请求：

- 439 条 `machine_realtime` 中的 `period_quantity`、`out_time` 仅在深拷贝中被删除。
- 原始请求保持不变。
- 当前实际 `null` 均落在明确声明的可空字段内。
- 所有顶层数据集都存在，因此不会发生 Schema 缺字段错误。

完整性校验必须返回 `valid=false`，并至少覆盖以下类别：

- `machine_master`、`machine_process_times`、`orders`、`products`、`process_routes`、`buffer_master` 等关键空数据集。
- `workshop_name`、`main_id` 和 AGV 兼容字段的 `null_field`。
- 137 条运行机台空字符串 `machine_realtime.order_code` 的阻断性 `empty_code`；301 条异常机台的空订单编码按明确口径允许。
- 机台、订单、Buffer 等非空编码对应主数据不存在的 `missing_reference`。

这些问题只形成结构化结果，不触发算法调用。

## 7. 包导出

按任务要求更新：

- `app/schemas/__init__.py`：导出 14 个后端请求模型，不移除既有符号。
- `app/adapters/__init__.py`：导出 Loader、LoadError、完整性校验器和结果模型，不移除既有符号。

现有 `__init__.py` 为空，因此新增显式导出不会覆盖旧导出行为；具体模块路径导入仍保持可用。

## 8. 测试策略

严格采用测试驱动实现，新增：

- `tests/schemas/test_backend_request_schema.py`
- `tests/adapters/test_backend_request_loader.py`
- `tests/adapters/test_backend_request_validator.py`
- `examples/backend_request_sample.json`

精简合法示例包含任务要求的最小闭合数据：1 条实时机台、1 条机台主数据、1 条机台产品工艺数据、1 个车间、1 条订单、1 个产品、2 条串行路线、1 条 Buffer 实时、1 条 Buffer 主数据，并为 `lines`、`machine_lines`、`agv_relations` 各提供合法记录。它必须同时通过 Loader 和完整性校验。

### 8.1 Schema 测试

- 完整请求解析及 datetime 类型。
- 所有顶层字段必传，空列表仍可解析。
- nullable 字段“缺失失败、显式 null 成功”。
- 数量接受整数和小数。
- 各数值边界约束。
- 顶层和嵌套未知字段拒绝。
- `proc_seconds` 秒单位不变。
- 首尾工序空引用可解析。
- 每个公开模型最终配置均为 `extra="forbid"`。

### 8.2 Loader 测试

- `load_dict` 返回 `BackendAlgorithmRequest`。
- 原始 payload 深层不变。
- 所有实时记录的两个废弃字段被兼容删除。
- 其他位置的同名字段不被删除。
- 其他未知字段仍触发 `ValidationError`。
- UTF-8 中文 JSON 文件读取。
- 文件不存在、不可读/解码错误、非法 JSON 的 LoadError 路径和原因。
- 合法 JSON 的 Pydantic `ValidationError` 继续传播。

### 8.3 完整性测试

- 完整闭合数据 `valid=true`、`issues=[]`。
- 四种状态分别验证：字段缺失、显式 null、空编码、空数据集。
- `order_code` 参数化覆盖中文运行、英文不同大小写运行、异常和未知非运行状态；验证运行空值阻断、非运行空值允许、所有非空订单编码均检查引用。
- 九个关键数据集逐项为空。
- 所有指定主外键逐项断裂。
- 路线按 `(workshop_code, loop_code)` 验证重复 sequence、组内首尾 null、缺中间引用和跨组错误引用。
- served process 不存在。
- 多问题汇总、同字段 null/空值不重复产生 missing reference、issue 字段完整、顺序稳定。
- 精简的“当前甲方不完整形态”可加载但返回 `valid=false`，且四类问题齐全。

测试套件不依赖工作区外的微信文件路径。实现完成后，在当前环境额外对真实 `algo-request.json` 做一次只读验证并汇总 issue 类别。

### 8.4 验证命令

```powershell
pytest -q
```

实现前基线为 `113 passed`。完成标准是新增测试与原有 113 项全部通过。

## 9. 修改范围

允许新增或修改：

- `app/schemas/backend_request_schema.py`
- `app/adapters/backend_request_loader.py`
- `app/adapters/backend_request_validator.py`
- `app/schemas/__init__.py`
- `app/adapters/__init__.py`
- 三个指定测试文件
- `examples/backend_request_sample.json`
- 本设计文档及后续实施计划

禁止修改：

- `app/core/**`
- `app/service/**`
- `app/api/**`
- `app/schemas/common_schema.py`
- `app/schemas/request_schema.py`
- `app/schemas/response_schema.py`
- `app/adapters/snapshot_adapter.py`
- 断料、溢满、候选机台、切线方案、切回、丝网和混料逻辑

当前工作区已有用户改动和未跟踪文件；实现必须只触碰上述目标文件，不覆盖、清理或提交无关改动。

## 10. 完成标准

1. 14 个后端请求模型字段、必填性、nullable 语义和数值约束符合本设计。
2. Loader 只做 UTF-8/JSON 读取、深拷贝和两个废弃字段清洗。
3. 其他未知字段始终被拒绝。
4. 完整性校验返回稳定、结构化、可定位的全部问题。
5. 精简合法示例同时通过 Loader 和完整性校验。
6. 当前真实请求能加载、完整性结果为 `valid=false`，且明确报告空数据集、null、空编码和断裂引用。
7. 不产生 `BackendAlgorithmRequest -> CutlineSnapshot` 映射，不进入算法。
8. `pytest -q` 全量通过，且没有修改禁止范围内文件。
