from datetime import datetime

from models.signal import Signal
from risk.portfolio import Portfolio
from engine.risk_engine import RiskEngine

portfolio = Portfolio(starting_balance=100000, max_open_positions=5)
risk_engine = RiskEngine(risk_percent=1)

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

print("\nRisk Engine Result")
print("=" * 40)
print("Reason:", reason)
print("Signal approved:", signal.approved)
print("Trade:", trade)