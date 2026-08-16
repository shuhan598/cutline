"""Buffer 实时绑定字段的统一解析和兼容判断工具。

后端的 ``buffer_realtime.bound_source_name`` 可能同时包含产品名、工序
后缀和自动绑定标识，例如 ``210R公版-退火下-AUTO``。本模块只负责判断
这类绑定是否可以安全地进入算法，并把第一个 ASCII 连字符前的内容提取
为算法内部使用的产品名；产品是否真实存在于订单目录，则由调用方继续
完成映射校验。
"""

from __future__ import annotations

import re


_BOUND_SOURCE_PRODUCT_PATTERN = re.compile(
    # 产品名前缀必须满足：数字开头、随后至少一个 ASCII 字母、至少一个
    # 中文字符，并且除此之外不能再出现空格、标点或其他 Unicode 字符。
    # lookahead 用来保证中文字符存在，后面的字符集负责限制允许的完整范围。
    r"^[0-9]+[A-Za-z]+(?=[0-9A-Za-z\u4e00-\u9fff]*[\u4e00-\u9fff])"
    r"[0-9A-Za-z\u4e00-\u9fff]+$"
)


def is_multi_value_bound_source_name(value: object) -> bool:
    """判断绑定来源是否包含两个及以上逗号分隔的非空值。

    多值绑定无法唯一对应一个订单，因此整条 Buffer 实时记录必须被忽略。
    空字符串或只有一个值的字符串不属于“多值”本身，但仍可能因为产品名
    格式不合法而被 ``should_ignore_bound_source_name`` 过滤。
    """
    if not isinstance(value, str):
        return False
    return sum(bool(part.strip()) for part in value.split(",")) >= 2


def is_valid_bound_source_product_name(value: object) -> bool:
    """判断首个 ASCII 连字符前的产品名前缀是否符合约定格式。

    允许的前缀格式是 ``数字 + 英文字母 + 中文``，并且完整前缀只能由
    数字、ASCII 英文字母和中文组成。例如 ``210R公版``、``210N艺馨``
    合法；``天合返洗验证``（缺少数字和英文字母）以及 ``210R``（缺少
    中文）不合法。连字符后的工序和 ``AUTO`` 后缀不参与格式判断。
    """
    if not isinstance(value, str):
        return False
    product_name = value.strip().split("-", 1)[0].strip()
    return bool(_BOUND_SOURCE_PRODUCT_PATTERN.fullmatch(product_name))


def should_ignore_bound_source_name(value: object) -> bool:
    """判断 Buffer 绑定是否应在所有后续算法环节中整体忽略。

    过滤顺序不影响结果：逗号多值绑定直接忽略；单值绑定还必须通过产品名
    格式校验。该函数只判断“能否进入算法”，不会判断格式正确的产品是否
    存在于订单目录；后者仍由订单映射逻辑产生 ``order_mapping_not_found``。
    """
    return (
        is_multi_value_bound_source_name(value)
        or not is_valid_bound_source_product_name(value)
    )


def normalize_bound_source_product_name(
    value: str,
) -> str:
    """取第一个 ASCII ``-`` 前的内容作为算法内部标准产品名。

    调用方应先使用 ``should_ignore_bound_source_name`` 过滤无效值，再调用
    本函数。这里不做格式校验，职责仅限于去除工序/自动绑定后缀并清理首尾
    空白，例如 ``210R公版-退火下-AUTO`` 会得到 ``210R公版``。
    """
    return value.strip().split("-", 1)[0].strip()
