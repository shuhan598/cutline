# App 全量中文注释完善实施计划

**目标：** 为 `app/` 下所有 Python 模块补充完整、可维护的中文注释和文档字符串，不改变任何运行逻辑、接口字段或计算结果。

**方式：** 按职责分批梳理模块级职责、公共类/函数契约、关键算法分支和异常/降级路径；优先补充业务边界与数据流注释，避免对显而易见的逐行代码增加噪声。

**验证：** 每批修改后运行对应测试，全部批次结束后运行完整测试套件和 `git diff --check`。

---

## 批次 1：公共入口和配置

文件：

- `app/main.py`
- `app/api/*.py`
- `app/service/*.py`
- `app/config/*.py`

注释重点：HTTP 接口输入输出、服务编排顺序、持久化状态构建、配置默认值和环境变量来源。

## 批次 2：请求适配和后端数据边界

文件：

- `app/adapters/*.py`
- `app/schemas/backend_request_schema.py`
- `app/schemas/request_schema.py`
- `app/schemas/pending_cutline_schema.py`

注释重点：后端字段到内部模型的转换、快照一致性、引用校验、绑定选择、无效 Buffer 记录的忽略规则和错误隔离。

## 批次 3：核心数据模型和响应映射

文件：

- `app/schemas/common_schema.py`
- `app/schemas/result_schema.py`
- `app/schemas/response_schema.py`
- `app/mappers/*.py`
- `app/core/buffer_aggregation/*.py`

注释重点：模型字段语义、能力开关、物理 Buffer 与订单粒度的关系、内部结果到公开响应的映射规则。

## 批次 4：预警、候选机台和预测时间

文件：

- `app/core/warning/*.py`
- `app/core/candidate_machine/*.py`
- `app/core/prediction_time/**/*.py`
- `app/core/net_rate/*.py`

注释重点：库存告警触发条件、候选机台筛选顺序、速率与时间计算公式、不可计算时的降级原因。

## 批次 5：切线计划、确认、回流和丝网业务

文件：

- `app/core/cutline_plan/*.py`
- `app/core/cutline_confirmation/*.py`
- `app/core/return_judge/*.py`
- `app/core/silk_screen/*.py`
- `app/core/mixing_trace/*.py`

注释重点：决策状态机、人工干预条件、待确认计划、回流判断、丝网转换和混料追踪的事件流。

## 批次 6：车间解析、工具函数和收尾验证

文件：

- `app/core/workshop/*.py`
- `app/utils/*.py`
- 所有 `app/**/__init__.py`

注释重点：工序循环解析、机台/车间关系、工具函数边界和空值处理；最后检查所有非空模块是否具备模块说明和公共接口说明。

验证命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

