import pandas as pd

from core.regime.market_state import MarketState


def detect_market_regime(df: pd.DataFrame) -> MarketState:
    """
    Simple market regime detector.

    Uses:
    - EMA trend
    - RSI
    """

    if df.empty:
        return MarketState.UNKNOWN

    latest = df.iloc[-1]

    short_ema = latest["Short EMA"]
    long_ema = latest["Long EMA"]
    rsi = latest["RSI"]

    if short_ema > long_ema and rsi > 55:
        return MarketState.BULL

    if short_ema < long_ema and rsi < 45:
        return MarketState.BEAR

    return MarketState.SIDEWAYS