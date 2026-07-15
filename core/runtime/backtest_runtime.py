from typing import Any, Dict, Optional

from config.defaults import DEFAULT_SETTINGS
from core.pipeline.models import ScanStrategyMode
from core.runtime.context import RuntimeContext
from core.runtime.modes import RuntimeMode
from core.runtime.router import RuntimeResult
from core.services.backtest_service import BacktestRequest, BacktestService


def _setting(settings: Dict[str, Any], key: str):
    return settings.get(key, DEFAULT_SETTINGS[key])


def build_backtest_request(settings: Dict[str, Any]) -> BacktestRequest:
    """Builds a BacktestRequest from the existing settings system, using the
    BACKTEST_* defaults (config/defaults.py) whenever a key is absent."""
    return BacktestRequest(
        symbol=_setting(settings, "BACKTEST_SYMBOL"),
        strategy_mode=ScanStrategyMode(_setting(settings, "BACKTEST_STRATEGY_MODE")),
        strategy_name=_setting(settings, "BACKTEST_STRATEGY"),
        period=_setting(settings, "BACKTEST_PERIOD"),
        interval=_setting(settings, "BACKTEST_INTERVAL"),
        initial_capital=_setting(settings, "BACKTEST_INITIAL_CAPITAL"),
        short_ema=_setting(settings, "BACKTEST_SHORT_EMA"),
        long_ema=_setting(settings, "BACKTEST_LONG_EMA"),
        rsi_threshold=_setting(settings, "BACKTEST_RSI_THRESHOLD"),
        use_volume_filter=_setting(settings, "BACKTEST_USE_VOLUME_FILTER"),
        use_regime_filter=_setting(settings, "BACKTEST_USE_REGIME_FILTER"),
        risk_percent=_setting(settings, "BACKTEST_RISK_PERCENT"),
        atr_multiplier=_setting(settings, "BACKTEST_ATR_MULTIPLIER"),
        reward_risk_ratio=_setting(settings, "BACKTEST_REWARD_RISK_RATIO"),
        minimum_alpha_score=_setting(settings, "BACKTEST_MINIMUM_ALPHA_SCORE"),
        commission=_setting(settings, "BACKTEST_COMMISSION"),
        slippage=_setting(settings, "BACKTEST_SLIPPAGE"),
    )


def run_backtest(
    context: RuntimeContext,
    service: Optional[BacktestService] = None
) -> RuntimeResult:
    """Standalone backtest runtime coordinator.

    Builds a BacktestRequest from the existing settings system and runs it
    through BacktestService, exactly as the Streamlit page does. Contains no
    Streamlit, broker, or live-execution code: BacktestService's default
    collaborators only ever perform paper/local (Yahoo market data) and
    pure-computation (TradingPipeline) operations. No persistence is
    performed - BacktestService does not write to the database.
    """
    request = build_backtest_request(context.settings)
    service = service or BacktestService(logger=context.logger)

    result = service.run(request)

    metrics = result.metrics
    message = (
        f"Backtest completed for {request.symbol}: "
        f"{metrics.get('Total Trades', 0)} trade(s), "
        f"{metrics.get('Total Return %', 0):.2f}% total return, "
        f"{metrics.get('Max Drawdown %', 0):.2f}% max drawdown, "
        f"final equity ${metrics.get('Final Equity', request.initial_capital):,.2f}."
    )

    context.logger.info(message)

    return RuntimeResult(
        mode=RuntimeMode.BACKTEST,
        status="completed",
        message=message,
    )
