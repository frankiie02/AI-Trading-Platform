"""Read-only Interactive Brokers adapter.

IBKRBroker implements the existing BrokerInterface for account inspection
only - connection, account summary, positions, open orders, and fills.
submit_order()/cancel_order() always raise BrokerUnsupportedOperationError;
no order-transmission code exists anywhere in this file (statically
verified by tests/unit/test_ibkr_broker.py, which asserts none of
placeOrder/place_order/cancelOrder/reqGlobalCancel/transmit appear in the
source of this module).

IBKRBroker depends only on IBKRClientProtocol (ibkr_client.py), never on
ib_insync directly - mapping code reads raw objects via plain attribute
access (ib_insync's own long-stable attribute names: `.tag`, `.value`,
`.position`, `.avgCost`, `.order.action`, `.orderStatus.status`,
`.execution.execId`, ...), so the identical mapping logic runs against
either a real IBInsyncClient or a test fake with zero ib_insync dependency.

Connection semantics mirror PaperBroker: starts DISCONNECTED, connect()/
disconnect() are idempotent, every read raises BrokerConnectionError while
disconnected, and no connection state is ever persisted to the database
(IBKRBroker never imports core.database). Unlike PaperBroker, connect()
performs a single, explicitly-bounded (config.timeout) call into the
injected client - no retry loop, no background worker, no thread or
process is created.

Safety boundary (see IBKRConnectionConfig.__post_init__): this milestone
requires read_only=True and environment != LIVE at configuration-construction
time - fail closed, not at first use.

Account/position mapping conventions (documented per-field, since IBKR's
data does not line up 1:1 with the broker-neutral model):
  - equity is taken directly from IBKR's own 'NetLiquidation' account tag,
    never recomputed as cash + market_value, so unrealised P&L is never
    double-counted against it.
  - reserved_cash has no IBKR equivalent surfaced in this milestone; it is
    reported as 0.0 (documented, not fabricated), mirroring PaperBroker's
    own "nothing is held aside" convention.
  - current_price/market_value/unrealised_pnl on a BrokerPosition are None
    when IBKR's positions() response does not include them (this milestone
    never fetches market data separately) - never a fabricated number.
  - get_order(order_id) only searches currently-open orders (there is no
    separate persisted order history in a read-only adapter); a filled or
    cancelled order that has aged out of IBKR's open-orders view returns
    None, not an error.
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from core.broker.base import BrokerInterface
from core.broker.errors import (
    BrokerConnectionError,
    BrokerError,
    BrokerUnsupportedOperationError,
    BrokerValidationError,
)
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
)

_BROKER_NAME = "ibkr"

_IBKR_ORDER_STATUS_MAP = {
    "PendingSubmit": BrokerOrderStatus.PENDING,
    "PreSubmitted": BrokerOrderStatus.PENDING,
    "Submitted": BrokerOrderStatus.SUBMITTED,
    "Filled": BrokerOrderStatus.FILLED,
    "PartiallyFilled": BrokerOrderStatus.PARTIALLY_FILLED,
    "Cancelled": BrokerOrderStatus.CANCELLED,
    "ApiCancelled": BrokerOrderStatus.CANCELLED,
    "PendingCancel": BrokerOrderStatus.CANCELLED,
    "Inactive": BrokerOrderStatus.REJECTED,
}

_IBKR_ORDER_TYPE_MAP = {
    "MKT": BrokerOrderType.MARKET,
    "LMT": BrokerOrderType.LIMIT,
    "STP": BrokerOrderType.STOP,
}


@dataclass
class IBKRConnectionConfig:
    host: str
    port: int
    client_id: int
    account_id: Optional[str] = None
    timeout: float = 5.0
    read_only: bool = True
    environment: BrokerEnvironment = BrokerEnvironment.PAPER

    def __post_init__(self):
        if not self.read_only:
            raise BrokerValidationError(
                "IBKRConnectionConfig.read_only must be True in this "
                "milestone; order transmission is not implemented.",
                broker_name=_BROKER_NAME,
            )

        if self.environment is BrokerEnvironment.LIVE:
            raise BrokerUnsupportedOperationError(
                "IBKRConnectionConfig.environment must not be LIVE in this "
                "milestone.",
                broker_name=_BROKER_NAME,
            )

        if not self.host:
            raise BrokerValidationError(
                "IBKRConnectionConfig.host is required.", broker_name=_BROKER_NAME
            )

        if not isinstance(self.port, int) or isinstance(self.port, bool) or self.port <= 0:
            raise BrokerValidationError(
                "IBKRConnectionConfig.port must be a positive integer.",
                broker_name=_BROKER_NAME,
            )

        if not isinstance(self.client_id, int) or isinstance(self.client_id, bool):
            raise BrokerValidationError(
                "IBKRConnectionConfig.client_id must be an integer.",
                broker_name=_BROKER_NAME,
            )

        if not isinstance(self.timeout, (int, float)) or self.timeout <= 0:
            raise BrokerValidationError(
                "IBKRConnectionConfig.timeout must be a positive number.",
                broker_name=_BROKER_NAME,
            )


class IBKRBroker(BrokerInterface):
    def __init__(
        self,
        config: IBKRConnectionConfig,
        client: Optional[IBKRClientProtocol] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._config = config
        self._client = client or self._build_default_client()
        self._logger = logger or logging.getLogger(__name__)
        self._state = BrokerConnectionState.DISCONNECTED
        self._connected_at: Optional[datetime] = None
        self._account_id = config.account_id

    @staticmethod
    def _build_default_client() -> IBKRClientProtocol:
        # Imported lazily so core.broker.ibkr_broker stays importable even
        # when ib_insync is not installed - only constructing a real client
        # (i.e. no fake client was injected) requires the package.
        from core.broker.ibkr_client import IBInsyncClient

        return IBInsyncClient()

    # ------------------------------------------------------------------
    # Identity / connection
    # ------------------------------------------------------------------

    @property
    def broker_name(self) -> str:
        return _BROKER_NAME

    @property
    def is_connected(self) -> bool:
        return self._state is BrokerConnectionState.CONNECTED

    def connect(self) -> BrokerConnection:
        if self._state is BrokerConnectionState.DISCONNECTED:
            self._logger.info(
                "Connecting to IBKR host=%s port=%s client_id=%s (read_only=%s)",
                self._config.host, self._config.port, self._config.client_id,
                self._config.read_only,
            )

            try:
                self._client.connect(
                    host=self._config.host,
                    port=self._config.port,
                    client_id=self._config.client_id,
                    timeout=self._config.timeout,
                    readonly=self._config.read_only,
                )
            except Exception as exc:
                raise BrokerConnectionError(
                    f"Failed to connect to IBKR: {exc}", broker_name=_BROKER_NAME
                ) from exc

            if not self._client.is_connected:
                raise BrokerConnectionError(
                    "IBKR client reported not connected after connect().",
                    broker_name=_BROKER_NAME,
                )

            self._state = BrokerConnectionState.CONNECTED
            self._connected_at = datetime.now()
            self._logger.info(
                "Connected to IBKR (account=%s)", self._mask(self._account_id)
            )

        return self.get_connection_status()

    def disconnect(self) -> None:
        if self._state is BrokerConnectionState.CONNECTED:
            try:
                self._client.disconnect()
            except Exception:
                self._logger.exception(
                    "Error while disconnecting from IBKR; forcing local "
                    "state to DISCONNECTED regardless."
                )

            self._logger.info("Disconnected from IBKR.")

        self._state = BrokerConnectionState.DISCONNECTED
        self._connected_at = None

    def get_connection_status(self) -> BrokerConnection:
        return BrokerConnection(
            broker_name=_BROKER_NAME,
            state=self._state,
            environment=self._config.environment,
            account_id=self._account_id,
            connected_at=self._connected_at,
            message=(
                "Read-only IBKR connection (order transmission disabled)."
                if self.is_connected else "Disconnected."
            ),
            metadata={"read_only": self._config.read_only, "port": self._config.port},
        )

    def _require_connection(self) -> None:
        if not self.is_connected:
            raise BrokerConnectionError(
                "IBKRBroker is not connected. Call connect() first.",
                broker_name=_BROKER_NAME,
            )

    @staticmethod
    def _mask(value: Optional[str]) -> Optional[str]:
        if not value:
            return value

        text = str(value)

        if len(text) <= 4:
            return "*" * len(text)

        return text[:2] + "*" * (len(text) - 4) + text[-2:]

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def get_account(self) -> BrokerAccount:
        self._require_connection()

        try:
            rows = self._client.account_values()
        except Exception as exc:
            raise BrokerError(
                f"Failed to read IBKR account values: {exc}", broker_name=_BROKER_NAME
            ) from exc

        account_id = self._select_account_id(rows)
        self._account_id = account_id

        filtered = [row for row in rows if getattr(row, "account", None) == account_id]

        cash = self._tag_float(filtered, "TotalCashValue")
        equity = self._tag_float(filtered, "NetLiquidation")
        buying_power = self._tag_float(filtered, "BuyingPower")
        market_value = self._tag_float(filtered, "GrossPositionValue")
        realised_pnl = self._tag_float(filtered, "RealizedPnL")
        unrealised_pnl = self._tag_float(filtered, "UnrealizedPnL")
        currency = self._tag_currency(filtered, "TotalCashValue") or "USD"

        self._logger.info(
            "Read IBKR account summary (account=%s, %d value row(s))",
            self._mask(account_id), len(filtered),
        )

        return BrokerAccount(
            account_id=account_id,
            currency=currency,
            cash=cash,
            # No IBKR equivalent is surfaced in this milestone - documented,
            # not fabricated. Mirrors PaperBroker's own "nothing held aside"
            # convention.
            reserved_cash=0.0,
            buying_power=buying_power,
            market_value=market_value,
            # Taken directly from IBKR's own NetLiquidation tag - never
            # recomputed from cash + market_value, so unrealised P&L is
            # never double-counted against it.
            equity=equity,
            realised_pnl=realised_pnl,
            unrealised_pnl=unrealised_pnl,
            total_pnl=realised_pnl + unrealised_pnl,
            status="ACTIVE",
            timestamp=datetime.now(),
        )

    def _select_account_id(self, rows) -> str:
        if self._config.account_id is not None:
            available = {getattr(row, "account", None) for row in rows}
            if rows and self._config.account_id not in available:
                raise BrokerValidationError(
                    f"Configured account_id {self._config.account_id!r} was "
                    f"not found among the IBKR accounts returned.",
                    broker_name=_BROKER_NAME,
                )
            return self._config.account_id

        distinct = sorted({
            getattr(row, "account", None) for row in rows
            if getattr(row, "account", None)
        })

        if not distinct:
            raise BrokerError(
                "No IBKR account data was returned.", broker_name=_BROKER_NAME
            )

        if len(distinct) > 1:
            raise BrokerValidationError(
                f"Multiple IBKR accounts were returned ({len(distinct)}) and "
                f"no account_id was configured to disambiguate.",
                broker_name=_BROKER_NAME,
            )

        return distinct[0]

    @staticmethod
    def _tag_float(rows, tag_name: str, default: float = 0.0) -> float:
        matches = [row for row in rows if getattr(row, "tag", None) == tag_name]

        if not matches:
            return default

        base_matches = [row for row in matches if getattr(row, "currency", None) == "BASE"]
        chosen = base_matches[0] if base_matches else matches[0]

        try:
            return float(getattr(chosen, "value", default))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _tag_currency(rows, tag_name: str) -> Optional[str]:
        matches = [row for row in rows if getattr(row, "tag", None) == tag_name]
        non_base = [row for row in matches if getattr(row, "currency", None) not in (None, "BASE")]

        if non_base:
            return getattr(non_base[0], "currency", None)

        return None

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def get_positions(self) -> List[BrokerPosition]:
        self._require_connection()

        try:
            rows = self._client.positions()
        except Exception as exc:
            raise BrokerError(
                f"Failed to read IBKR positions: {exc}", broker_name=_BROKER_NAME
            ) from exc

        if self._config.account_id is not None:
            rows = [row for row in rows if getattr(row, "account", None) == self._config.account_id]

        self._logger.info("Read %d IBKR position(s)", len(rows))

        return [self._to_broker_position(row) for row in rows]

    @staticmethod
    def _to_broker_position(row) -> BrokerPosition:
        contract = getattr(row, "contract", None)
        symbol = getattr(contract, "symbol", None) or ""
        raw_quantity = getattr(row, "position", 0) or 0
        quantity = int(round(raw_quantity))
        average_entry_price = float(getattr(row, "avgCost", 0.0) or 0.0)
        cost_basis = quantity * average_entry_price

        return BrokerPosition(
            symbol=symbol,
            quantity=quantity,
            average_entry_price=average_entry_price,
            # positions() carries no live quote - never fabricated.
            current_price=None,
            cost_basis=cost_basis,
            market_value=None,
            unrealised_pnl=None,
            realised_pnl=None,
            side=BrokerOrderSide.BUY if raw_quantity >= 0 else BrokerOrderSide.SELL,
            opened_at=None,
            metadata={
                "account": getattr(row, "account", None),
                "con_id": getattr(contract, "conId", None),
                "sec_type": getattr(contract, "secType", None),
                "exchange": getattr(contract, "exchange", None),
                "currency": getattr(contract, "currency", None),
                "raw_quantity": raw_quantity,
            },
        )

    # ------------------------------------------------------------------
    # Orders (read-only)
    # ------------------------------------------------------------------

    def get_open_orders(self) -> List[BrokerOrder]:
        self._require_connection()

        try:
            trades = self._client.open_orders()
        except Exception as exc:
            raise BrokerError(
                f"Failed to read IBKR open orders: {exc}", broker_name=_BROKER_NAME
            ) from exc

        self._logger.info("Read %d IBKR open order(s)", len(trades))

        orders = [self._to_broker_order(trade) for trade in trades]
        orders.sort(key=lambda o: o.created_at or datetime.min)

        return orders

    def get_order(self, order_id: str) -> Optional[BrokerOrder]:
        self._require_connection()

        for order in self.get_open_orders():
            if order.broker_order_id == str(order_id):
                return order

        return None

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrder:
        raise BrokerUnsupportedOperationError(
            "IBKRBroker is read-only in this milestone: order submission is "
            "not implemented.",
            broker_name=_BROKER_NAME,
        )

    def cancel_order(self, order_id: str) -> BrokerOrder:
        raise BrokerUnsupportedOperationError(
            "IBKRBroker is read-only in this milestone: order cancellation "
            "is not implemented.",
            broker_name=_BROKER_NAME,
            order_id=order_id,
        )

    @staticmethod
    def _to_broker_order(trade) -> BrokerOrder:
        order = getattr(trade, "order", None)
        order_status = getattr(trade, "orderStatus", None)
        contract = getattr(trade, "contract", None)

        raw_status = getattr(order_status, "status", None) or ""
        status = _IBKR_ORDER_STATUS_MAP.get(raw_status, BrokerOrderStatus.PENDING)

        side_raw = getattr(order, "action", "BUY")
        side = BrokerOrderSide.BUY if side_raw == "BUY" else BrokerOrderSide.SELL

        order_type_raw = getattr(order, "orderType", "MKT")
        order_type = _IBKR_ORDER_TYPE_MAP.get(order_type_raw, BrokerOrderType.MARKET)

        requested_quantity = int(getattr(order, "totalQuantity", 0) or 0)
        filled_quantity = int(getattr(order_status, "filled", 0) or 0)

        limit_price = getattr(order, "lmtPrice", None)
        stop_price = getattr(order, "auxPrice", None)
        avg_fill_price = getattr(order_status, "avgFillPrice", None)

        broker_order_id = str(getattr(order, "orderId", "") or getattr(order, "permId", "") or "")
        order_ref = getattr(order, "orderRef", None)
        client_order_id = str(order_ref) if order_ref else None

        return BrokerOrder(
            broker_order_id=broker_order_id,
            client_order_id=client_order_id,
            symbol=getattr(contract, "symbol", "") or "",
            side=side,
            requested_quantity=requested_quantity,
            filled_quantity=filled_quantity,
            order_type=order_type,
            status=status,
            limit_price=float(limit_price) if limit_price else None,
            stop_price=float(stop_price) if stop_price else None,
            average_fill_price=float(avg_fill_price) if avg_fill_price else None,
            commission=None,
            rejection_reason=None,
            created_at=None,
            updated_at=None,
            metadata={
                "raw_status": raw_status,
                "con_id": getattr(contract, "conId", None),
            },
        )

    # ------------------------------------------------------------------
    # Fills
    # ------------------------------------------------------------------

    def get_fills(
        self,
        order_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[BrokerFill]:
        self._require_connection()

        try:
            rows = self._client.fills()
        except Exception as exc:
            raise BrokerError(
                f"Failed to read IBKR fills: {exc}", broker_name=_BROKER_NAME
            ) from exc

        mapped = []
        seen_ids = set()

        for row in rows:
            execution = getattr(row, "execution", None)
            exec_id = getattr(execution, "execId", None)
            fill_id = str(exec_id) if exec_id else str(id(row))

            if fill_id in seen_ids:
                continue

            seen_ids.add(fill_id)
            mapped.append(self._to_broker_fill(row, fill_id))

        if order_id is not None:
            mapped = [fill for fill in mapped if fill.broker_order_id == str(order_id)]

        mapped.sort(key=lambda fill: fill.timestamp or datetime.min)

        if limit is not None:
            mapped = mapped[-limit:]

        self._logger.info("Read %d IBKR fill(s)", len(mapped))

        return mapped

    @staticmethod
    def _to_broker_fill(row, fill_id: str) -> BrokerFill:
        execution = getattr(row, "execution", None)
        commission_report = getattr(row, "commissionReport", None)
        contract = getattr(row, "contract", None)

        side_raw = getattr(execution, "side", "BOT")
        side = BrokerOrderSide.BUY if side_raw in ("BOT", "BUY") else BrokerOrderSide.SELL

        quantity = int(getattr(execution, "shares", 0) or 0)
        fill_price = float(getattr(execution, "price", 0.0) or 0.0)
        commission = (
            float(getattr(commission_report, "commission", 0.0) or 0.0)
            if commission_report is not None else 0.0
        )

        raw_order_id = getattr(execution, "orderId", None)
        broker_order_id = str(raw_order_id) if raw_order_id else None

        timestamp = getattr(execution, "time", None)

        return BrokerFill(
            fill_id=fill_id,
            broker_order_id=broker_order_id,
            symbol=getattr(contract, "symbol", "") or "",
            side=side,
            quantity=quantity,
            fill_price=fill_price,
            commission=commission,
            timestamp=timestamp if isinstance(timestamp, datetime) else None,
            metadata={"exec_id": getattr(execution, "execId", None)},
        )
