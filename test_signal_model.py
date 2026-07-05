from datetime import datetime

from models.signal import Signal

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

print("\nSignal")
print("=" * 40)
print(signal)