"""Broker-neutral abstract contract.

BrokerInterface separates broker-facing account/position/order operations
from trading decisions (TradingPipeline), local paper-state mutation
(PaperTradingService), and read-only portfolio analytics (PortfolioService).
It defines the single contract every broker adapter - PaperBroker today,
IBKR/Alpaca/OANDA in future milestones - must satisfy, so orchestration code
written against BrokerInterface never needs to know which broker is behind
it.

An ABC (not typing.Protocol) is used deliberately: BrokerInterface cannot be
instantiated directly, and every concrete adapter must implement every
abstract method or fail at class-definition time - stronger, earlier
feedback than structural typing would give for a contract multiple future
adapters need to satisfy identically.
"""
from abc import ABC, abstractmethod
from typing import List, Optional

from core.broker.models import (
    BrokerAccount,
    BrokerConnection,
    BrokerFill,
    BrokerOrder,
    BrokerOrderRequest,
    BrokerPosition,
)


class BrokerInterface(ABC):
    """Abstract broker contract. No implementation, no state, no I/O."""

    @property
    @abstractmethod
    def broker_name(self) -> str:
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        ...

    @abstractmethod
    def connect(self) -> BrokerConnection:
        ...

    @abstractmethod
    def disconnect(self) -> None:
        ...

    @abstractmethod
    def get_connection_status(self) -> BrokerConnection:
        ...

    @abstractmethod
    def get_account(self) -> BrokerAccount:
        ...

    @abstractmethod
    def get_positions(self) -> List[BrokerPosition]:
        ...

    @abstractmethod
    def get_open_orders(self) -> List[BrokerOrder]:
        ...

    @abstractmethod
    def get_order(self, order_id: str) -> Optional[BrokerOrder]:
        ...

    @abstractmethod
    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrder:
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> BrokerOrder:
        ...

    @abstractmethod
    def get_fills(
        self,
        order_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[BrokerFill]:
        ...
