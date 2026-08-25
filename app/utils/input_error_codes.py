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
