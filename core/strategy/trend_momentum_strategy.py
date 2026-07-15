def run_strategy(
    df,
    short_ema=20,
    long_ema=50,
    rsi_threshold=55,
    use_volume_filter=True
):
    """Registry-contract adapter.

    The original implementation re-ran add_all_indicators on an already
    pipeline-enriched frame (every other registered strategy relies on the
    caller's enrichment instead) and never populated Signal Confidence /
    Signal Reason / Strategy Name, so the scanner and voting engine could
    not display meaningful confidence or reasoning for this strategy. The
    trading calculation itself (Trend Filter & Momentum Filter & Volume
    Filter, using the same Short EMA / Long EMA / RSI comparisons every
    sibling strategy already uses) is unchanged.
    """
    df = df.copy()

    df["Trend Filter"] = df["Short EMA"] > df["Long EMA"]
    df["Momentum Filter"] = df["RSI"] > rsi_threshold

    if use_volume_filter:
        df["Volume Filter"] = df["Volume"] > df["Volume Average"]
    else:
        df["Volume Filter"] = True

    df["Signal"] = 0
    df["Signal Confidence"] = 0
    df["Signal Reason"] = "No trade"

    buy_condition = (
        df["Trend Filter"]
        & df["Momentum Filter"]
        & df["Volume Filter"]
    )

    df.loc[buy_condition, "Signal"] = 1
    df.loc[buy_condition, "Signal Confidence"] = 78
    df.loc[
        buy_condition,
        "Signal Reason"
    ] = "Trend and momentum aligned, volume confirmed"

    df["Strategy Name"] = "Trend Momentum"
    df["Position"] = df["Signal"].shift(1).fillna(0)

    return df
