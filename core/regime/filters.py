from core.regime.market_state import MarketState


ALLOWED_STRATEGIES = {
    MarketState.BULL: {
        "EMA Trend",
        "MACD Momentum",
        "Breakout",
        "RSI Pullback"
    },
    MarketState.BEAR: set(),
    MarketState.SIDEWAYS: {
        "RSI Pullback"
    },
}


def strategy_allowed(
    strategy_name: str,
    regime: MarketState,
):
    allowed = ALLOWED_STRATEGIES.get(regime, set())

    return strategy_name in allowed