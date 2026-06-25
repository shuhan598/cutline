# 光伏车间切线算法服务

## 1. 项目简介

本项目用于光伏车间生产过程中的切线评估。算法根据 Buffer 库存、机台实时状态、机台主数据、产线/车间信息、产品型号、工序路线、产能记录、订单进度和已发生切线事件等数据，识别断料、溢满、丝网清台等风险，并生成切线方案、人工介入提示、切回建议和单次混料通知。

需要注意：

- 算法服务不直接控制机台。
- 算法输出的是预警、推荐方案和建议结果。
- 后端系统、现场系统或人工流程负责确认、下发和执行切线。
- 当前项目主要是算法服务层和本地测试样例，不是完整 MES 系统。

## 2. 当前功能范围

当前代码已经覆盖的主要能力包括：

1. 断料预警：根据区间库存和净消耗速率预测耗尽时间。
2. 溢满预警：根据段容量、同车间同 Buffer 库存汇总和净速率预测溢满时间。
3. 断料候选机台筛选：按车间、工序、运行状态、产品兼容性和产能记录筛选可切入机台。
4. 溢满候选机台筛选：从正在生产溢满型号的机台中筛选可切走机台和目标型号。
5. 切线方案生成：对断料和溢满候选机台做逐台选择，生成方案或人工介入提示。
6. 人工介入提示：当候选池不足或风险无法由候选机台解决时输出。
7. 丝网清台预警：根据终端工序、订单剩余量和清台提前时间生成准备预警。
8. 切回建议：基于已追踪切线事件、净速率连续为负时长和安全库存水位判断是否建议切回。
9. 单次混料追踪：根据一次 `CutlineEvent` 计算混料起始时间和简化型号组成。
10. 车间维度隔离：净速率、候选机台、切线方案、溢满、切回和混料相关数据逐步引入 `workshop_code` / `workshop_name`。
11. S2 车间 P/R 互切规则：在非丝网工序、同尺寸前提下允许 S2 车间 P/R 形状互切。
12. 本地假数据与 pytest 测试：`examples/` 提供 JSON 样例，`tests/` 覆盖主要算法模块。

当前仍需继续完善或核对的内容：

- 批量多次切线的混料追踪尚未实现，目前 `MixStartCalculator` 只处理单次切线事件。
- 溢满公式当前仍基于现有产品区间净速率近似计算，后续可优化为 Buffer 整体库存增长速率或历史库存快照变化率。
- FastAPI 接口层目前基本是占位文件，尚未形成可直接对外调用的 HTTP 路由。
- 对外响应模型已有车间字段，但部分顶层字段和回传事件的车间信息仍需要结合后端契约继续核对和补齐。
- 当前样例数据主要用于算法验证，尚未接入真实后端或 MES 数据源。

## 3. 项目目录结构

```text
app/
  adapters/              # JSON / dict 转 CutlineSnapshot 的适配器
  api/                   # FastAPI 接口占位，目前尚未完整实现路由
  config/                # 配置模型
  core/                  # 算法核心模块
  schemas/               # 输入、内部结果、对外响应数据结构
  service/               # 算法管道编排和服务门面
  state/                 # 运行态占位模块
  utils/                 # 数值转换、时间、校验、ID 等工具

docs/                    # 设计说明和问题清单
examples/                # 本地测试用 JSON 假数据
tests/                   # pytest 自动化测试

requirements.txt         # Python 依赖
run.py                   # 本地运行入口
README.md                # 项目说明文档
```

核心代码大致分布如下：

- `app/schemas/common_schema.py`：机台、产线、库存、产能、订单、切线事件等通用数据模型。
- `app/schemas/request_schema.py`：算法输入请求模型，包括 `CutlineSnapshot` 和 `MixTraceRequest`。
- `app/schemas/result_schema.py`：算法内部结果模型。
- `app/schemas/response_schema.py`：对外响应模型。
- `app/core/net_rate/`：净速率计算。
- `app/core/prediction_time/`：断料和溢满时间预测。
- `app/core/warning/`：预警判断。
- `app/core/candidate_machine/`：候选机台筛选和产品兼容规则。
- `app/core/cutline_plan/`：切线方案生成。
- `app/core/silk_screen/`：丝网清台预警。
- `app/core/return_judge/`：切回判断。
- `app/core/mix_trace/`：混料追踪。
- `app/core/workshop/`：车间解析。
- `app/service/cutline_pipeline.py`：切线评估主流程编排。
- `app/service/cutline_service.py`：切线评估对外服务封装。
- `app/service/mix_trace_service.py`：混料追踪对外服务封装。

## 4. 核心算法流程

### 4.1 净速率计算

净速率用于描述某个 Buffer 区间内库存变化趋势：

```text
net_rate = downstream_input_rate - upstream_output_rate
```

其中：

- `downstream_input_rate` 表示下游工序对该型号的消耗速率。
- `upstream_output_rate` 表示上游工序对该型号的补充速率。
- 当 `net_rate > 0` 时，表示库存被消耗，可能产生断料风险。
- 当 `net_rate < 0` 时，表示库存在增长，可能产生溢满风险，或作为切回判断的信号。

当前净速率计算会结合 `WorkshopResolver` 按车间隔离，避免不同车间的同型号、同工序数据混算。

### 4.2 断料逻辑

断料链路的主要流程：

1. `NetRateCalculator` 计算区间净速率。
2. `DepletionTimeCalculator` 根据库存和正向净消耗速率预测耗尽时间。
3. `StockoutWarningEvaluator` 判断耗尽时间是否落入切线提前预警窗口。
4. `StockoutCandidateFinder` 在同车间、同工序范围内寻找可切入目标型号的候选机台。
5. `CutlinePlanBuilder.build_stockout()` 逐台选择候选机台，生成切线方案或人工介入提示。

断料时间近似公式：

```text
depletion_minutes = inventory_quantity / net_rate_per_hour * 60
```

断料候选机台会计算：

- `utilization_rate`：当前输出 / 当前产品产能。
- `idle_rate`：空闲度，用于断料场景优先选择更空闲的机台。
- `contribution_capacity_per_hour`：切到目标型号后可贡献的产能。

### 4.3 溢满逻辑

溢满链路的主要流程：

1. `NetRateCalculator` 计算区间净速率。
2. `OverflowTimeCalculator` 基于负净速率、段容量和同车间同 Buffer 库存汇总预测溢满时间。
3. `OverflowWarningEvaluator` 判断溢满时间是否进入切线提前预警窗口。
4. `OverflowCandidateFinder` 从正在生产溢满型号的机台中寻找可切走的机台和目标型号。
5. `CutlinePlanBuilder.build_overflow()` 按候选机台利用率排序生成方案或人工介入提示。

当前溢满时间近似公式：

```text
overflow_minutes = (segment_capacity - current_inventory) / abs(net_rate_per_hour) * 60
```

其中 `current_inventory` 会按同车间、同 Buffer 汇总库存。溢满候选机台的 `utilization_rate` 使用当前机台正在生产的溢满型号计算；目标型号产能只用于计算切走后的贡献产能。

### 4.4 丝网清台预警

丝网清台逻辑由 `SilkScreenHandler` 处理。当前逻辑会：

1. 根据工艺路线识别终端出料工序。
2. 遍历运行中的丝网机台。
3. 根据订单剩余量和当前产能估算完成时间。
4. 用配置中的清台提前时间计算准备时间。
5. 通过 `WorkshopResolver` 解析丝网机台所属车间，并写入结果。

当前只补充预警和结果输出，不改变丝网工序识别、订单剩余量或完成时间计算公式。

### 4.5 切回判断

切回判断由 `ReturnEvaluator` 处理，输入来自 `snapshot.active_cutline_events`。

判断条件保持为：

1. 当前净速率为负：`net_rate_per_hour < 0`。
2. 净速率连续为负时间大于稳定窗口：`negative_duration_minutes > stability_window_minutes`。
3. 当前库存高于安全库存水位：`inventory_quantity > safety_inventory_quantity`。

安全库存水位近似计算：

```text
safety_inventory_quantity = cutline_lead_minutes / 60 * abs(net_rate_per_hour)
```

当前切回判断优先使用切线事件上的 `workshop_code` / `workshop_name`。如果事件缺少车间编码，则尝试通过机台主数据和产线主数据反查机台所属车间。净速率和库存匹配时优先按车间、产品型号、上游工序匹配，兼容旧数据时才退回宽松匹配。

### 4.6 混料追踪

混料追踪由 `MixStartCalculator` 处理，目前是一条 `CutlineEvent` 生成一条 `MixTraceNotification`。

混料起始时间近似计算：

```text
mix_start_time =
  cut_time
  + max_feed_basket_count * basket_capacity / capacity_per_hour * 60 minutes
  + agv_delivery_minutes
  + process_time_minutes
```

当前混料通知会直接透传切线事件上的 `workshop_code` / `workshop_name`。混料组成采用简化估算：一半旧型号、一半新型号。批量混料追踪、同机台多次切线排序和更复杂的批次组成尚未实现。

## 5. 车间维度说明

项目中车间维度主要通过以下字段表达：

- `workshop_code`：车间编码，例如 `S1`、`S2`。
- `workshop_name`：车间名称，例如 `S2车间`。

车间解析主要由 `app/core/workshop/workshop_resolver.py` 完成：

- 机台车间：通过 `MachineMaster.line_code` 查找 `LineMaster`。
- 库存车间：通过 `BufferInventoryItem.cycle_code` 查找 `CycleMaster`。
- 编码匹配会做 `strip().upper()` 归一化，避免大小写和空格导致匹配失败。

当前需要按车间隔离的典型场景：

- 净速率计算。
- 断料和溢满候选机台筛选。
- 溢满库存汇总。
- 切回判断中的净速率和库存匹配。
- 丝网清台预警输出。
- 混料通知输出。

## 6. 输入数据说明

切线评估的主要输入模型是 `CutlineSnapshot`，位于 `app/schemas/request_schema.py`，常用字段包括：

- `current_time`：当前评估时间。
- `machine_statuses`：机台实时状态。
- `machine_masters`：机台主数据。
- `line_masters`：产线和车间主数据。
- `cycle_masters`：周期/区域和车间主数据。
- `product_models`：产品型号主数据。
- `process_route_steps`：工艺路线。
- `buffer_segments`：Buffer 区间定义。
- `buffer_inventories`：Buffer 库存。
- `capacity_records`：机台产能记录。
- `orders`：订单数据。
- `active_cutline_events`：当前仍在追踪的切线事件。
- `config`：算法配置。

混料追踪的主要输入模型是 `MixTraceRequest`，包括：

- `cutline_event`：单次切线事件。
- `capacity_records`：产能记录。
- `config`：混料相关配置。

## 7. 输出结果说明

切线评估的对外响应模型是 `CutlineEvaluateResponse`，位于 `app/schemas/response_schema.py`，主要包含：

- `warnings`：断料、溢满或丝网清台预警。
- `plans`：切线推荐方案。
- `manual_interventions`：人工介入提示。
- `return_suggestions`：切回建议。
- `tracked_events`：需要后续追踪的切线事件。

混料追踪的对外响应模型是 `MixTraceResponse`，主要包含：

- `notifications`：混料通知列表。

响应模型中与车间相关的字段通常为可选字段，默认值为 `None`，用于兼容旧数据和渐进式接入。

## 8. 本地运行方式

建议使用 Python 3.11 或更高版本。当前测试环境可在 Python 3.13 下通过。

安装依赖：

```bash
python -m pip install -r requirements.txt
```

运行测试：

```bash
pytest
```

或使用精简输出：

```bash
pytest -q
```

当前 `requirements.txt` 主要依赖：

- `pydantic`
- `pydantic-settings`
- `fastapi`
- `uvicorn`
- `pytest`

## 9. 示例数据

`examples/` 目录下提供了多组本地 JSON 样例：

- `cutline_sample_input.json`：基础断料场景。
- `cutline_complex_input.json`：较复杂的断料和方案场景。
- `cutline_overflow_input.json`：溢满场景。
- `cutline_return_input.json`：切回判断场景。
- `cutline_silk_screen_input.json`：丝网清台预警场景。
- `cutline_mix_trace_input.json`：混料追踪场景。

这些样例主要用于算法单元测试和服务流程测试，不代表真实生产接口字段已经最终定稿。

## 10. 测试说明

测试位于 `tests/` 目录，主要覆盖：

- `tests/adapters/`：输入适配器。
- `tests/core/`：通用核心逻辑，例如产品兼容、速率策略、车间解析。
- `tests/cutline_sample_input/`：基础断料流程。
- `tests/cutline_complex_input/`：复杂断料流程。
- `tests/cutline_overflow_input/`：溢满时间、预警、候选机台、方案和服务流程。
- `tests/cutline_return_input/`：切回判断和服务映射。
- `tests/cutline_silk_screen_input/`：丝网清台预警。
- `tests/cutline_mix_trace_input/`：单次混料追踪。
- `tests/schemas/`：数据模型兼容性。
- `tests/utils/`：工具函数。

当前全量测试命令：

```bash
pytest
```

## 11. 当前待优化事项

后续可继续推进的事项包括：

1. 明确真实后端接口契约，并将 `app/api/` 从占位文件补充为可调用路由。
2. 根据真实生产数据校正溢满预测公式。
3. 完善批量混料追踪，支持同一机台多次切线事件的排序和连续批次推导。
4. 继续核对所有对外响应字段中的车间维度，保证后端、前端和算法口径一致。
5. 将示例数据逐步替换或扩展为更贴近真实生产的数据集。
6. 增加异常输入、缺失主数据和边界容量场景的测试。
7. 根据现场策略继续细化候选机台排序和人工介入原因。

