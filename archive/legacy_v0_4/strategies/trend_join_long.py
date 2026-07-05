from indicators.atr import calculate_atr


def generate_trend_signal(data, symbol: str):
    data = data.copy()

    data["EMA_20"] = data["Close"].ewm(span=20, adjust=False).mean()
    data["EMA_50"] = data["Close"].ewm(span=50, adjust=False).mean()
    data["Volume_Avg_20"] = data["Volume"].rolling(20).mean()
    data["ATR"] = calculate_atr(data)

    latest = data.iloc[-1]

    rules = {
        "price_above_ema20": latest["Close"] > latest["EMA_20"],
        "ema20_above_ema50": latest["EMA_20"] > latest["EMA_50"],
        "volume_above_average": latest["Volume"] > latest["Volume_Avg_20"],
    }

    signal = all(rules.values())

    entry = float(latest["Close"])
    atr = float(latest["ATR"])

    stop_loss = round(entry - (2 * atr), 2)
    take_profit = round(entry + (4 * atr), 2)

    return {
        "symbol": symbol,
        "strategy": "Trend Join Long",
        "signal": "BUY" if signal else "NO_TRADE",
        "latest_close": round(entry, 2),
        "entry": round(entry, 2),
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "rules": rules,
    }