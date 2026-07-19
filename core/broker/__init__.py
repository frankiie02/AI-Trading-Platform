"""Broker-neutral interface and adapters.

PaperBroker (paper_broker.py) wraps the existing local paper-trading
subsystem (PaperTradingService/PortfolioService). IBKRBroker
(ibkr_broker.py) is a **read-only** Interactive Brokers adapter - account/
position/order/fill inspection only; submit_order()/cancel_order() always
raise BrokerUnsupportedOperationError. No order-transmission code exists
anywhere in this package, no network call is made at import time, and
importing this package never requires the optional `ib_insync` dependency
(only constructing a real, non-fake IBKR client does). See docs/broker.md.
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
from core.broker.factory import create_broker, create_ibkr_broker
from core.broker.ibkr_broker import IBKRBroker, IBKRConnectionConfig
from core.broker.ibkr_client import IBKRClientProtocol
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
    "IBKRBroker",
    "IBKRConnectionConfig",
    "IBKRClientProtocol",
    "create_broker",
    "create_ibkr_broker",
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
