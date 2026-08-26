"""集中定义对外四位数字错误码及其英文兼容标识。"""

from __future__ import annotations


_INPUT_CODE_BASE_BY_DATASET = {
    "orders": 2100,
    "machine_realtime": 2200,
    "machine_master": 2200,
    "machine_process_times": 2200,
    "machine_lines": 2200,
    "agv_relations": 2300,
    "buffer_realtime": 2400,
    "buffer_master": 2400,
    "products": 2500,
    "process_routes": 2600,
    "workshops": 2700,
    "lines": 2800,
    "pending_cutline_plans": 2900,
    "active_cutline_events": 2920,
    "return_suggested_event_ids": 2940,
    "mixed_cutline_event_ids": 2940,
    "snapshot_meta": 2960,
    "request": 2980,
}

_INPUT_REASON_OFFSET = {
    "empty_dataset": 1,
    "empty_code": 2,
    "empty_value": 3,
    "null_field": 4,
    "duplicate_key": 5,
    "invalid_value": 6,
    "invalid_reference": 7,
    "missing_reference": 8,
    "ambiguous_reference": 9,
    "name_mismatch": 10,
    "workshop_mismatch": 11,
    "binding_conflict": 12,
    "missing_agv_binding": 13,
    "unknown_process_name": 14,
    "duplicate_sequence": 15,
    "broken_process_route": 16,
    "invalid_last_process_downstream": 17,
    "missing_silk_screen_process": 18,
    "duplicate_silk_screen_process": 19,
    "silk_screen_not_last": 20,
    "load_error": 21,
    "extra_forbidden": 91,
    "missing": 92,
    "float_parsing": 93,
    "model_type": 94,
}

_SPECIAL_INPUT_REASON_OFFSET = {
    "empty_dataset": 1,
    "empty_code": 2,
    "empty_value": 3,
    "null_field": 4,
    "duplicate_key": 5,
    "invalid_value": 6,
    "invalid_reference": 7,
    "missing_reference": 8,
    "ambiguous_reference": 9,
    "name_mismatch": 10,
    "workshop_mismatch": 11,
    "binding_conflict": 12,
    "missing_agv_binding": 13,
    "load_error": 14,
    "extra_forbidden": 15,
    "missing": 16,
    "float_parsing": 17,
    "model_type": 18,
}

_HTTP_ERROR_CODES = {
    "STATIC_DATA_INVALID": "1001",
    "IDEMPOTENCY_KEY_REUSED": "1002",
    "CATALOG_VERSION_CONFLICT": "1003",
    "BASE_CATALOG_VERSION_NOT_FOUND": "1004",
    "BASE_CATALOG_VERSION_STALE": "1005",
    "STATIC_CATALOG_REQUIRED": "1006",
    "CATALOG_VERSION_NOT_FOUND": "1007",
    "STATIC_CATALOG_DATA_MISSING": "1008",
    "DYNAMIC_DATA_INVALID": "1009",
    "BACKEND_DATA_INVALID": "1010",
    "SNAPSHOT_CONVERSION_FAILED": "1011",
    "REQUEST_VALIDATION_ERROR": "1012",
}

_AGGREGATION_ERROR_CODES = {
    "main_id_unavailable": "3001",
    "inventory_unavailable": "3002",
    "duplicate_buffer_id": "3003",
    "static_buffer_mapping_unresolved": "3004",
    "workshop_conflict": "3005",
    "service_process_conflict": "3006",
    "capacity_unavailable": "3007",
    "inventory_at_or_above_capacity": "3008",
    "buffer_code_index_conflict": "3009",
    "order_mapping_not_found": "3010",
    "order_mapping_ambiguous": "3011",
}

_PIPELINE_ERROR_CODES = {
    ("pending_cutline_confirmation", "pending_cutline_detection_error"): "3020",
    ("active_event_creation", "pending_plan_not_found"): "3021",
    ("active_event_creation", "active_event_creation_error"): "3022",
    ("active_event_merge", "active_event_identity_conflict"): "3023",
    ("return_evaluation", "target_interval_not_found"): "3024",
    ("return_evaluation", "target_interval_ambiguous"): "3025",
    ("silk_screen_transition", "silk_screen_transition_calculation_error"): "3026",
    ("stockout_candidate", "candidate_machine_calculation_error"): "3027",
    ("overflow_candidate", "candidate_machine_calculation_error"): "3027",
    ("stockout_selection", "machine_selection_evaluation_error"): "3028",
    ("overflow_selection", "machine_selection_evaluation_error"): "3028",
    ("stockout_plan", "value_error"): "3029",
    ("overflow_plan", "value_error"): "3029",
    ("pending_cutline_creation", "value_error"): "3029",
}

_MIXING_TRACE_ERROR_CODES = {
    "selected_machine_context_incomplete": "3101",
    "same_order_transition_invalid": "3102",
    "source_order_not_found": "3103",
    "target_order_not_found": "3104",
    "cutline_plan_product_mismatch": "3105",
    "same_product_transition_no_mixing": "3106",
    "machine_runtime_not_found": "3107",
    "machine_runtime_ambiguous": "3108",
    "runtime_quantity_invalid": "3109",
    "runtime_actual_capacity_unavailable": "3110",
    "process_duration_not_found": "3111",
    "process_duration_ambiguous": "3112",
    "process_duration_invalid": "3113",
    "mix_start_time_unrepresentable": "3114",
}

_ERROR_MESSAGES = {
    "1001": "静态目录数据不合法",
    "1002": "幂等键已被不同请求占用",
    "1003": "目录版本与已有内容冲突",
    "1004": "增量更新的基准目录版本不存在",
    "1005": "增量更新的基准目录版本已过期",
    "1006": "尚未发布静态目录",
    "1007": "请求的目录版本不存在",
    "1008": "动态快照引用的静态目录数据不存在",
    "1009": "动态请求数据不合法",
    "1010": "后端数据不完整、格式错误或关联关系错误",
    "1011": "请求数据无法转换为算法快照",
    "1012": "请求格式、字段类型或载荷标准化错误",
    "2101": "必需数据集为空",
    "2102": "编码字段为空或仅包含空白字符",
    "2103": "必填业务值为空",
    "2104": "当前场景不允许字段为 null",
    "2105": "主键或业务键重复",
    "2106": "字段值不符合业务约束",
    "2107": "关联字段与目标记录不一致",
    "2108": "被引用记录不存在",
    "2109": "引用匹配到多条记录",
    "2110": "编码与名称不匹配",
    "2111": "关联记录所属车间不一致",
    "2112": "同一机台或绑定在同一时刻冲突",
    "2113": "运行机台缺少有效 AGV 绑定",
    "2114": "工序名称无法映射到内部目录",
    "2115": "同一车间工序序号重复",
    "2116": "工艺路线的上下游关系不连续",
    "2117": "最后一道工序仍填写下游工序",
    "2118": "车间路线缺少丝网工序",
    "2119": "同一车间存在多个丝网工序",
    "2120": "丝网工序不是车间最后一道工序",
    "2121": "原始后端载荷标准化失败",
    "2199": "请求数据校验失败",
    "2291": "请求包含未声明字段",
    "2292": "Schema 必填字段缺失",
    "2293": "数字字段无法解析",
    "2294": "对象类型或 JSON 结构错误",
    "2914": "原始后端载荷标准化失败",
    "2915": "请求包含未声明字段",
    "2916": "Schema 必填字段缺失",
    "2917": "数字字段无法解析",
    "2918": "对象类型或 JSON 结构错误",
    "2919": "请求数据校验失败",
    "3001": "Buffer 实时记录缺少物理 main 标识",
    "3002": "Buffer 库存不是有限的非负数",
    "3003": "同一物理 main 内存在重复的 Buffer 编码",
    "3004": "Buffer 主数据或工艺关系无法唯一匹配",
    "3005": "同一物理 main 的 Buffer 或订单车间不一致",
    "3006": "同一物理 main 的服务工序区间不一致",
    "3007": "至少一个 Buffer 没有有效的正容量",
    "3008": "物理库存达到或超过总容量",
    "3009": "一个 Buffer 编码映射到多个物理 main",
    "3010": "Buffer 绑定产品没有当前运行订单",
    "3011": "Buffer 绑定产品匹配到多个当前运行订单",
    "3020": "Pending 基线、AGV 历史或候选上下文无法无歧义比较",
    "3021": "确认结果引用的 Pending 计划不存在",
    "3022": "已确认切线无法生成合法的活跃事件",
    "3023": "新活跃事件与已有事件的业务身份冲突",
    "3024": "活跃事件找不到唯一的目标净速率区间",
    "3025": "活跃事件匹配到多个目标净速率区间",
    "3026": "丝网完工或清台准备数据无法计算",
    "3027": "候选机台的关联数据或产能无法计算",
    "3028": "候选筛选或切线影响模拟失败",
    "3029": "方案构造或 Pending 状态投影失败",
    "3099": "未分类的局部算法错误",
    "3101": "方案或事件缺少机台、订单、工序或切线时间等上下文",
    "3102": "源订单和目标订单相同",
    "3103": "源订单不存在或不唯一",
    "3104": "目标订单不存在或不唯一",
    "3105": "方案产品编码和订单产品编码不一致",
    "3106": "源产品和目标产品相同，不产生混料",
    "3107": "机台实时记录缺失",
    "3108": "同一机台存在多条实时记录",
    "3109": "30 分钟输入量或产出量不是有限的非负数",
    "3110": "根据实时量计算出的实际产能不为正",
    "3111": "机台和源产品的工艺时长缺失",
    "3112": "机台和源产品的工艺时长重复",
    "3113": "工艺时长不是有限的非负数",
    "3114": "混料开始时间计算溢出或类型错误",
    "3199": "未分类的混料追溯错误",
}

_INPUT_REASON_MESSAGES = {
    "empty_dataset": "必需数据集为空",
    "empty_code": "编码字段为空或仅包含空白字符",
    "empty_value": "必填业务值为空",
    "null_field": "当前场景不允许字段为 null",
    "duplicate_key": "主键或业务键重复",
    "invalid_value": "字段值不符合业务约束",
    "invalid_reference": "关联字段与目标记录不一致",
    "missing_reference": "被引用记录不存在",
    "ambiguous_reference": "引用匹配到多条记录",
    "name_mismatch": "编码与名称不匹配",
    "workshop_mismatch": "关联记录所属车间不一致",
    "binding_conflict": "同一机台或绑定在同一时刻冲突",
    "missing_agv_binding": "运行机台缺少有效 AGV 绑定",
    "unknown_process_name": "工序名称无法映射到内部目录",
    "duplicate_sequence": "同一车间工序序号重复",
    "broken_process_route": "工艺路线的上下游关系不连续",
    "invalid_last_process_downstream": "最后一道工序仍填写下游工序",
    "missing_silk_screen_process": "车间路线缺少丝网工序",
    "duplicate_silk_screen_process": "同一车间存在多个丝网工序",
    "silk_screen_not_last": "丝网工序不是车间最后一道工序",
    "load_error": "原始后端载荷标准化失败",
    "extra_forbidden": "请求包含未声明字段",
    "missing": "Schema 必填字段缺失",
    "float_parsing": "数字字段无法解析",
    "model_type": "对象类型或 JSON 结构错误",
}

_INPUT_REASON_ACTIONS = {
    "empty_dataset": "数据集为空",
    "empty_code": "不符合编码规则",
    "empty_value": "为空",
    "null_field": "不允许为 null",
    "duplicate_key": "存在重复值",
    "invalid_value": "不符合业务规则",
    "invalid_reference": "引用关系不一致",
    "missing_reference": "引用记录不存在",
    "ambiguous_reference": "引用匹配到多条记录",
    "name_mismatch": "编码与名称不匹配",
    "workshop_mismatch": "所属车间不一致",
    "binding_conflict": "在同一时刻存在绑定冲突",
    "missing_agv_binding": "缺少有效 AGV 绑定",
    "unknown_process_name": "无法映射到内部工序目录",
    "duplicate_sequence": "序号重复",
    "broken_process_route": "上下游关系不连续",
    "invalid_last_process_downstream": "最后一道工序不应填写下游工序",
    "missing_silk_screen_process": "缺少丝网工序",
    "duplicate_silk_screen_process": "存在多个丝网工序",
    "silk_screen_not_last": "不是最后一道工序",
    "load_error": "原始载荷标准化失败",
    "extra_forbidden": "未在请求契约中声明",
    "missing": "缺失",
    "float_parsing": "无法解析为数字",
    "model_type": "类型或 JSON 结构错误",
}

_DATASET_LABELS = {
    "orders": "订单",
    "machine_realtime": "机台实时数据",
    "machine_master": "机台主数据",
    "machine_process_times": "机台工艺时长",
    "machine_lines": "机台产线关系",
    "agv_relations": "AGV 绑定数据",
    "buffer_realtime": "Buffer 实时数据",
    "buffer_master": "Buffer 主数据",
    "products": "产品",
    "process_routes": "工艺路线",
    "workshops": "车间",
    "lines": "产线",
    "pending_cutline_plans": "Pending 计划",
    "active_cutline_events": "活跃切线事件",
    "return_suggested_event_ids": "返工建议事件",
    "mixed_cutline_event_ids": "混料事件",
    "snapshot_meta": "快照元数据",
    "request": "请求",
}

_FIELD_LABELS = {
    "order_code": "订单编码",
    "order_name": "订单名称",
    "due_date": "截至日期",
    "total_quantity": "订单总数量",
    "produced_quantity": "已生产数量",
    "remaining_quantity": "剩余数量",
    "machine_code": "机台编码",
    "machine_name": "机台名称",
    "completed_quantity": "已完成数量",
    "period_quantity": "期间数量",
    "product_code": "产品编码",
    "product_name": "产品名称",
    "workshop_code": "车间编码",
    "workshop_name": "车间名称",
    "buffer_code": "Buffer 编码",
    "max_capacity": "最大容量",
    "current_quantity": "当前库存",
    "process_code": "工序编码",
    "process_name": "工序名称",
    "sequence": "工序序号",
    "equipmentid": "AGV 机台编码",
    "linename": "AGV 当前产品名称",
}

_PIPELINE_STAGE_LABELS = {
    "main_buffer_aggregation": "主 Buffer 聚合",
    "pending_cutline_confirmation": "Pending 切线确认",
    "active_event_creation": "活跃事件创建",
    "active_event_merge": "活跃事件合并",
    "return_evaluation": "返工评估",
    "silk_screen_transition": "丝网切换",
    "stockout_candidate": "缺料候选机台",
    "overflow_candidate": "溢料候选机台",
    "stockout_selection": "缺料机台筛选",
    "overflow_selection": "溢料机台筛选",
    "stockout_plan": "缺料方案",
    "overflow_plan": "溢料方案",
    "pending_cutline_creation": "Pending 计划创建",
}


def input_error_code(dataset: str, reason_code: str) -> str:
    """返回指定输入数据域及原因的四位数字错误码。"""
    base = _INPUT_CODE_BASE_BY_DATASET.get(dataset, 2980)
    offsets = (
        _SPECIAL_INPUT_REASON_OFFSET
        if base >= 2900
        else _INPUT_REASON_OFFSET
    )
    return str(base + offsets.get(reason_code, 19 if base >= 2900 else 99))


def http_error_code(legacy_code: str) -> str:
    """返回 HTTP 整体错误的四位数字码。"""
    return _HTTP_ERROR_CODES.get(legacy_code, "1099")


def error_code_message(
    error_code: str,
    fallback: str | None = None,
    *,
    reason_code: str | None = None,
) -> str:
    """返回对外错误码对应的中文描述，输入校验明细按原始原因补全分段码。"""
    return _ERROR_MESSAGES.get(
        error_code,
        _INPUT_REASON_MESSAGES.get(reason_code or "", fallback or "未分类错误"),
    )


def http_error_message(error_code: str, scope: str) -> str:
    """返回包含算法范围的 HTTP 错误说明。"""
    return f"{scope}-请求：{error_code_message(error_code)}"


def input_error_message(
    *,
    scope: str,
    dataset: str,
    field: str | None,
    record_key: str | None,
    reason_code: str,
    error_code: str,
    fallback: str | None = None,
) -> str:
    """返回包含数据对象和字段定位的中文输入校验说明。"""
    dataset_label = _DATASET_LABELS.get(dataset, dataset)
    if record_key and record_key.startswith("index:"):
        record_label = f"{dataset_label}第{int(record_key[6:]) + 1}条"
    elif record_key:
        record_label = f"{dataset_label} {record_key}"
    elif dataset == "request":
        record_label = "请求"
    else:
        record_label = (
            dataset_label
            if dataset_label.endswith(("数据", "事件", "元数据"))
            else f"{dataset_label}数据集"
        )

    action = _INPUT_REASON_ACTIONS.get(
        reason_code,
        error_code_message(error_code, fallback, reason_code=reason_code),
    )
    if field:
        field_label = _FIELD_LABELS.get(field, field)
        return f"{scope}-{record_label}中‘{field_label}’字段{action}"
    return f"{scope}-{record_label}：{action}"


def pipeline_error_message(
    error_code: str,
    *,
    stage: str,
    warning_key: str | None,
    fallback: str | None = None,
) -> str:
    """返回包含切线/混料范围和告警标识的局部算法错误说明。"""
    target = warning_key or _PIPELINE_STAGE_LABELS.get(stage, stage)
    return f"切线/混料-{target}：{error_code_message(error_code, fallback)}"


def mixing_error_message(
    error_code: str,
    *,
    machine_code: str,
    fallback: str | None = None,
) -> str:
    """返回包含机台定位的混料追溯错误说明。"""
    return f"混料-{machine_code}：{error_code_message(error_code, fallback)}"


def aggregation_error_code(reason_code: str) -> str:
    """返回主 Buffer 聚合错误的四位数字码。"""
    return _AGGREGATION_ERROR_CODES.get(reason_code, "3099")


def pipeline_error_code(stage: str, reason_code: str) -> str:
    """返回算法管道局部错误的四位数字码。"""
    if stage == "main_buffer_aggregation":
        return aggregation_error_code(reason_code)
    return _PIPELINE_ERROR_CODES.get((stage, reason_code), "3099")


def mixing_trace_error_code(reason_code: str) -> str:
    """返回混料追溯错误的四位数字码。"""
    return _MIXING_TRACE_ERROR_CODES.get(reason_code, "3199")
