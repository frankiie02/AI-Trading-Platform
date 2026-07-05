from datetime import datetime

from models.signal import Signal
from risk.portfolio import Portfolio
from engine.risk_engine import RiskEngine
from engine.execution_engine import ExecutionEngine

portfolio = Portfolio(starting_balance=100000, max_open_positions=5)
risk_engine = RiskEngine(risk_percent=1)
execution_engine = ExecutionEngine()

signal = Signal(
    symbol="AMD",
    timestamp=datetime.now(),
    action="BUY",
    confidence=0.85,
    entry_price=561.17,
    stop_loss=525.20,
    take_profit=633.11,
    strategy="Trend Join Long",
    score=3
)

trade, reason = risk_engine.approve_signal(signal, portfolio)

print("\nRisk Result")
print("=" * 40)
print(reason)
print(trade)

open_result = execution_engine.execute_trade(trade, portfolio)

print("\nOpen Result")
print("=" * 40)
print(open_result)
print(portfolio.summary())

close_result = execution_engine.close_trade(
    trade=trade,
    portfolio=portfolio,
    exit_price=633.11,
    exit_date=datetime.now()
)

print("\nClose Result")
print("=" * 40)
print(close_result)

print("\nClosed Trade")
print("=" * 40)
print(trade)

print("\nPortfolio Summary")
print("=" * 40)
print(portfolio.summary())