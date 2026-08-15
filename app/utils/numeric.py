"""提供全项目统一的安全数值转换。"""

import math


def safe_float(value, default=0.0):
    """转 float；None/非数字/非有限值一律返回 default。"""
    try:
        if value is None:
            return default

        converted = float(value)
        if not math.isfinite(converted):
            return default

        return converted
    except (TypeError, ValueError, OverflowError):
        return default
