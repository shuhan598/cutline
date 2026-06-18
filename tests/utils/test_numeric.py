from app.utils.numeric import safe_float


def test_safe_float_converts_numeric_string():
    assert safe_float("12.5") == 12.5


def test_safe_float_returns_default_for_none():
    assert safe_float(None) == 0.0
    assert safe_float(None, default=None) is None


def test_safe_float_returns_default_for_invalid():
    assert safe_float("abc") == 0.0


def test_safe_float_rejects_non_finite():
    assert safe_float(float("inf")) == 0.0
    assert safe_float(float("nan")) == 0.0
