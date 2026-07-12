import pytest

from core.runtime.exceptions import InvalidRuntimeModeError
from core.runtime.modes import RuntimeMode


EXPECTED_MODES = {
    "research",
    "scanner",
    "backtest",
    "optimisation",
    "paper",
    "live",
}


def test_enum_contains_exactly_the_expected_modes():
    actual_values = {mode.value for mode in RuntimeMode}
    assert actual_values == EXPECTED_MODES


@pytest.mark.parametrize("value", sorted(EXPECTED_MODES))
def test_from_string_accepts_every_valid_mode(value):
    assert RuntimeMode.from_string(value) is RuntimeMode(value)


@pytest.mark.parametrize(
    "raw_value, expected_mode",
    [
        ("research", RuntimeMode.RESEARCH),
        ("RESEARCH", RuntimeMode.RESEARCH),
        ("  scanner  ", RuntimeMode.SCANNER),
        ("Backtest", RuntimeMode.BACKTEST),
    ],
)
def test_from_string_normalises_case_and_whitespace(raw_value, expected_mode):
    assert RuntimeMode.from_string(raw_value) is expected_mode


def test_from_string_rejects_unknown_value():
    with pytest.raises(InvalidRuntimeModeError):
        RuntimeMode.from_string("not_a_real_mode")


def test_from_string_rejects_none():
    with pytest.raises(InvalidRuntimeModeError):
        RuntimeMode.from_string(None)
