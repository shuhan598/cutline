"""Buffer 实时绑定字段的临时兼容判断。"""

from __future__ import annotations


def is_multi_value_bound_source_name(value: object) -> bool:
    """判断绑定来源是否包含两个及以上逗号分隔的非空值。"""
    if not isinstance(value, str):
        return False
    return sum(bool(part.strip()) for part in value.split(",")) >= 2


def normalize_bound_source_product_name(
    value: str,
) -> str:
    """取第一个英文连字符前的内容作为算法内部标准产品名。"""
    return value.strip().split("-", 1)[0].strip()
