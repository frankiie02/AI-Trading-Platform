import yfinance as yf


def get_price_history(symbol: str, period: str = "6mo", interval: str = "1d"):
    data = yf.download(
        symbol,
        period=period,
        interval=interval,
        progress=False,
        auto_adjust=False
    )

    if data.empty:
        raise ValueError(f"No market data returned for {symbol}")

    # Fix yfinance MultiIndex columns issue
    if isinstance(data.columns, tuple) or hasattr(data.columns, "levels"):
        data.columns = [
            col[0] if isinstance(col, tuple) else col
            for col in data.columns
        ]

    data = data.reset_index()

    return data