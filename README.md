# 光伏车间切线算法服务

本仓库提供新版切线算法的本地服务编排与测试。当前唯一正式调用链是：

```text
原始请求 JSON
  -> BackendRequestLoader
  -> CutlineAlgorithmRequest
  -> SnapshotAdapter.to_algorithm_snapshot
  -> CutlinePipeline.evaluate_algorithm
  -> AlgorithmResponseMapper.to_response
  -> CutlineAlgorithmResponse
```

算法输出建议和计算结果，不直接控制机台，也不写数据库。当前对后端提供同步 HTTP
接口 `POST /stub/algo/run` 和 `POST /cutline/evaluate`：后端提交请求 JSON，
同一次请求直接返回 `CutlineAlgorithmResponse` JSON。

## 请求与内部配置

后端请求由 `BackendRequestLoader` 标准化后形成 `CutlineAlgorithmRequest`。请求中不传
`config`；`SnapshotAdapter` 转换为内部 `AlgorithmSnapshot` 时，由
`AlgorithmConfig` 注入默认运行参数。历史活动切线事件通过请求顶层
`active_cutline_events` 传入。该事件只保存下一轮切回判断需要的 12 个字段：
`event_id`、`machine_code`、源/目标订单、车间、目标 Buffer、上下游工序、
目标硅片尺寸/规格、切线开始时间和 `negative_start_time`。

`machine_realtime` 不再携带 `order_code`。甲方 AGV 原始字段
`equipmentid/equipmentname/lastlinecode/lastlinename/waferspec/createtime` 只在 Loader
中映射为标准的
`machine_code/machine_name/order_code/order_name/wafer_spec/binding_time`。快照按
UTC+08:00 选择不晚于 `snapshot_time` 的最新有效绑定，并写入内部
`AlgorithmMachineRuntime.current_order_code`。机台当前订单编码、订单名称和硅片规格均以
选中的 AGV 绑定为准；`AlgorithmMachineRuntime` 不保存当前硅片规格。产线
`wafer_spec` 仅为兼容字段，机台到产线再到车间的归属链保持不变；机台工序始终来自
`machine_master`。需要参与计算的订单如果没有有效 AGV `wafer_spec`，算法会抛出明确的
数据错误，绝不回退到 `line.wafer_spec`。

默认正式切线时刻就是方案生成时刻，切线执行延迟为 0 分钟。混料追溯以该正式切线时刻为基础计算，不再额外增加 15 分钟切线延迟。

请求样例见 `examples/backend_request_sample.json`，空结构响应样例见 `examples/cutline_algorithm_response_sample.json`。运行正式服务链：

```powershell
python examples/run_cutline_algorithm.py
```

## V3 标准假数据

正式示例和完整流程测试统一使用 `S2` / `S2车间`，产线编码为
`S2-SW1A`、`S2-SW1B`、`S2-SW2A`、`S2-SW2B`，机台编码从
`EA001` 开始。工艺路线固定为：

```text
发料机 -> 制绒 -> 碱抛 -> 背膜 -> 硼扩 -> POLY -> RCA -> 退火 -> 氧化 -> 正膜 -> 丝网
```

相邻工序使用数字字符串 Buffer `310110301` 至 `310110310`。统一工厂入口位于
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

其中：

- 甲方业务结果：`stockout_warnings`、`overflow_warnings`、`cutline_decisions`、`return_recommendations`、`silk_screen_results`、`mixing_trace_records`。
- 后端算法状态：`new_active_cutline_events`、`updated_active_cutline_events`、`closed_active_cutline_event_ids`。
- 后端错误记录：`errors`。单条预警、切回或混料计算失败不会清除其它成功结果。

`negative_start_time` 只属于后端算法状态，不展示给甲方。更新事件中的 `negative_start_time: null` 表示后端必须清空原计时。算法一旦输出 `return_recommendations`，会在同轮输出对应的关闭 ID；后端应立即移除该活动事件，下一轮不再提交，不等待现场实际完成切回。现场实际切回时间 `returned_time` 由后端或现场系统记录。

## 测试

安装 `requirements.txt` 中的依赖后运行：

```powershell
pytest -q
```

样例契约可单独验证：

```powershell
pytest -q tests/test_current_examples.py
```

