import pandas as pd

from data.market_data import get_price_history
from analytics.backtester import run_backtest
from analytics.metrics import calculate_metrics

symbols = [
    "SPY",
    "QQQ",
    "AAPL",
    "MSFT",
    "NVDA",
    "TSLA",
    "AMD",
    "META",
    "AMZN",
    "GOOGL"
]

all_summaries = []

print("\nMulti-Symbol Backtest")
print("=" * 60)

for symbol in symbols:
    try:
        print(f"\nRunning backtest for {symbol}...")

        data = get_price_history(symbol, period="5y")
        trades = run_backtest(data, symbol)
        metrics = calculate_metrics(trades)

        if metrics:
            metrics["Symbol"] = symbol
            all_summaries.append(metrics)

            trades.to_csv(f"analytics/trades_{symbol}.csv", index=False)

    except Exception as e:
        print(f"{symbol}: ERROR - {e}")

summary = pd.DataFrame(all_summaries)

cols = ["Symbol"] + [col for col in summary.columns if col != "Symbol"]
summary = summary[cols]

print("\nCombined Summary")
print("=" * 60)
print(summary)

summary.to_csv("analytics/multi_symbol_summary.csv", index=False)

print("\nSaved to analytics/multi_symbol_summary.csv")

summary = summary.sort_values(
    by=["Net Profit %", "Profit Factor", "Win Rate %"],
    ascending=False
)