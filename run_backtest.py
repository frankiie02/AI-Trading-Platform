import pandas as pd

from data.market_data import get_price_history
from analytics.backtester import run_backtest
from analytics.metrics import calculate_metrics
from analytics.reports import create_equity_curve, create_drawdown_chart

symbol = "AMD"

data = get_price_history(symbol, period="5y")
trades = run_backtest(data, symbol)
metrics = calculate_metrics(trades)

print("\nBacktest Trades")
print("=" * 60)
print(trades)

print("\nBacktest Summary")
print("=" * 60)
print(pd.DataFrame([metrics]))

trades.to_csv("analytics/trades.csv", index=False)
pd.DataFrame([metrics]).to_csv("analytics/summary.csv", index=False)

create_equity_curve(trades)
create_drawdown_chart(trades)

print("\nTrades saved to analytics/trades.csv")
print("Summary saved to analytics/summary.csv")
print("Equity curve saved to analytics/equity_curve.png")
print("Drawdown chart saved to analytics/drawdown.png")