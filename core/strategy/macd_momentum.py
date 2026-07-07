def run_strategy(
    df,
    short_ema=20,
    long_ema=50,
    rsi_threshold=55,
    use_volume_filter=True
):
    df = df.copy()

    df["Trend Filter"] = df["Short EMA"] > df["Long EMA"]

    df["Momentum Filter"] = (
        (df["MACD"] > df["MACD Signal"])
        & (df["MACD Histogram"] > 0)
        & (df["MACD Histogram"] > df["MACD Histogram"].shift(1))
    )

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
    df.loc[buy_condition, "Signal Confidence"] = 82
    df.loc[
        buy_condition,
        "Signal Reason"
    ] = "MACD bullish momentum, histogram expanding, trend and volume confirmed"

    df["Strategy Name"] = "MACD Momentum"
    df["Position"] = df["Signal"].shift(1).fillna(0)

    return df