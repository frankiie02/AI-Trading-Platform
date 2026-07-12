class RuntimeConfigurationError(Exception):
    """Base class for errors raised while bootstrapping the trading application."""


class InvalidRuntimeModeError(RuntimeConfigurationError):
    """Raised when a configured runtime-mode value does not match any RuntimeMode."""


class UnsupportedRuntimeModeError(RuntimeConfigurationError):
    """Raised when a recognised runtime mode has no runnable handler yet."""


class LiveModeDisabledError(RuntimeConfigurationError):
    """Raised whenever live mode is selected. Live trading is hard-disabled."""
