"""Broker-neutral typed models for core/broker/.

These models are deliberately independent of PaperTradingService's own
PaperAccount/PaperOrder/PaperPosition/PaperTrade shapes: they exist so that
PaperBroker, and every future broker adapter (IBKR, Alpaca, OANDA), expose
exactly the same contract regardless of what sits behind them. PaperBroker
(core/broker/paper_broker.py) is responsible for mapping PaperTradingService/
PortfolioService objects into these; no other module should construct them.

BrokerOrderRequest.__post_init__ only normalises the symbol (strip + upper),
matching the existing ScanRequest/BacktestRequest/_OrderRequest convention
elsewhere in this codebase. It does not validate quantity, order type, or
price - that validation is owned by the broker adapter (PaperBroker
raises BrokerValidationError/BrokerUnsupportedOperationError before calling
into PaperTradingService), since different brokers may have different
structural rules.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class BrokerEnvironment(str, Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"
    SIMULATION = "SIMULATION"


class BrokerConnectionState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTED = "CONNECTED"


class BrokerOrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class BrokerOrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class BrokerTimeInForce(str, Enum):
    DAY = "DAY"
    GTC = "GTC"


class BrokerOrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


@dataclass
class BrokerConnection:
    broker_name: str
    state: BrokerConnectionState
    environment: BrokerEnvironment
    account_id: Optional[str] = None
    connected_at: Optional[datetime] = None
    message: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def is_connected(self) -> bool:
        return self.state == BrokerConnectionState.CONNECTED


@dataclass
class BrokerAccount:
    account_id: str
    currency: str
    cash: float
    reserved_cash: float
    buying_power: float
    market_value: float
    equity: float
    realised_pnl: float
    unrealised_pnl: float
    total_pnl: float
    status: str
    timestamp: Optional[datetime] = None


@dataclass
class BrokerPosition:
    symbol: str
    quantity: int
    average_entry_price: float
    current_price: float
    cost_basis: float
    market_value: float
    unrealised_pnl: float
    realised_pnl: Optional[float]
    side: BrokerOrderSide
    opened_at: Optional[datetime] = None
    strategy_name: Optional[str] = None
    strategy_mode: Optional[str] = None


@dataclass
class BrokerOrderRequest:
    symbol: str
    side: BrokerOrderSide
    quantity: int
    order_type: BrokerOrderType = BrokerOrderType.MARKET
    time_in_force: BrokerTimeInForce = BrokerTimeInForce.DAY
    # For a MARKET order, limit_price doubles as the required explicit
    # reference/fill price in this simulated paper environment (there is no
    # real market-data feed to fill against) - see paper_broker.py.
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    client_order_id: Optional[str] = None
    strategy_name: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.symbol:
            self.symbol = self.symbol.strip().upper()

        if not isinstance(self.side, BrokerOrderSide):
            self.side = BrokerOrderSide(self.side)

        if not isinstance(self.order_type, BrokerOrderType):
            self.order_type = BrokerOrderType(self.order_type)

        if not isinstance(self.time_in_force, BrokerTimeInForce):
            self.time_in_force = BrokerTimeInForce(self.time_in_force)


@dataclass
class BrokerOrder:
    broker_order_id: str
    client_order_id: Optional[str]
    symbol: str
    side: BrokerOrderSide
    requested_quantity: int
    filled_quantity: int
    order_type: BrokerOrderType
    status: BrokerOrderStatus
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    average_fill_price: Optional[float] = None
    commission: Optional[float] = None
    rejection_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)

    @property
    def remaining_quantity(self) -> int:
        return max(self.requested_quantity - self.filled_quantity, 0)


@dataclass
class BrokerFill:
    fill_id: str
    broker_order_id: Optional[str]
    symbol: str
    side: BrokerOrderSide
    quantity: int
    fill_price: float
    commission: float
    timestamp: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)
