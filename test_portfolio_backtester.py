from analytics.portfolio_backtester import PortfolioBacktester

bt = PortfolioBacktester(
    starting_balance=100000,
    risk_percent=1,
    max_positions=5
)

bt.process_trade(
    symbol="AMD",
    entry_price=561.17,
    stop_loss=525.20,
    take_profit=633.11,
    exit_price=633.11
)

bt.process_trade(
    symbol="NVDA",
    entry_price=194.81,
    stop_loss=182.00,
    take_profit=220.00,
    exit_price=220.00
)

print("\nPortfolio Summary")
print("=" * 50)

summary = bt.summary()

print(f"Cash: ${summary['cash']:.2f}")
print(f"Trades: {summary['trades']}")

print("\nTrade Log")

for trade in summary["trade_log"]:
    print(trade)