from typing import Any, Dict, Optional

from config.defaults import DEFAULT_SETTINGS
from core.runtime.context import RuntimeContext
from core.runtime.modes import RuntimeMode
from core.runtime.router import RuntimeResult
from core.services.scanner_service import ScanRequest, ScannerService, ScanStrategyMode


def _setting(settings: Dict[str, Any], key: str):
    return settings.get(key, DEFAULT_SETTINGS[key])


def build_scan_request(settings: Dict[str, Any]) -> ScanRequest:
    """Builds a ScanRequest from the existing settings system, using the
    SCANNER_* defaults (config/defaults.py) whenever a key is absent."""
    return ScanRequest(
        symbols=_setting(settings, "SCANNER_SYMBOLS"),
        strategy_mode=ScanStrategyMode(_setting(settings, "SCANNER_STRATEGY_MODE")),
        strategy_name=_setting(settings, "SCANNER_STRATEGY_NAME"),
        period=_setting(settings, "SCANNER_PERIOD"),
        interval=_setting(settings, "SCANNER_INTERVAL"),
        short_ema=_setting(settings, "SCANNER_SHORT_EMA"),
        long_ema=_setting(settings, "SCANNER_LONG_EMA"),
        rsi_threshold=_setting(settings, "SCANNER_RSI_THRESHOLD"),
        use_volume_filter=_setting(settings, "SCANNER_USE_VOLUME_FILTER"),
        use_regime_filter=_setting(settings, "SCANNER_USE_REGIME_FILTER"),
        risk_percent=_setting(settings, "SCANNER_RISK_PERCENT"),
        atr_multiplier=_setting(settings, "SCANNER_ATR_MULTIPLIER"),
        reward_risk_ratio=_setting(settings, "SCANNER_REWARD_RISK_RATIO"),
        minimum_alpha_score=_setting(settings, "SCANNER_MINIMUM_ALPHA_SCORE"),
        queue_trades=_setting(settings, "SCANNER_QUEUE_TRADES"),
    )


def _log_progress(context: RuntimeContext):
    def _callback(completed: int, total: int, symbol: str) -> None:
        context.logger.info("Scanned %s (%s/%s)", symbol, completed, total)

    return _callback


def run_scanner(
    context: RuntimeContext,
    service: Optional[ScannerService] = None
) -> RuntimeResult:
    """Standalone scanner runtime coordinator.

    Builds a ScanRequest from the existing settings system and runs it
    through ScannerService, exactly as the Streamlit page does. Contains no
    Streamlit, broker, or live-execution code: ScannerService's default
    collaborators only ever perform paper/local (Yahoo market data + SQLite)
    operations. Persistence/trade-queue failures (ScannerServiceError and
    subclasses) are intentionally not swallowed here - they propagate to the
    caller as controlled, typed runtime errors.
    """
    request = build_scan_request(context.settings)
    service = service or ScannerService(logger=context.logger)

    result = service.scan(request, progress_callback=_log_progress(context))

    stats = result.statistics
    message = (
        f"Scanner completed: {stats.successful_symbols}/{stats.symbols_requested} "
        f"symbol(s) scanned successfully ({stats.failed_symbols} failed), "
        f"{stats.buy_signals} BUY signal(s), {result.queued_count} trade(s) queued."
    )

    context.logger.info(message)

    return RuntimeResult(
        mode=RuntimeMode.SCANNER,
        status="completed",
        message=message,
    )
