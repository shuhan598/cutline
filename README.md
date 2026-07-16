# 光伏车间切线算法服务

本仓库提供新版切线算法的本地服务编排与测试。当前唯一正式调用链是：

```text
CutlineAlgorithmRequest
  -> SnapshotAdapter.to_algorithm_snapshot
  -> CutlinePipeline.evaluate_algorithm
  -> AlgorithmResponseMapper.to_response
  -> CutlineAlgorithmResponse
```

算法输出建议和计算结果，不直接控制机台，也不写数据库。`app/api/` 与 `app/main.py` 目前没有可供外部调用的实际 HTTP 路由。

## 请求与内部配置

后端请求使用 `CutlineAlgorithmRequest`。请求中不传 `config`；`SnapshotAdapter` 转换为内部 `AlgorithmSnapshot` 时，由 `AlgorithmConfig` 注入默认运行参数。历史活动切线事件通过请求顶层 `active_cutline_events` 传入，并随计算结果返回新增或更新后的事件，形成后端持久化闭环。

默认正式切线时刻就是方案生成时刻，切线执行延迟为 0 分钟。混料追溯以该正式切线时刻为基础计算，不再额外增加 15 分钟切线延迟。

请求样例见 `examples/backend_request_sample.json`，空结构响应样例见 `examples/cutline_algorithm_response_sample.json`。运行正式服务链：

```powershell
python examples/run_cutline_algorithm.py
```

## 响应

`CutlineAlgorithmResponse` 公开字段为：

- `calculation_time`
- `stockout_warnings`
- `overflow_warnings`
- `cutline_decisions`
- `return_results`
- `silk_screen_results`
- `mixing_trace_records`
- `mixing_trace_failures`
- `new_active_cutline_events`
- `updated_active_cutline_events`
- `errors`

其中单条预警或候选计算失败会记录到 `errors`，不影响其它可独立计算的结果。

## 测试

安装 `requirements.txt` 中的依赖后运行：

```powershell
pytest -q
```

样例契约可单独验证：

```powershell
pytest -q tests/test_current_examples.py
```
