"""IBKR client-facing protocol and the concrete ib_insync wrapper.

IBKRBroker (ibkr_broker.py) depends only on IBKRClientProtocol - it never
imports ib_insync or references any ib_insync type directly, so its mapping
logic is identical whether driven by a real IBInsyncClient or a test fake.
No ib_insync type appears in this Protocol's signatures: every method
returns plain lists of opaque objects that IBKRBroker reads via attribute
access (`.tag`, `.value`, `.position`, `.avgCost`, `.order.action`,
`.orderStatus.status`, `.execution.execId`, ...) - the same, long-stable
ib_insync attribute names, but never an isinstance check against an
ib_insync class. That is what lets tests inject a plain SimpleNamespace-based
fake with zero ib_insync dependency.

The `ib_insync` import itself is optional and guarded: importing this
module never fails even when the package is not installed. Only
constructing IBInsyncClient (i.e. actually trying to use a real IBKR
connection) raises a controlled BrokerConnectionError if the package is
missing - never at import time, and never breaking the rest of the
platform.
"""
from typing import List, Protocol

from core.broker.errors import BrokerConnectionError

try:
    from ib_insync import IB
except ImportError:  # pragma: no cover - exercised only when ib_insync is absent
    IB = None


class IBKRClientProtocol(Protocol):
    @property
    def is_connected(self) -> bool:
        ...

    def connect(
        self,
        host: str,
        port: int,
        client_id: int,
        timeout: float,
        readonly: bool,
    ) -> None:
        ...

    def disconnect(self) -> None:
        ...

    def account_values(self) -> List[object]:
        ...

    def positions(self) -> List[object]:
        ...

    def open_orders(self) -> List[object]:
        ...

    def fills(self) -> List[object]:
        ...


class IBInsyncClient:
    """Thin wrapper around ib_insync.IB(). Owns no mapping logic - it only
    translates IBKRClientProtocol's neutral method names to ib_insync's
    actual API (connect/disconnect/isConnected/accountSummary/positions/
    openTrades/fills), so IBKRBroker never touches ib_insync directly."""

    def __init__(self):
        if IB is None:
            raise BrokerConnectionError(
                "IBKR support requires the optional 'ib_insync' package, "
                "which is not installed. Install it (see docs/broker.md) "
                "or inject a fake IBKRClientProtocol implementation for "
                "testing.",
                broker_name="ibkr",
            )

        self._ib = IB()

    @property
    def is_connected(self) -> bool:
        return bool(self._ib.isConnected())

    def connect(
        self,
        host: str,
        port: int,
        client_id: int,
        timeout: float,
        readonly: bool,
    ) -> None:
        self._ib.connect(
            host=host, port=port, clientId=client_id,
            timeout=timeout, readonly=readonly,
        )

    def disconnect(self) -> None:
        self._ib.disconnect()

    def account_values(self) -> List[object]:
        return list(self._ib.accountSummary())

    def positions(self) -> List[object]:
        return list(self._ib.positions())

    def open_orders(self) -> List[object]:
        return list(self._ib.openTrades())

    def fills(self) -> List[object]:
        return list(self._ib.fills())
