def run_strategy(
    df,
    short_ema=20,
    long_ema=50,
    rsi_threshold=55,
    use_volume_filter=True
):
    df = df.copy()

    df["Previous High"] = df["High"].rolling(
        window=20
    ).max().shift(1)

    df["Trend Filter"] = df["Short EMA"] > df["Long EMA"]
    df["Momentum Filter"] = df["Close"] > df["Previous High"]

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
    df.loc[buy_condition, "Signal Confidence"] = 85
    df.loc[
        buy_condition,
        "Signal Reason"
    ] = "Price broke above 20-day high, trend bullish, volume confirmed"

    df["Strategy Name"] = "Breakout"
    df["Position"] = df["Signal"].shift(1).fillna(0)

    return df