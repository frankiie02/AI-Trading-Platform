from dataclasses import dataclass
from datetime import datetime


@dataclass
class Signal:
    symbol: str
    timestamp: datetime
    action: str

    confidence: float

    entry_price: float
    stop_loss: float
    take_profit: float

    strategy: str
    score: int

    approved: bool = False