# 当前请求示例

`examples/` 下的 4 份正式请求和 `examples/scenarios/` 下的 13 份 V3 场景请求，
都由 `tests/fixtures/v3_full_route_factory.py` 确定性生成。不要单独手工维护这些 JSON；
在项目根目录运行：

```powershell
python examples/generate_v3_scenarios.py
```

甲方标准输入、正式输出和 422 错误样例由第二个生成器维护：

```powershell
python examples/generate_cutline_standard_examples.py
```

所有 ProcessRoute 使用获批的 12 个规范工序名，其中英文名保持
`POLY` / `RCA` / `ALD`，不生成中文别名。`process_code` 仍是关联主键；
`sequence` 是 fixture 提供的后端输入，不表示生产固定顺序。

`backend_request_standard.json` 和 `cutline_standard_input_first_round.json` 省略
ProcessRoute 的 `loop_code` / `loop_name`，用于展示新 Request；其他兼容场景
仍可携带旧 loop 值，但内部循环始终由 `process_name` 重建。Buffer loop
字段仅作描述，服务区间按 `served_process_codes` 在同车间路线中解析，
并由 route `sequence` 确定方向。

同一生成器还通过真实 Loader/Service/Mapper 链维护四份增强响应：

- `cutline_algorithm_response_sample.json`：字段不变的基础业务响应
- `cutline_evaluate_stockout_round_1_response.json`：首轮 Pending、无 Active/混料
- `cutline_evaluate_confirmation_round_response.json`：确认 Active、单次混料与水位
- `cutline_evaluate_return_response.json`：首次切回建议与 return 水位

当前机台与订单绑定契约如下：

- `machine_master.machine_code` 是算法标准码（如 `EA001`），
  `machine_master.p166_jt_group` 是 P166 实时码（如 `P166-EA001`）。
- `machine_realtime.machine_code` 使用 P166 实时码；`machine_process_times`、
  `machine_lines`、`pending_cutline_plans` 中的机台编码和
  `active_cutline_events.machine_code` 继续使用算法标准码。
- AGV 原始记录使用 `equipmentid/equipmentname/linename/lastlinename/waferspec/createtime`；
  `equipmentid` 是算法标准码，`linename` 是当前产品型号名称，
  `lastlinename` 可为 `null`，不再提交订单编码字段。
- `orders` 不包含 `order_name`；当前订单通过 `product_name` 精确匹配。
- `buffer_realtime.bound_source_name` 同样使用产品型号名称。
- 所有切线算法请求显式包含 `pending_cutline_plans`、`active_cutline_events`、
  `return_suggested_event_ids` 和 `mixed_cutline_event_ids`；不同契约的原始 ingestion
  样例不混入算法状态字段。两个 ID 数组是独立的累计幂等水位。
- 首轮断料方案只返回业务建议，并在增强响应的 `persistence_state` 创建 Pending；
  `new_active_cutline_events` 和 `mixing_trace_records` 均为空。
- `cutline_standard_input_next_round.json` 的 Pending 直接来自同次生成时首轮
  正式输出的 `persistence_state.pending_cutline_plans`，不使用独立预制状态。
- `v3_return_round_2.json` 展示后端回传完整 Pending 和 AGV 历史后，在 30 分钟窗口内
  确认真实机台换型；本轮创建一条 Active、一条混料记录并推进混料水位。
- `v3_return_recommended.json` 回传完整 Active 和已有混料水位，用于展示首次切回建议；
  后端保存输出的 `return_suggested_event_ids` 与 `status=return_recommended` 后，后续轮次
  不会重复输出建议。
- Pending 监控依赖方案创建时基线和窗口内新 AGV 记录，因此确认场景不能只保留每台机台
  最新一条记录。基线输出统一使用 `observed_at` 并保存 `machine_status`；
  `lastlinename` 只辅助核对上一产品，当前订单始终来自 `linename`。

运行默认正式请求：

```powershell
python examples/run_cutline_algorithm.py
```

也可以传入场景路径，例如：

```powershell
python examples/run_cutline_algorithm.py examples/scenarios/v3_stockout_auto.json
```

运行真实确认轮：

```powershell
python examples/run_cutline_algorithm.py examples/scenarios/v3_return_round_2.json
```

脚本通过 `CutlineService` 输出增强 `CutlineEvaluateResponse`。HTTP 兼容路由
`/stub/algo/run` 会投影为不含 `persistence_state` 的基础业务响应；闭环联调应使用
`/cutline/evaluate`。
