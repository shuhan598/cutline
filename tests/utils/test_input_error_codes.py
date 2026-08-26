import pytest

from app.utils.input_error_codes import (
    aggregation_error_code,
    error_code_message,
    http_error_code,
    input_error_code,
    mixing_trace_error_code,
    pipeline_error_code,
)


@pytest.mark.parametrize(
    ("dataset", "reason", "expected"),
    (
        ("orders", "missing_reference", "2108"),
        ("machine_master", "missing_reference", "2208"),
        ("agv_relations", "load_error", "2321"),
        ("buffer_master", "invalid_value", "2406"),
        ("products", "missing", "2592"),
        ("process_routes", "unknown_process_name", "2614"),
        ("snapshot_meta", "missing", "2976"),
        ("request", "model_type", "2998"),
    ),
)
def test_input_error_code_uses_data_domain_ranges(
    dataset: str,
    reason: str,
    expected: str,
):
    assert input_error_code(dataset, reason) == expected


def test_error_code_mappers_keep_http_algorithm_and_mixing_ranges_distinct():
    assert http_error_code("BACKEND_DATA_INVALID") == "1010"
    assert aggregation_error_code("duplicate_buffer_id") == "3003"
    assert pipeline_error_code(
        "return_evaluation", "target_interval_not_found"
    ) == "3024"
    assert mixing_trace_error_code("process_duration_not_found") == "3111"


def test_error_code_messages_are_chinese_and_cover_segmented_input_codes():
    assert error_code_message("1012") == "请求格式、字段类型或载荷标准化错误"
    assert error_code_message("2995", reason_code="extra_forbidden") == "请求包含未声明字段"
    assert error_code_message("3003") == "同一物理 main 内存在重复的 Buffer 编码"
    assert error_code_message("3111") == "机台和源产品的工艺时长缺失"
