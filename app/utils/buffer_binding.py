"""Buffer 实时绑定字段的临时兼容判断。"""

from __future__ import annotations

import re


_BOUND_SOURCE_PRODUCT_PATTERN = re.compile(
    r"^[0-9]+[A-Za-z]+(?=[0-9A-Za-z\u4e00-\u9fff]*[\u4e00-\u9fff])"
    r"[0-9A-Za-z\u4e00-\u9fff]+$"
)


def is_multi_value_bound_source_name(value: object) -> bool:
    """判断绑定来源是否包含两个及以上逗号分隔的非空值。"""
    if not isinstance(value, str):
        return False
    return sum(bool(part.strip()) for part in value.split(",")) >= 2


def is_valid_bound_source_product_name(value: object) -> bool:
    """判断首个连字符前的产品名是否符合数字+字母+中文格式。"""
    if not isinstance(value, str):
        return False
    product_name = value.strip().split("-", 1)[0].strip()
    return bool(_BOUND_SOURCE_PRODUCT_PATTERN.fullmatch(product_name))


def should_ignore_bound_source_name(value: object) -> bool:
    """判断 Buffer 绑定是否应被忽略。"""
    return (
        is_multi_value_bound_source_name(value)
        or not is_valid_bound_source_product_name(value)
    )


def normalize_bound_source_product_name(
    value: str,
) -> str:
    """取第一个英文连字符前的内容作为算法内部标准产品名。"""
    return value.strip().split("-", 1)[0].strip()
