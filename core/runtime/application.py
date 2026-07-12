import logging
from typing import Any, Dict, Optional

from core.runtime.context import RuntimeContext
from core.runtime.modes import RuntimeMode
from core.runtime.router import RuntimeResult, RuntimeRouter

DEFAULT_RUNTIME_MODE = "research"


class TradingApplication:
    """Minimal application bootstrap.

    Lifecycle: load configuration -> resolve runtime mode -> obtain logger ->
    create RuntimeContext -> route runtime mode -> return result.

    This class does not initialise a database, broker, market-data client,
    or any service container. It only bootstraps and routes.
    """

    def __init__(
        self,
        settings: Optional[Dict[str, Any]] = None,
        router: Optional[RuntimeRouter] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._settings = settings
        self._router = router or RuntimeRouter()
        self._logger = logger or logging.getLogger("trading_platform.runtime")

    def run(self) -> RuntimeResult:
        settings = self._load_settings()

        mode = RuntimeMode.from_string(
            settings.get("RUNTIME_MODE", DEFAULT_RUNTIME_MODE)
        )

        context = RuntimeContext(
            settings=settings,
            mode=mode,
            logger=self._logger,
        )

        self._logger.info("Starting trading application in '%s' mode.", mode.value)

        result = self._router.route(context)

        self._logger.info("Trading application finished with status '%s'.", result.status)

        return result

    def _load_settings(self) -> Dict[str, Any]:
        if self._settings is not None:
            return self._settings

        from config.config_manager import load_settings

        return load_settings()
