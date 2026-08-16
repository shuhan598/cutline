import pytest

from app.utils import buffer_binding


@pytest.mark.parametrize(
    ("value", "ignored"),
    (
        ("210R公版-退火下-AUTO", False),
        ("210N艺馨-氧化下-AUTO", False),
        ("210R公版2-背膜下-AUTO", False),
        ("天合返洗验证-退火下-AUTO", True),
        ("210公版-退火下-AUTO", True),
        ("210R-退火下-AUTO", True),
        ("R210公版-退火下-AUTO", True),
        ("产品一", True),
        ("Product A", True),
        ("Product A,Product B", True),
    ),
)
def test_should_ignore_bound_source_name(value, ignored):
    assert buffer_binding.should_ignore_bound_source_name(value) is ignored
