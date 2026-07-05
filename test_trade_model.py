from datetime import datetime

from models.trade import Trade

trade = Trade(
    symbol="AMD",
    entry_date=datetime(2026, 7, 1),
    entry_price=561.17,
    shares=27,
    stop_loss=525.20,
    take_profit=633.11
)

print("\nNew Trade")
print("=" * 40)
print(trade)

trade.close(
    exit_price=633.11,
    exit_date=datetime(2026, 7, 10)
)

print("\nClosed Trade")
print("=" * 40)
print(trade)

print("\nCapital Used")
print("=" * 40)
print(trade.capital)