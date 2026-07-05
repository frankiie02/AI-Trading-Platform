from datetime import datetime

from models.signal import Signal
from data.market_data import get_price_history
from strategies.trend_join_long import generate_trend_signal


class Scanner:
    def __init__(self, symbols):
        self.symbols = symbols

    def scan(self):
        signals = []

        for symbol in self.symbols:
            try:
                data = get_price_history(symbol)
                result = generate_trend_signal(data, symbol)

                passed_rules = int(sum(result["rules"].values()))
                confidence = float(passed_rules / len(result["rules"]))

                if result["signal"] == "BUY":
                    signal = Signal(
                        symbol=symbol,
                        timestamp=datetime.now(),
                        action="BUY",
                        confidence=confidence,
                        entry_price=result["entry"],
                        stop_loss=result["stop_loss"],
                        take_profit=result["take_profit"],
                        strategy=result["strategy"],
                        score=passed_rules
                    )

                    signals.append(signal)

            except Exception as e:
                print(f"{symbol}: ERROR - {e}")

        return signals