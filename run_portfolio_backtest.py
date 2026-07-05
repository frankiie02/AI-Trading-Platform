import pandas as pd

from data.market_data import get_price_history
from analytics.backtester import run_backtest
from risk.portfolio import Portfolio
from risk.position_sizer import calculate_position_size

symbols = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "AMZN", "GOOGL"]

portfolio = Portfolio(starting_balance=100000, max_open_positions=5)

candidate_trades = []

print("\nCollecting trades...")
print("=" * 60)

for symbol in symbols:
    print(f"Scanning {symbol}...")

    data = get_price_history(symbol, period="5y")
    trades = run_backtest(data, symbol)

    if not trades.empty:
        candidate_trades.append(trades)

all_candidates = pd.concat(candidate_trades, ignore_index=True)

all_candidates["Entry Date"] = pd.to_datetime(all_candidates["Entry Date"])
all_candidates["Exit Date"] = pd.to_datetime(all_candidates["Exit Date"])

all_candidates = all_candidates.sort_values("Entry Date")

portfolio_trades = []

print("\nRunning chronological portfolio simulation...")
print("=" * 60)

for _, trade in all_candidates.iterrows():
    symbol = trade["Symbol"]
    entry_price = trade["Entry Price"]
    exit_price = trade["Exit Price"]

    stop_loss = min(entry_price, exit_price)
    take_profit = max(entry_price, exit_price)

    sizing = calculate_position_size(
        account_balance=portfolio.cash,
        risk_percent=1,
        entry_price=entry_price,
        stop_loss=stop_loss
    )

    if sizing is None or sizing["shares"] <= 0:
        continue

    opened = portfolio.open_position(
        symbol=symbol,
        shares=sizing["shares"],
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit
    )

    if not opened["approved"]:
        continue

    closed = portfolio.close_position(
        symbol=symbol,
        exit_price=exit_price
    )

    portfolio_trades.append({
        "Symbol": symbol,
        "Entry Date": trade["Entry Date"],
        "Exit Date": trade["Exit Date"],
        "Shares": sizing["shares"],
        "Entry Price": entry_price,
        "Exit Price": exit_price,
        "Exit Reason": trade["Exit Reason"],
        "PnL %": trade["PnL %"],
        "PnL": closed["pnl"],
        "Cash": closed["cash"]
    })

results = pd.DataFrame(portfolio_trades)

print("\nPortfolio Backtest Results")
print("=" * 60)
print(results)

results.to_csv("analytics/portfolio_trades.csv", index=False)

print("\nFinal Portfolio:")
print(portfolio.summary())
print("\nSaved to analytics/portfolio_trades.csv")