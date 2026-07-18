# 光伏车间切线算法服务

本仓库提供新版切线算法的本地服务编排与测试。当前唯一正式调用链是：

```text
CutlineAlgorithmRequest
  -> SnapshotAdapter.to_algorithm_snapshot
  -> CutlinePipeline.evaluate_algorithm
  -> AlgorithmResponseMapper.to_response
  -> CutlineAlgorithmResponse
```

算法输出建议和计算结果，不直接控制机台，也不写数据库。当前对后端提供同步 HTTP 接口 `POST /stub/algo/run`：后端提交 `CutlineAlgorithmRequest` JSON，同一次请求直接返回 `CutlineAlgorithmResponse` JSON。

## 请求与内部配置

后端请求使用 `CutlineAlgorithmRequest`。请求中不传 `config`；`SnapshotAdapter` 转换为内部 `AlgorithmSnapshot` 时，由 `AlgorithmConfig` 注入默认运行参数。历史活动切线事件通过请求顶层 `active_cutline_events` 传入。该事件只保存下一轮切回判断需要的 12 个字段：`event_id`、`machine_code`、源/目标订单、车间、目标 Buffer、上下游工序、目标硅片尺寸/规格、切线开始时间和 `negative_start_time`。

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

