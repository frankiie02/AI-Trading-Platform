import pandas as pd


def calculate_atr(data, period=14):
    df = data.copy()

    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()

    tr = pd.concat(
        [high_low, high_close, low_close],
        axis=1
    ).max(axis=1)

    atr = tr.rolling(period).mean()

    return atr