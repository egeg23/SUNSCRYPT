import pytest

from app import safety


def test_leverage_cap_is_2x_default_1x():
    assert safety.MAX_LEVERAGE == 2
    assert safety.DEFAULT_LEVERAGE == 1


@pytest.mark.parametrize("value", [0.5, 1, 2])
def test_leverage_within_cap(value):
    assert safety.check_leverage(value) == value


@pytest.mark.parametrize("value", [0, -1, 2.01, 3, 100])
def test_leverage_over_cap_rejected(value):
    with pytest.raises(ValueError):
        safety.check_leverage(value)


def test_demo_is_default():
    assert safety.DEFAULT_MODE == safety.Mode.DEMO


@pytest.mark.parametrize(
    ("enabled", "stop", "allowed"),
    [(False, False, False), (False, True, False), (True, True, False), (True, False, True)],
)
def test_real_mode_needs_owner_flag_and_no_stop(enabled, stop, allowed):
    assert safety.real_mode_allowed(enabled, stop) is allowed
