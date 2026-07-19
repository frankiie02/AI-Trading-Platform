"""PaperBroker: adapts the existing local paper-trading subsystem to
BrokerInterface.

PaperBroker is an adapter, not a second execution engine. It owns no
persistence and no order-lifecycle logic of its own:

    submit_order        -> PaperTradingService.create_order_from_decision()
    cancel_order         -> PaperTradingService.cancel_order()
    get_account          -> PortfolioService.get_summary()
    get_positions         -> PortfolioService.get_positions()
    get_open_orders       -> PaperTradingService.get_open_orders()
    get_order             -> PaperTradingService.get_order()
    get_fills              -> core.execution.paper_orders_repository.get_trade_rows()
                              (an existing repository read, not a new
                              PaperTradingService concept - "fills" are the
                              raw execution ledger, distinct from
                              PaperTradingService.get_trades()'s completed-
                              round-trip-only view)

Rejection vs. exception (see core/broker/errors.py for the full rule):
malformed requests (bad symbol/quantity/side/order type, missing the
required reference price) raise BrokerValidationError/
BrokerUnsupportedOperationError before PaperTradingService is ever called.
A syntactically valid order that fails a business rule (insufficient cash,
position limits, etc.) comes back as BrokerOrder(status=REJECTED,
rejection_reason=...), mirroring PaperTradingService's own existing
convention (InsufficientCashError is defined there but never raised - the
same rejection already surfaces as a REJECTED PaperOrder).

Connection semantics: PaperBroker starts DISCONNECTED. connect()/
disconnect() only flip an in-memory flag - no socket, thread, process, or
network call is ever made, and no connection state is persisted to the
database. This exists purely for interface parity with future brokers that
manage a genuine connection; a local paper account has nothing to connect
to. Every account/position/order operation raises BrokerConnectionError
while disconnected. connect()/disconnect() are idempotent.
"""
import logging
from datetime import datetime
from typing import List, Optional

from core.broker.base import BrokerInterface
from core.broker.errors import (
    BrokerCancellationError,
    BrokerConnectionError,
    BrokerError,
    BrokerOrderNotFoundError,
    BrokerUnsupportedOperationError,
    BrokerValidationError,
)
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
from core.execution.paper_orders_repository import get_trade_rows
from core.pipeline.models import ScanStrategyMode, TradingDecision
from core.services.paper_trading_service import (
    InvalidOrderStateTransitionError,
    InvalidPaperOrderError,
    PaperTradingService,
    PaperTradingServiceError,
)
from core.services.portfolio_service import PortfolioService, PortfolioServiceError

_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

_ORDER_STATUS_MAP = {
    "CREATED": BrokerOrderStatus.PENDING,
    "VALIDATED": BrokerOrderStatus.PENDING,
    "SUBMITTED": BrokerOrderStatus.SUBMITTED,
    "FILLED": BrokerOrderStatus.FILLED,
    "REJECTED": BrokerOrderStatus.REJECTED,
    "CANCELLED": BrokerOrderStatus.CANCELLED,
    "EXPIRED": BrokerOrderStatus.EXPIRED,
}

_CLIENT_ORDER_ID_PREFIX = "broker:"


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None

    try:
        return datetime.strptime(value, _TIMESTAMP_FORMAT)
    except (TypeError, ValueError):
        return None


class PaperBroker(BrokerInterface):
    _BROKER_NAME = "paper"

    def __init__(
        self,
        paper_trading_service: PaperTradingService,
        portfolio_service: PortfolioService,
        logger: Optional[logging.Logger] = None,
    ):
        self._paper_trading_service = paper_trading_service
        self._portfolio_service = portfolio_service
        self._logger = logger or logging.getLogger(__name__)
        self._state = BrokerConnectionState.DISCONNECTED
        self._connected_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Identity / connection
    # ------------------------------------------------------------------

    @property
    def broker_name(self) -> str:
        return self._BROKER_NAME

    @property
    def is_connected(self) -> bool:
        return self._state is BrokerConnectionState.CONNECTED

    def connect(self) -> BrokerConnection:
        if self._state is BrokerConnectionState.DISCONNECTED:
            self._state = BrokerConnectionState.CONNECTED
            self._connected_at = datetime.now()

        return self.get_connection_status()

    def disconnect(self) -> None:
        self._state = BrokerConnectionState.DISCONNECTED
        self._connected_at = None

    def get_connection_status(self) -> BrokerConnection:
        return BrokerConnection(
            broker_name=self._BROKER_NAME,
            state=self._state,
            environment=BrokerEnvironment.PAPER,
            account_id=None,
            connected_at=self._connected_at,
            message=(
                "Local simulated paper account; no network connection exists."
                if self.is_connected else "Disconnected."
            ),
        )

    def _require_connection(self) -> None:
        if not self.is_connected:
            raise BrokerConnectionError(
                "PaperBroker is not connected. Call connect() first.",
                broker_name=self._BROKER_NAME,
            )

    # ------------------------------------------------------------------
    # Account / positions (read-only, via PortfolioService)
    # ------------------------------------------------------------------

    def get_account(self) -> BrokerAccount:
        self._require_connection()

        try:
            account_id = self._paper_trading_service.get_account().account_id
            summary = self._portfolio_service.get_summary()
        except (PaperTradingServiceError, PortfolioServiceError) as exc:
            raise BrokerError(str(exc), broker_name=self._BROKER_NAME) from exc

        buying_power = max(summary.cash - summary.reserved_cash, 0.0)

        return BrokerAccount(
            account_id=account_id,
            currency="USD",
            cash=summary.cash,
            reserved_cash=summary.reserved_cash,
            buying_power=buying_power,
            market_value=summary.market_value,
            equity=summary.equity,
            realised_pnl=summary.realised_pnl,
            unrealised_pnl=summary.unrealised_pnl,
            total_pnl=summary.total_pnl,
            status="ACTIVE",
            timestamp=datetime.now(),
        )

    def get_positions(self) -> List[BrokerPosition]:
        self._require_connection()

        try:
            positions = self._portfolio_service.get_positions()
        except PortfolioServiceError as exc:
            raise BrokerError(str(exc), broker_name=self._BROKER_NAME) from exc

        return [self._to_broker_position(position) for position in positions]

    @staticmethod
    def _to_broker_position(position) -> BrokerPosition:
        return BrokerPosition(
            symbol=position.symbol,
            quantity=position.quantity,
            average_entry_price=position.average_entry_price,
            current_price=position.current_price,
            cost_basis=position.cost_basis,
            market_value=position.market_value,
            unrealised_pnl=position.unrealised_pnl,
            realised_pnl=position.realised_pnl,
            side=BrokerOrderSide.BUY,
            opened_at=_parse_timestamp(position.opened_at),
            strategy_name=position.strategy_name,
            strategy_mode=position.strategy_mode,
        )

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def get_open_orders(self) -> List[BrokerOrder]:
        self._require_connection()

        try:
            orders = self._paper_trading_service.get_open_orders()
        except PaperTradingServiceError as exc:
            raise BrokerError(str(exc), broker_name=self._BROKER_NAME) from exc

        return [self._to_broker_order(order) for order in orders]

    def get_order(self, order_id: str) -> Optional[BrokerOrder]:
        self._require_connection()
        numeric_id = self._parse_order_id(order_id)

        try:
            order = self._paper_trading_service.get_order(numeric_id)
        except PaperTradingServiceError as exc:
            raise BrokerError(str(exc), broker_name=self._BROKER_NAME, order_id=order_id) from exc

        return self._to_broker_order(order) if order is not None else None

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrder:
        self._require_connection()
        self._validate_request(request)

        hold_for_review = bool(request.metadata.get("hold_for_review", False))

        decision = TradingDecision(
            symbol=request.symbol,
            final_signal="BUY",
            raw_signal="BUY",
            strategy_name=request.strategy_name or "Broker",
            strategy_mode=ScanStrategyMode.SINGLE,
            current_price=request.limit_price,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            suggested_shares=request.quantity,
        )

        source_reference = (
            f"{_CLIENT_ORDER_ID_PREFIX}{request.client_order_id}"
            if request.client_order_id else f"{_CLIENT_ORDER_ID_PREFIX}manual"
        )

        try:
            order = self._paper_trading_service.create_order_from_decision(
                decision, source_reference=source_reference, auto_fill=not hold_for_review,
            )
        except InvalidPaperOrderError as exc:
            raise BrokerValidationError(
                str(exc), broker_name=self._BROKER_NAME, symbol=request.symbol
            ) from exc
        except PaperTradingServiceError as exc:
            raise BrokerError(
                str(exc), broker_name=self._BROKER_NAME, symbol=request.symbol
            ) from exc

        return self._to_broker_order(order)

    def cancel_order(self, order_id: str) -> BrokerOrder:
        self._require_connection()
        numeric_id = self._parse_order_id(order_id)

        existing = self._paper_trading_service.get_order(numeric_id)

        if existing is None:
            raise BrokerOrderNotFoundError(
                f"No order with id {order_id}.", broker_name=self._BROKER_NAME, order_id=order_id
            )

        try:
            cancelled = self._paper_trading_service.cancel_order(numeric_id)
        except InvalidOrderStateTransitionError as exc:
            raise BrokerCancellationError(
                str(exc), broker_name=self._BROKER_NAME, order_id=order_id
            ) from exc
        except PaperTradingServiceError as exc:
            raise BrokerError(
                str(exc), broker_name=self._BROKER_NAME, order_id=order_id
            ) from exc

        return self._to_broker_order(cancelled)

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
            rows = list(get_trade_rows(self._paper_trading_service.db_path))
        except Exception as exc:
            raise BrokerError(str(exc), broker_name=self._BROKER_NAME) from exc

        if order_id is not None:
            numeric_id = self._parse_order_id(order_id)
            rows = [row for row in rows if row["order_id"] == numeric_id]

        # get_trade_rows() is newest-first (ORDER BY id DESC); fills are
        # reported chronologically, oldest first.
        rows.reverse()

        if limit is not None:
            rows = rows[-limit:]

        return [self._to_broker_fill(row) for row in rows]

    @staticmethod
    def _to_broker_fill(row) -> BrokerFill:
        side = row["side"] if row["side"] in ("BUY", "SELL") else "BUY"

        return BrokerFill(
            fill_id=str(row["id"]),
            broker_order_id=str(row["order_id"]) if row["order_id"] is not None else None,
            symbol=row["symbol"],
            side=BrokerOrderSide(side),
            quantity=row["shares"],
            fill_price=row["price"],
            commission=row["fees"] or 0.0,
            timestamp=_parse_timestamp(row["timestamp"]),
            metadata={"exit_reason": row["exit_reason"]} if row["exit_reason"] else {},
        )

    # ------------------------------------------------------------------
    # Request validation / model mapping
    # ------------------------------------------------------------------

    def _validate_request(self, request: BrokerOrderRequest) -> None:
        if not request.symbol:
            raise BrokerValidationError("Symbol is required.", broker_name=self._BROKER_NAME)

        if request.quantity is None or request.quantity <= 0:
            raise BrokerValidationError(
                "Quantity must be a positive integer.",
                broker_name=self._BROKER_NAME, symbol=request.symbol,
            )

        if request.side is not BrokerOrderSide.BUY:
            raise BrokerUnsupportedOperationError(
                f"PaperBroker only supports BUY orders (long-only, no short "
                f"selling); got side={request.side.value}.",
                broker_name=self._BROKER_NAME, symbol=request.symbol,
            )

        if request.order_type is not BrokerOrderType.MARKET:
            raise BrokerUnsupportedOperationError(
                f"PaperBroker only supports MARKET orders; got "
                f"order_type={request.order_type.value}.",
                broker_name=self._BROKER_NAME, symbol=request.symbol,
            )

        if not request.limit_price or request.limit_price <= 0:
            raise BrokerValidationError(
                "A positive limit_price is required as the explicit "
                "fill-reference price for market orders in this simulated "
                "paper environment (no real market-data feed exists).",
                broker_name=self._BROKER_NAME, symbol=request.symbol,
            )

    def _to_broker_order(self, order) -> BrokerOrder:
        status = _ORDER_STATUS_MAP.get(order.status, BrokerOrderStatus.PENDING)
        filled_quantity = order.quantity if status is BrokerOrderStatus.FILLED else 0

        metadata = {}
        if order.source_reference:
            metadata["source_reference"] = order.source_reference
        if order.strategy_name:
            metadata["strategy_name"] = order.strategy_name
        if order.strategy_mode:
            metadata["strategy_mode"] = order.strategy_mode

        return BrokerOrder(
            broker_order_id=str(order.order_id),
            client_order_id=self._extract_client_order_id(order.source_reference),
            symbol=order.symbol,
            side=BrokerOrderSide.BUY,
            requested_quantity=order.quantity,
            filled_quantity=filled_quantity,
            order_type=BrokerOrderType.MARKET,
            status=status,
            limit_price=order.requested_price,
            stop_price=None,
            average_fill_price=order.fill_price,
            commission=order.fees,
            rejection_reason=order.rejection_reason,
            created_at=_parse_timestamp(order.created_at),
            updated_at=_parse_timestamp(order.updated_at),
            metadata=metadata,
        )

    @staticmethod
    def _extract_client_order_id(source_reference: Optional[str]) -> Optional[str]:
        if not source_reference or not source_reference.startswith(_CLIENT_ORDER_ID_PREFIX):
            return None

        value = source_reference[len(_CLIENT_ORDER_ID_PREFIX):]
        return value if value != "manual" else None

    def _parse_order_id(self, order_id) -> int:
        try:
            return int(order_id)
        except (TypeError, ValueError):
            raise BrokerValidationError(
                f"Invalid order id: {order_id!r}", broker_name=self._BROKER_NAME
            )
