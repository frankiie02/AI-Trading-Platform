from core.strategy import breakout
from core.strategy import ema_trend
from core.strategy import macd_momentum
from core.strategy import rsi_pullback


STRATEGY_REGISTRY = {
    "EMA Trend": ema_trend.run_strategy,
    "RSI Pullback": rsi_pullback.run_strategy,
    "Breakout": breakout.run_strategy,
    "MACD Momentum": macd_momentum.run_strategy,
}


def get_available_strategies():
    return list(STRATEGY_REGISTRY.keys())


def get_strategy(strategy_name):
    return STRATEGY_REGISTRY.get(strategy_name)