from core.strategy import breakout
from core.strategy import ema_trend
from core.strategy import rsi_pullback


AVAILABLE_STRATEGIES = [
    "EMA Trend",
    "RSI Pullback",
    "Breakout"
]


def generate_strategy_signals(
    df,
    strategy_name="EMA Trend",
    short_ema=20,
    long_ema=50,
    rsi_threshold=55,
    use_volume_filter=True
):
    if strategy_name == "EMA Trend":
        return ema_trend.run_strategy(
            df=df,
            short_ema=short_ema,
            long_ema=long_ema,
            rsi_threshold=rsi_threshold,
            use_volume_filter=use_volume_filter
        )

    if strategy_name == "RSI Pullback":
        return rsi_pullback.run_strategy(
            df=df,
            short_ema=short_ema,
            long_ema=long_ema,
            rsi_threshold=rsi_threshold,
            use_volume_filter=use_volume_filter
        )

    if strategy_name == "Breakout":
        return breakout.run_strategy(
            df=df,
            short_ema=short_ema,
            long_ema=long_ema,
            rsi_threshold=rsi_threshold,
            use_volume_filter=use_volume_filter
        )

    return ema_trend.run_strategy(
        df=df,
        short_ema=short_ema,
        long_ema=long_ema,
        rsi_threshold=rsi_threshold,
        use_volume_filter=use_volume_filter
    )