# 光伏车间切线算法服务

## 项目当前阶段说明

本项目当前还处于算法测试阶段，重点是先把切线算法里的核心计算链路跑通。

- 目前不直接对接甲方真实接口。
- 当前算法使用 `examples` 目录下的 JSON 假数据进行测试。
- 算法输入是统一整理后的 `dict` / JSON 数据。
- 当前重点是先跑通：净消耗速率计算、断料耗尽时间预测、断料预警判断、候选机台筛选。

## 当前已实现的算法模块

### 1. 区间净消耗速率计算

对应文件：

- `app/core/net_rate/net_rate_calculator.py`

计算逻辑：

- 以 `buffer_code + product_code + process_from + process_to` 为一个计算单元。
- 统计上游工序 `process_from` 中，当前产品型号对应的 `running` 机台产出速率。
- 统计下游工序 `process_to` 中，当前产品型号对应的 `running` 机台吞入速率。
- 净消耗速率计算公式：

```text
net_rate_per_hour = downstream_input_per_hour - upstream_output_per_hour
```

含义：

- `net_rate_per_hour > 0`：Buffer 库存正在减少，存在断料风险。
- `net_rate_per_hour = 0`：Buffer 库存基本平衡。
- `net_rate_per_hour < 0`：Buffer 库存正在增加，后续可用于溢满风险判断。

### 2. 断料耗尽时间计算

对应文件：

- `app/core/prediction_time/depletion_time/depletion_time_calculator.py`

计算逻辑：

- 根据当前 Buffer 库存和净消耗速率，计算库存还能支撑多久。
- 计算公式：

```text
depletion_minutes = inventory_quantity / net_rate_per_hour * 60
```

说明：

- 只有 `net_rate_per_hour > 0` 时才计算耗尽时间。
- 如果 `net_rate_per_hour <= 0`，则当前不认为会发生断料，`depletion_minutes` 为 `None`。
- `depletion_minutes` 越小，断料风险越紧急。

### 3. 断料预警判断

对应文件：

- `app/core/warning/stockout_warning.py`

判断逻辑：

- 从 `data["config"]["cutline_lead_minutes"]` 中读取切线提前量。
- 当前规则：

```text
depletion_minutes <= cutline_lead_minutes 时触发断料预警
```

说明：

- 当前假数据中 `cutline_lead_minutes` 通常设置为 `30`。
- 如果耗尽时间小于或等于 30 分钟，则 `warning_triggered = True`。
- 如果耗尽时间大于 30 分钟，则不触发预警。

### 4. 候选机台筛选

对应文件：

- `app/core/candidate_machine/candidate_machine_finder.py`

筛选逻辑：

- 只对已经触发断料预警的 `stockout` warning 进行候选机台筛选。
- 候选机台当前筛选条件：

1. 机台状态 `status == "running"`。
2. 机台所在工序 `process_code == 断料预警的 process_from`。
3. 机台当前生产型号 `product_code` 不能等于目标断料型号。
4. 当前机台生产型号与目标型号 `wafer_size` 相同。
5. 当前机台生产型号与目标型号 `shape_code` 相同。

说明：

- 如果多台机台都满足候选条件，会全部进入 `candidates` 列表。
- 当前只生成候选机台池，不做最终切线决策。
- 当前还没有实现借出影响校验、切入量计算、候选机台打分、切回逻辑。

### 5. 多个断料预警的处理顺序

处理逻辑：

- 当同时出现多个断料预警时，按照 `depletion_minutes` 从小到大排序。
- `depletion_minutes` 越小，说明越快断料，优先级越高。
- 当前排序范围是全局排序，不按 Buffer 分组。
- 当前不新增 `priority_rank` 字段，输出顺序本身就是优先级顺序。

## 当前算法主流程

```text
输入 JSON 假数据
↓
calculate_all_net_rates
↓
calculate_all_depletion_times
↓
evaluate_all_stockout_warnings
↓
find_all_candidates
↓
输出净消耗、耗尽时间、断料预警、候选机台结果
```

## 测试数据与测试目录对应关系

| 假数据文件 | 对应测试目录 | 说明 |
| --- | --- | --- |
| `examples/cutline_sample_input.json` | `tests/cutline_sample_input/` | 基础样例测试，验证最简单的单 Buffer、少量机台、基础断料预警和候选机台筛选 |
| `examples/cutline_complex_input.json` | `tests/cutline_complex_input/` | 复杂场景测试，验证多 Buffer、多型号、多个断料预警、无候选机台、多个候选机台、全局紧急程度排序 |

## 如何运行测试

运行基础样例测试：

```bash
python -m pytest tests/cutline_sample_input -q
```

运行复杂场景测试：

```bash
python -m pytest tests/cutline_complex_input -q
```

运行全部测试：

```bash
python -m pytest tests -q
```

## 如何查看复杂场景计算结果

当前可以通过打印算法函数的返回结果查看每一步计算结果。常用链路是：

- `calculate_all_net_rates`
- `calculate_all_depletion_times`
- `evaluate_all_stockout_warnings`
- `find_all_candidates`

也就是说，可以读取 `examples/cutline_complex_input.json`，依次调用上面几个函数，然后打印每一步的返回值。这样能看到每个 Buffer + 产品型号的净消耗速率、耗尽时间、是否触发断料预警，以及最终筛选出的候选机台列表。
