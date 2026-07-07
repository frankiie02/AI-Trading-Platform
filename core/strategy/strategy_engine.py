from core.strategy.registry import (
    get_available_strategies,
    get_strategy
)


AVAILABLE_STRATEGIES = get_available_strategies()


def generate_strategy_signals(
    df,
    strategy_name="EMA Trend",
    short_ema=20,
    long_ema=50,
    rsi_threshold=55,
    use_volume_filter=True
):
    strategy_function = get_strategy(strategy_name)

    if strategy_function is None:
        strategy_function = get_strategy("EMA Trend")

    return strategy_function(
        df=df,
        short_ema=short_ema,
        long_ema=long_ema,
        rsi_threshold=rsi_threshold,
        use_volume_filter=use_volume_filter
    )