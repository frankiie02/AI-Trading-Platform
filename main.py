import pandas as pd

from data.market_data import get_price_history
from strategies.trend_join_long import generate_trend_signal

symbols = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMD"]

results = []

print("\nAI Trading Platform")
print("=" * 60)

for symbol in symbols:
    try:
        data = get_price_history(symbol)
        result = generate_trend_signal(data, symbol)

        passed = sum(result["rules"].values())

        results.append({
    "Symbol": result["symbol"],
    "Strategy": result["strategy"],
    "Price": result["latest_close"],
    "Signal": result["signal"],
    "Entry": result["entry"],
    "Stop Loss": result["stop_loss"],
    "Take Profit": result["take_profit"],
    "Risk/Reward": "2:1",
    "Score": f"{passed}/3"
})

    except Exception as e:
        results.append({
            "Symbol": symbol,
            "Strategy": "Trend Join Long",
            "Price": None,
            "Signal": f"ERROR: {e}",
            "Score": "0/3"
        })

df = pd.DataFrame(results)

print(df)

df.to_csv("signals.csv", index=False)

print("\nSignals saved to signals.csv")