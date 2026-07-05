import pandas as pd
import yfinance as yf


def download_price_data(
    symbol,
    period="1y",
    interval="1d",
    auto_adjust=True
):
    data = yf.download(
        symbol,
        period=period,
        interval=interval,
        auto_adjust=auto_adjust,
        progress=False
    )

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    if data.empty:
        return pd.DataFrame()

    data = data.copy()
    data.dropna(inplace=True)

    return data


def get_price_history(
    symbol: str,
    period: str = "6mo",
    interval: str = "1d"
):
    data = download_price_data(
        symbol=symbol,
        period=period,
        interval=interval,
        auto_adjust=False
    )

    if data.empty:
        raise ValueError(f"No market data returned for {symbol}")

    return data.reset_index()