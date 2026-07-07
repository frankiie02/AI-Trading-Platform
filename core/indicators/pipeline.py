from core.indicators.technical_indicators import add_all_indicators


def build_indicator_pipeline(
    df,
    short_ema=20,
    long_ema=50,
    rsi_window=14,
    atr_window=14,
    volume_window=20
):
    """
    Build the full indicator dataset once.

    Strategies should consume this enriched DataFrame instead of
    recalculating indicators independently.
    """

    if df.empty:
        return df

    enriched_df = add_all_indicators(
        df=df,
        short_ema=short_ema,
        long_ema=long_ema,
        rsi_window=rsi_window,
        atr_window=atr_window,
        volume_window=volume_window
    )

    return enriched_df