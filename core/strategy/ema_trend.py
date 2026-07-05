from core.indicators.technical_indicators import add_all_indicators


def run_strategy(
    df,
    short_ema=20,
    long_ema=50,
    rsi_threshold=55,
    use_volume_filter=True
):
    df = df.copy()

    df = add_all_indicators(
        df,
        short_ema=short_ema,
        long_ema=long_ema
    )

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
    df.loc[buy_condition, "Signal Confidence"] = 80
    df.loc[
        buy_condition,
        "Signal Reason"
    ] = "EMA trend bullish, RSI momentum strong, volume confirmed"

    df["Strategy Name"] = "EMA Trend"
    df["Position"] = df["Signal"].shift(1).fillna(0)

    return df