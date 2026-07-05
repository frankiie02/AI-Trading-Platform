import os
import pandas as pd
from datetime import datetime

from config.settings import settings
from engine.scanner import Scanner
from engine.risk_engine import RiskEngine
from engine.execution_engine import ExecutionEngine
from risk.portfolio import Portfolio

portfolio = Portfolio(
    starting_balance=settings.STARTING_BALANCE,
    max_open_positions=settings.MAX_OPEN_POSITIONS
)

scanner = Scanner(settings.SYMBOLS)
risk_engine = RiskEngine(risk_percent=settings.RISK_PERCENT)
execution_engine = ExecutionEngine()

signals = scanner.scan()
trade_log = []

print("\nAI Trading Platform - Live Pipeline")
print("=" * 60)

if not signals:
    print("No BUY signals found.")
else:
    for signal in signals:
        print(f"\nSignal found: {signal.symbol}")

        trade, reason = risk_engine.approve_signal(signal, portfolio)
        print("Risk decision:", reason)

        if trade:
            result = execution_engine.execute_trade(trade, portfolio)
            print("Execution:", result)

            if result["approved"]:
                trade_log.append({
                    "Timestamp": datetime.now(),
                    "Symbol": trade.symbol,
                    "Action": "BUY",
                    "Strategy": signal.strategy,
                    "Confidence": signal.confidence,
                    "Score": signal.score,
                    "Shares": trade.shares,
                    "Entry Price": trade.entry_price,
                    "Stop Loss": trade.stop_loss,
                    "Take Profit": trade.take_profit,
                    "Capital Used": trade.capital,
                    "Cash Remaining": result["cash_remaining"]
                })

print("\nPortfolio Summary")
print("=" * 60)
print(portfolio.summary())

if trade_log:
    os.makedirs("logs", exist_ok=True)
    df = pd.DataFrame(trade_log)
    df.to_csv(settings.TRADE_LOG_PATH, index=False)
    print(f"\nTrade log saved to {settings.TRADE_LOG_PATH}")
else:
    print("\nNo trades executed, so no trade log was saved.")