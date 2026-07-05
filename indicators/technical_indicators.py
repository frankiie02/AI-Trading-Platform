import pandas as pd


def add_ema(df, column="Close", short_window=20, long_window=50):
    df = df.copy()

    df["Short EMA"] = df[column].ewm(
        span=short_window,
        adjust=False
    ).mean()

    df["Long EMA"] = df[column].ewm(
        span=long_window,
        adjust=False
    ).mean()

    return df


def add_rsi(df, column="Close", window=14):
    df = df.copy()

    delta = df[column].diff()

    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)

    average_gain = gain.rolling(window=window).mean()
    average_loss = loss.rolling(window=window).mean()

    rs = average_gain / average_loss

    df["RSI"] = 100 - (100 / (1 + rs))

    return df


def add_atr(df, window=14):
    df = df.copy()

    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()

    true_range = pd.concat(
        [high_low, high_close, low_close],
        axis=1
    ).max(axis=1)

    df["ATR"] = true_range.rolling(window=window).mean()

    return df


def add_volume_average(df, window=20):
    df = df.copy()

    df["Volume Average"] = df["Volume"].rolling(
        window=window
    ).mean()

    return df


def add_all_indicators(
    df,
    short_ema=20,
    long_ema=50,
    rsi_window=14,
    atr_window=14,
    volume_window=20
):
    df = df.copy()

    df = add_ema(
        df,
        short_window=short_ema,
        long_window=long_ema
    )

    df = add_rsi(
        df,
        window=rsi_window
    )

    df = add_atr(
        df,
        window=atr_window
    )

    df = add_volume_average(
        df,
        window=volume_window
    )

    return df