# 光伏车间切线算法服务

本仓库提供新版切线算法的本地服务编排与测试。主评估调用链是：

```text
原始请求 JSON
  -> BackendRequestLoader
  -> CutlineAlgorithmRequest
  -> SnapshotAdapter.to_algorithm_snapshot
  -> CutlinePipeline.evaluate_algorithm
  -> AlgorithmResponseMapper.to_evaluate_response
  -> CutlineEvaluateResponse
       = CutlineAlgorithmResponse 原有业务字段
       + persistence_state
```

算法输出建议和计算结果，不直接控制机台，也不写数据库。当前对后端提供两个同步
HTTP 接口：`POST /cutline/evaluate` 返回增强的 `CutlineEvaluateResponse`；兼容接口
`POST /stub/algo/run` 仍按原 `CutlineAlgorithmResponse` 投影，不返回持久化状态。

## 请求与内部配置

后端请求由 `BackendRequestLoader` 标准化后形成 `CutlineAlgorithmRequest`。请求中不传
`config`；`SnapshotAdapter` 转换为内部 `AlgorithmSnapshot` 时，由
`AlgorithmConfig` 注入默认运行参数。后端持久化但尚未确认执行的方案通过请求顶层
`pending_cutline_plans` 传入；已经确认的活动切线事件通过
`active_cutline_events` 传入；已经完成混料或切回建议的事件 ID 分别通过
`mixed_cutline_event_ids`、`return_suggested_event_ids` 回传。算法服务是无状态的，
不使用进程内缓存或本地文件保存这些跨轮状态。

`process_routes[].loop_code` 和 `loop_name` 是可选兼容字段。旧请求继续传入原值、旧值
或错误值都可解析，但这些值不作为内部权威；Snapshot 始终根据 trim 后的
`process_name` 重新生成循环。`process_code` 继续作为关联主键，`process_name` 只负责
识别所属循环。中央目录严格为：

| 工序名称 | 内部循环 |
| --- | --- |
| 发料机 | `LOOP1` / 一循环 |
| 制绒、硼扩、氧化 | `LOOP2` / 二循环 |
| 碱抛、`POLY`、退火 | `LOOP3` / 三循环 |
| `RCA` | `LOOP4` / 四循环 |
| `ALD`、正膜、背膜、丝网 | `LOOP5` / 五循环 |

中文名称只在 trim 后精确匹配；仅 `POLY`、`RCA`、`ALD` 兼容大小写。未知名称会携带
`process_code` 和原始 `process_name` 明确报错，不提供别名或模糊匹配。`sequence`
完全采用后端输入，每项仍须为正整数且在同一 workshop 内唯一；不写死顺序，
车间最小值不必等于 1，也不要求连续。
完整工艺路线、上下游引用和唯一末序丝网均按 workshop 校验，上下游可跨内部循环。

Buffer 仍要求 `served_process_codes` 恰好包含两个可解析工序；两个工序必须能在同一
workshop 完整路线中形成唯一配对，并按 route `sequence` 规范化为上游到下游，既不
依赖数组排列，也不要求同循环或固定相邻。`buffer_master[].loop_code` 和 `loop_name`
仅作兼容/描述，不参与合法性、方向或断料/溢满区间判断。仍使用上述 12 个可识别名称且满足
workshop 内唯一性的旧 Request 可继续携带 route loop 字段；非目录名称现会按设计
明确拒绝。正式 Response 字段和层级不变。

首轮预警返回原有预警、候选方案，并在 `persistence_state.pending_cutline_plans`
返回完整 Pending；不创建活动事件或混料记录。后端保存该状态并在下一轮回传后，算法在
`(created_at, expire_at]` 内比较预警时基线与 AGV 绑定历史。只有确认某台标准机台
确实换型，才创建 Active，生成该真实事件的一条混料记录并进入切回判断。
默认确认窗口由 `cutline_confirmation_window_minutes=30` 统一配置，时间判断只使用
请求的 `snapshot_time`。方案创建时保存本车间、本工序范围内的完整机台绑定基线，
每条基线的 `observed_at` 必须不晚于 `created_at`。

公开的新活动事件仍保持既有 12 个字段：`event_id`、`machine_code`、源/目标订单、
车间、目标 Buffer、上下游工序、目标硅片尺寸/规格、真实切线开始时间和
`negative_start_time`。`persistence_state.active_cutline_events` 则返回完整持久化对象，
包括 `plan_id`、`warning_id`、`status` 和 Pending 来源上下文；这些内部字段不会改变
原公开业务事件的字段结构。

`machine_realtime` 不再携带 `order_code`，其中的 `machine_code` 是 P166 集团编号；
Adapter 通过 `machine_master.p166_jt_group` 找到静态机台，再统一转换为静态
`machine_master.machine_code`。AGV 的 `equipmentid` 本身使用该标准编号。核心 Snapshot、
活动事件和 Response 始终只传播标准编号。

甲方 AGV 原始字段
`equipmentid/equipmentname/linename/lastlinename/waferspec/createtime` 只在 Loader
中映射为标准的
`machine_code/machine_name/product_name/previous_product_name/wafer_spec/binding_time`。
`lastlinecode` 和订单 `order_name` 已从新契约删除。快照按 UTC+08:00 选择不晚于
`snapshot_time` 的最新有效绑定，用 `linename -> products.product_name ->
orders.product_name` 精确找到唯一当前订单，再把 `order_code` 写入内部
`AlgorithmMachineRuntime.current_order_code`。`lastlinename` 只表示上一产品，不参与当前
订单查找或兜底。Buffer 的 `bound_source_name` 同样表示产品型号名称，并通过
`orders.product_name` 解析为内部 `order_code`。`AlgorithmMachineRuntime` 不保存当前硅片规格。产线
`wafer_spec` 仅为兼容字段。机台所属车间的算法权威链路是
`machine_code -> machine_master.process_code -> process_routes.process_code
-> process_routes.workshop_code`；不再通过 `machine_lines -> lines.workshop_code`
判断。需要参与计算的订单如果没有有效 AGV `wafer_spec`，算法会抛出明确的数据错误，
绝不回退到 `line.wafer_spec`。`lines` 和 `machine_lines` 是默认空数组的可选兼容
数据，当前核心算法不依赖产线；省略二者或显式传入空数组均可运行。旧请求同时提供
完整产线和机台产线关系时，Adapter 仍执行产线唯一性、未知机台、未知产线及重复绑定
校验。只提供 `machine_lines` 而不提供 `lines` 会得到明确的数据错误。

方案生成时刻不再被视为正式切线时刻。真实活动事件的 `cutline_start_time` 使用窗口内
能够证明绑定变化的 AGV `createtime`；当前实现把它解释为“算法可观察到的 AGV 绑定
记录时间”，不是精确物理换型时间。混料只由确认并成功合并的 Active 触发，计算基准
使用该 `cutline_start_time`，不再额外叠加方案执行延迟；其余混料公式保持不变。
同一事件成功生成混料后写入 `mixed_cutline_event_ids`，失败时不推进水位，可在后续轮次重试。

完全省略可选产线字段的标准请求见
`examples/backend_request_standard.json`；显式传空数组的请求见
`examples/backend_request_sample.json`。基础业务响应样例见
`examples/cutline_algorithm_response_sample.json`；首轮、确认轮和切回轮增强响应见
`examples/cutline_evaluate_*_response.json`。运行正式服务链：

```powershell
python examples/run_cutline_algorithm.py
```

## V3 标准假数据

正式示例和完整流程测试统一使用 `S2` / `S2车间`，机台编码从 `EA001` 开始。
共享测试工厂仍保留 `S2-SW1A`、`S2-SW1B`、`S2-SW2A`、`S2-SW2B`
完整产线数据，用于验证旧请求兼容；提交的场景 JSON 使用空的可选产线数组验证核心
算法解耦。当前 fixture 的 12 工序后端输入顺序为（仅用于样例，不是生产固定
`sequence`）：

```text
发料机 -> 制绒 -> 碱抛 -> 背膜 -> 硼扩 -> POLY -> RCA -> 退火 -> 氧化 -> ALD -> 正膜 -> 丝网
```

该 fixture 使用数字字符串 Buffer `310110301` 至 `310110311` 覆盖测试区间；该编号
布局仅属于测试数据，不构成生产约束。统一工厂入口位于
`tests/fixtures/v3_full_route_factory.py`，场景 JSON 可确定性重新生成：

```powershell
python examples/generate_v3_scenarios.py
```

运行指定场景时把 JSON 路径作为参数传入，例如：

```powershell
python examples/run_cutline_algorithm.py examples/scenarios/v3_stockout_auto.json
```

未传参数时仍运行 `examples/backend_request_sample.json`。

## 响应

`CutlineAlgorithmResponse` 公开字段为：

- `calculation_time`
- `stockout_warnings`
- `overflow_warnings`
- `cutline_decisions`
- `return_recommendations`
- `silk_screen_results`
- `mixing_trace_records`
- `new_active_cutline_events`
- `updated_active_cutline_events`
- `closed_active_cutline_event_ids`
- `errors`

`CutlineEvaluateResponse` 平铺保留上述全部字段，只增加：

- `persistence_state.pending_cutline_plans`
- `persistence_state.active_cutline_events`
- `persistence_state.expired_pending_plan_ids`
- `persistence_state.completed_pending_plan_ids`
- `persistence_state.return_suggested_event_ids`
- `persistence_state.mixed_cutline_event_ids`
- `persistence_state.new_mixing_trace_records`

其中：

- 甲方业务结果：`stockout_warnings`、`overflow_warnings`、`cutline_decisions`、`return_recommendations`、`silk_screen_results`、`mixing_trace_records`。
- 后端算法状态：`new_active_cutline_events`、`updated_active_cutline_events`、`closed_active_cutline_event_ids`。
- 后端错误记录：`errors`。单条预警、切回或混料计算失败不会清除其它成功结果。

`negative_start_time` 只属于后端算法状态，不展示给甲方。更新事件中的
`negative_start_time: null` 表示后端必须清空原计时。算法一旦输出
`return_recommendations`，会在同轮写入累计 `return_suggested_event_ids` 并把完整
Active 状态更新为 `return_recommended`；后端下一轮原样回传状态和水位后不会重复建议。
算法不检测现场是否实际切回，也不创建 PendingReturnPlan。

`pending_cutline_plans`、确认状态、机台数量和基线绑定不属于基础
`CutlineAlgorithmResponse`，但会作为增强接口的完整持久化状态返回。后端应保存整个
`persistence_state`，并把其中 Pending、Active 和两个累计 ID 水位映射回下一轮请求；
不要从公开事件 ID 字符串中拆分方案编号。部分执行保持
`PARTIALLY_CONFIRMED` 到窗口截止，全部执行为 `CONFIRMED`，未完成部分到期为
`EXPIRED`，切回建议完成后可推进为 `RETURN_SUGGESTED`。

## 测试

安装 `requirements.txt` 中的依赖后运行：

```powershell
pytest -q
```

样例契约可单独验证：

```powershell
pytest -q tests/test_current_examples.py
```

