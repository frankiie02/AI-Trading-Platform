from dataclasses import dataclass

from core.runtime.context import RuntimeContext
from core.runtime.exceptions import LiveModeDisabledError, UnsupportedRuntimeModeError
from core.runtime.modes import RuntimeMode

_NOT_YET_IMPLEMENTED_MODES = (
    RuntimeMode.RESEARCH,
)


@dataclass
class RuntimeResult:
    """Outcome of routing a runtime mode, without performing any trading logic."""

    mode: RuntimeMode
    status: str
    message: str


class RuntimeRouter:
    """Dispatches a resolved RuntimeMode to a controlled result.

    This router intentionally contains no trading, broker, execution, or
    market-data logic. It only recognises modes and reports their status.
    """

    def route(self, context: RuntimeContext) -> RuntimeResult:
        mode = context.mode

        if mode is RuntimeMode.LIVE:
            raise LiveModeDisabledError(
                "Live mode is disabled. Live trading is not enabled in this build."
            )

        if mode is RuntimeMode.OPTIMISATION:
            raise UnsupportedRuntimeModeError(
                "Optimisation runtime is not implemented yet."
            )

        if mode is RuntimeMode.SCANNER:
            # Imported lazily so RuntimeRouter's own module-level import
            # surface stays free of scanner/market-data/database
            # dependencies, matching this class's "no trading logic" intent.
            from core.runtime.scanner_runtime import run_scanner

            return run_scanner(context)

        if mode is RuntimeMode.BACKTEST:
            # Imported lazily for the same reason as the scanner runtime
            # above - keeps RuntimeRouter's own imports free of market-data/
            # pipeline dependencies.
            from core.runtime.backtest_runtime import run_backtest

            return run_backtest(context)

        if mode is RuntimeMode.PAPER:
            # Imported lazily for the same reason as the scanner/backtest
            # runtimes above - keeps RuntimeRouter's own imports free of
            # execution/database dependencies.
            from core.runtime.paper_runtime import run_paper_trading

            return run_paper_trading(context)

        if mode in _NOT_YET_IMPLEMENTED_MODES:
            context.logger.info(
                "Runtime mode '%s' recognised; standalone runtime service is "
                "not yet implemented.",
                mode.value,
            )

            return RuntimeResult(
                mode=mode,
                status="not_implemented",
                message=(
                    f"Runtime mode '{mode.value}' is recognised. Its standalone "
                    "service is not yet implemented in this build. Use "
                    "`streamlit run dashboard.py` for the current interactive "
                    "workflow."
                ),
            )

        raise UnsupportedRuntimeModeError(
            f"No handler registered for runtime mode '{mode.value}'."
        )
