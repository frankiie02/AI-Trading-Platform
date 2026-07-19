"""Controlled exception hierarchy for the broker interface (core/broker/).

Rejection-vs-exception rule (applies to every BrokerInterface implementation,
not just PaperBroker):

    Invalid API request or unsupported operation
    (bad symbol/quantity/order type/side, missing a required price, an
    operation the broker genuinely does not implement)
        -> raise BrokerValidationError or BrokerUnsupportedOperationError,
           before any underlying service is called.

    Valid request rejected by broker/account business rules
    (insufficient cash, position/exposure limits, etc.)
        -> return BrokerOrder(status=REJECTED, rejection_reason=...).
           This mirrors PaperTradingService's own existing convention
           exactly (InsufficientCashError is defined there but never
           raised - the same class of rejection already comes back as a
           REJECTED PaperOrder).

    Infrastructure/persistence failure
        -> raise BrokerError (or a subclass). Raw database/service
           exceptions are never allowed to leak through the interface.
"""


class BrokerError(Exception):
    """Base class for all broker-interface failures."""

    def __init__(self, message, *, broker_name=None, order_id=None, symbol=None, reason=None):
        super().__init__(message)
        self.broker_name = broker_name
        self.order_id = order_id
        self.symbol = symbol
        self.reason = reason


class BrokerConnectionError(BrokerError):
    """Raised when a broker operation is attempted without a live connection,
    or a connect()/disconnect() call itself fails."""


class BrokerValidationError(BrokerError):
    """Raised when a request is malformed before it ever reaches the
    underlying trading service (bad symbol, non-positive quantity, missing
    a required price, invalid side, etc.)."""


class BrokerOrderRejectedError(BrokerError):
    """Reserved for brokers that must raise rather than return a rejected
    order. PaperBroker does not raise this - business-rule rejections come
    back as BrokerOrder(status=REJECTED, ...), matching
    PaperTradingService's existing convention. Kept for interface
    completeness and for future brokers whose APIs raise on rejection."""


class BrokerOrderNotFoundError(BrokerError):
    """Raised when an operation references an order ID the broker has no
    record of."""


class BrokerCancellationError(BrokerError):
    """Raised when a cancellation cannot be completed (excluding the normal
    controlled case of a non-cancellable status, which PaperBroker maps to
    this with an explicit reason - see paper_broker.py)."""


class BrokerUnsupportedOperationError(BrokerError):
    """Raised for an operation or parameter the broker does not implement
    (e.g. a non-MARKET order type, a SELL/short request, live environment)."""
