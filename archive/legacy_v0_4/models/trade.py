from dataclasses import dataclass
from datetime import datetime


@dataclass
class Trade:
    symbol: str
    entry_date: datetime
    entry_price: float
    shares: int
    stop_loss: float
    take_profit: float

    exit_date: datetime | None = None
    exit_price: float | None = None
    status: str = "OPEN"
    pnl: float = 0.0

    def close(self, exit_price: float, exit_date: datetime):
        self.exit_price = round(exit_price, 2)
        self.exit_date = exit_date
        self.pnl = round(
            (exit_price - self.entry_price) * self.shares,
            2
        )
        self.status = "CLOSED"

    @property
    def capital(self):
        return round(
            self.entry_price * self.shares,
            2
        )