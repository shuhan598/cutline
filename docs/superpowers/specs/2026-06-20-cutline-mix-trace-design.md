# 混料追溯算法 B 实现设计

> 对应《算法设计 v2》第四章「算法 B：混料追溯」。本 spec 是该模块的**实现设计**（落到代码的契约），不修改 v2 目标规格书。

## 目标与范围

实现 `MixTraceService`：接收一次切线事件，计算混料起始时刻 `T_mix_start`，产出一条混料通知（含型号组成、估算片数、生命周期状态），供甲方 MES 做花篮级标记。

**本 spec 范围**：纯算法组件 + 门面 + pytest 假数据，沿用现有「组件吃 Pydantic 对象、门面映射对外响应」模式。

**不在本 spec 范围**（各自独立推进）：
- HTTP API / 入口层（`mix_trace_api`/`main`/`run`）。
- 批量多事件入参（按文档 4.2，多次切线 = 多次调用，单数 `cutline_event` 契约不变）。
- 已知小遗留 P7/P9 及评审 3 项。

## 架构与组件（轻量组件+门面）

```
app/core/mix_trace/__init__.py              # 空
app/core/mix_trace/mix_start_calculator.py  # MixStartCalculator 纯算法
app/service/mix_trace_service.py            # MixTraceService 门面（替换单行占位）
```

- `MixStartCalculator.calculate(request: MixTraceRequest) -> Optional[MixTraceNotification]`
  - 纯算法，吃整个 request（与切线链「组件吃对象」一致）。
  - 数据齐全 → 返回 `MixTraceNotification`；缺产能记录或产能 ≤ 0 → 返回 `None`。
- `MixTraceService.trace(request: MixTraceRequest) -> MixTraceResponse`
  - 调 calculator。`None` → `MixTraceResponse(success=False, message=指明机台编码与前型号, notifications=[])`；否则 → `MixTraceResponse(success=True, message="", notifications=[notification])`。

不造内部 result 对象（`MixTraceNotification` 与计算结果近 1:1）；不造 adapter（`MixTraceRequest` 本身即契约，测试用 `model_validate` 读 JSON）。

## 算法规格

输入（`MixTraceRequest`）：`current_time`、`cutline_event=(equipment_code, cut_time, previous_product_code=model_A, next_product_code=model_B)`、`capacity_records`、`config`。

数值全程经 `app/utils/numeric.safe_float`，时间用 `datetime + timedelta`。

```
record = capacity_records 中满足
         equipment_code == event.equipment_code 且 product_code == event.previous_product_code
若 record 不存在 或 safe_float(record.actual_capacity_per_hour) <= 0:
    return None

残留消耗时长_min = config.max_feed_basket_count × config.basket_capacity
                   / record.actual_capacity_per_hour × 60
T_mix_start = event.cut_time + timedelta(minutes =
                  残留消耗时长_min + config.agv_delivery_minutes + record.process_time_minutes)

m              = config.mix_basket_count
estimated_total = m × config.basket_capacity
half           = (m / 2) × config.basket_capacity
product_compositions = [
    {"product_code": model_A, "sequence_no": 1, "estimated_quantity": half},
    {"product_code": model_B, "sequence_no": 2, "estimated_quantity": half},
]
status = "arrived" if current_time >= T_mix_start else "pending"

return MixTraceNotification(
    source_equipment_code = event.equipment_code,
    cut_time              = event.cut_time,
    previous_product_code = model_A,
    next_product_code     = model_B,
    mix_start_time        = T_mix_start,
    mix_basket_count      = m,
    estimated_total_quantity = estimated_total,
    product_compositions  = product_compositions,
    status                = status,
)
```

**单位**：`record.process_time_minutes` 已是分钟；`config.agv_delivery_minutes` 分钟；残留按「片 ÷ (片/小时) = 小时」再 ×60 转分钟。

**口径自检（文档 4.1 例 pk03）**：`cut_time=10:00`、`model_A=HG210R`、`actual_capacity_per_hour=9600`、`process_time_minutes=60`、`agv_delivery_minutes=5`、`mix_basket_count=2`、`basket_capacity=120`、`max_feed_basket_count=10`：
- 残留 = 10×120/9600×60 = **7.5 min**
- T_mix_start = 10:00 + 7.5 + 5 + 60 = **11:12:30**
- estimated_total = 2×120 = **240**；A/B 各 **120**
- 若 current_time=10:00 < 11:12:30 → status=**pending**

## 数据流与接口

调用方 → `MixTraceRequest`（Pydantic）→ `MixTraceService.trace` → `MixTraceResponse`。

**schema 零改动**。复用既有字段：
- `MixTraceRequest`：`request_id?`、`current_time`(必填)、`cutline_event`(必填)、`capacity_records`、`config`。
- `CutlineEvent`：`equipment_code`、`cut_time`、`previous_product_code`、`next_product_code`。
- `MachineCapacityRecord`：`equipment_code`、`product_code`、`actual_capacity_per_hour`、`process_time_minutes`。
- `AlgorithmConfig`：`agv_delivery_minutes`(默认5)、`mix_basket_count`(默认2)、`basket_capacity`(默认120)、`max_feed_basket_count`(默认10)。
- `MixTraceNotification`：`source_equipment_code`、`cut_time`、`previous/next_product_code`、`mix_start_time`(必填)、`mix_basket_count`、`estimated_total_quantity`、`product_compositions`、`status`(默认 "pending")。
- `MixTraceResponse`：`success`、`message`、`notifications`。

## 错误处理

- 缺产能记录 / 产能 ≤ 0：calculator 返回 `None`，门面回 `success=False` + message（含机台编码与前型号）+ `notifications=[]`。
- 不为正常缺数据抛异常；非法入参由 Pydantic 校验兜底。

## 测试策略

新增 fixture 与测试（沿用 `examples/` 假数据 + `tests/` 按场景分目录 的约定）：

- `examples/cutline_mix_trace_input.json`：pk03 例（产能 9600、工艺 60min、agv 5、m=2、current_time=10:00）。
- `tests/cutline_mix_trace_input/__init__.py`（空）
- `tests/cutline_mix_trace_input/test_mix_start_calculator.py`
  - 数值：残留 7.5、`mix_start_time == datetime(...,11,12,30)`、`estimated_total_quantity == 240`、组成 A/B 各 120、`mix_basket_count == 2`。
  - 生命周期：`current_time < T_mix_start → status=="pending"`；`current_time >= T_mix_start → status=="arrived"`。
  - 缺数据：capacity_records 不含该 (机台,前型号) → `calculate` 返回 `None`；产能=0 → `None`。
- `tests/cutline_mix_trace_input/test_mix_trace_service.py`
  - 成功路径：`success is True`，`len(notifications)==1`，字段与上一致。
  - 缺数据路径：`success is False`，`notifications==[]`，`message` 含机台编码。

**验收**：`python -m pytest -q` 全绿（64 + 新增），无 ERROR；切线既有测试不回归；算法层 0 处裸 dict、0 处本地 `safe_float`。

## 多次切线

每次切线事件 = 一次 `trace` 调用 = 一条独立通知（文档 4.2「各次切线的混料通知独立推送」），与单数 `cutline_event` 契约一致。
