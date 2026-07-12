from enum import Enum

from core.runtime.exceptions import InvalidRuntimeModeError


class RuntimeMode(str, Enum):
    RESEARCH = "research"
    SCANNER = "scanner"
    BACKTEST = "backtest"
    OPTIMISATION = "optimisation"
    PAPER = "paper"
    LIVE = "live"

    @classmethod
    def from_string(cls, value):
        if value is None:
            raise InvalidRuntimeModeError("Runtime mode is not configured.")

        normalised = str(value).strip().lower()

        try:
            return cls(normalised)
        except ValueError:
            valid_values = ", ".join(mode.value for mode in cls)
            raise InvalidRuntimeModeError(
                f"Unknown runtime mode: {value!r}. Valid modes are: {valid_values}."
            )
