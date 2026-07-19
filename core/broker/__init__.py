"""Broker-neutral interface and adapters.

PaperBroker (paper_broker.py) is the only concrete adapter implemented so
far - it wraps the existing local paper-trading subsystem
(PaperTradingService/PortfolioService). No external broker (IBKR, Alpaca,
OANDA), network call, or live credential exists anywhere in this package.
See docs/broker.md.
"""
from core.broker.base import BrokerInterface
from core.broker.errors import (
    BrokerCancellationError,
    BrokerConnectionError,
    BrokerError,
    BrokerOrderNotFoundError,
    BrokerOrderRejectedError,
    BrokerUnsupportedOperationError,
    BrokerValidationError,
)
from core.broker.factory import create_broker
from core.broker.models import (
    BrokerAccount,
    BrokerConnection,
    BrokerConnectionState,
    BrokerEnvironment,
    BrokerFill,
    BrokerOrder,
    BrokerOrderRequest,
    BrokerOrderSide,
    BrokerOrderStatus,
    BrokerOrderType,
    BrokerPosition,
    BrokerTimeInForce,
)
from core.broker.paper_broker import PaperBroker

__all__ = [
    "BrokerInterface",
    "PaperBroker",
    "create_broker",
    "BrokerAccount",
    "BrokerConnection",
    "BrokerConnectionState",
    "BrokerEnvironment",
    "BrokerFill",
    "BrokerOrder",
    "BrokerOrderRequest",
    "BrokerOrderSide",
    "BrokerOrderStatus",
    "BrokerOrderType",
    "BrokerPosition",
    "BrokerTimeInForce",
    "BrokerError",
    "BrokerCancellationError",
    "BrokerConnectionError",
    "BrokerOrderNotFoundError",
    "BrokerOrderRejectedError",
    "BrokerUnsupportedOperationError",
    "BrokerValidationError",
]
