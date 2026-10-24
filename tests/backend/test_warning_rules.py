from app.backend.rules import classify_warning, projected_change_pct


def test_warning_boundaries() -> None:
    assert classify_warning(4.99) == "STABLE"
    assert classify_warning(5.00) == "WATCH"
    assert classify_warning(9.99) == "WATCH"
    assert classify_warning(10.00) == "ELEVATED"
    assert classify_warning(14.99) == "ELEVATED"
    assert classify_warning(15.00) == "HIGH"
    assert classify_warning(-3.0) == "STABLE"


def test_change_requires_positive_current_price() -> None:
    assert projected_change_pct(100, 105) == 5.0
    import pytest

    with pytest.raises(ValueError):
        projected_change_pct(0, 100)
    with pytest.raises(ValueError):
        projected_change_pct(float("nan"), 100)
