from core.indicators.technical_indicators import add_all_indicators


def generate_signals(
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

    df.loc[
        (
            df["Trend Filter"]
            & df["Momentum Filter"]
            & df["Volume Filter"]
        ),
        "Signal"
    ] = 1

    df["Position"] = df["Signal"].shift(1).fillna(0)

    return df