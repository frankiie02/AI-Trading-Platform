"""Reusable, Streamlit-free paper-trading orchestration workflow.

PaperTradingService coordinates paper-account initialisation, order
creation/validation/fill simulation, position management, stop-loss/
take-profit exits, manual closes, trade-history recording, and account
reconciliation - the same kind of workflow ScannerService/BacktestService
already provide for their respective domains, reusing the shared
TradingPipeline's TradingDecision as its execution input rather than
reimplementing any indicator/strategy/regime/alpha/risk algorithm.

This service is completely simulated and local: it never imports a broker
SDK, never uses real credentials, and never submits a real order. The
pre-existing core/execution/paper_trader.py (PaperTrader) is left
completely untouched; this service owns its own independent fill/cash/
position bookkeeping (reusing PaperTrader's existing weighted-average-entry
and cash-delta conventions for consistency) against additive schema
changes (core/database/database.py), persisted through
core/execution/paper_orders_repository.py rather than raw SQL here.

Execution convention (mirrors BacktestService's, see
core/services/backtest_service.py, adapted for interactive/standalone use
rather than bar-by-bar historical replay):
  - Only an actionable decision (`TradingDecision.final_signal == "BUY"`)
    can create an order; long-only, no leverage, no short selling.
  - A market BUY fills at `reference_price * (1 + slippage / 100)`
    (adverse); an exit fills at `reference_price * (1 - slippage / 100)`
    (adverse). `reference_price` is the caller-supplied current price
    (from the TradingDecision, a queued signal, or a page/runtime-supplied
    quote) - this service never downloads market data itself.
  - A flat `commission` is charged per fill (entry and exit each incur it
    once).
  - Final order quantity is capped by available cash and by
    `max_position_percent` of account equity, in addition to the
    decision's own `suggested_shares`; partial fills are not supported -
    an order either fills in full at its (possibly capped) quantity or is
    rejected before it is submitted.
  - One open position per symbol; adding to an existing position averages
    the entry price (matching PaperTrader's existing convention).
  - Stop-loss is checked before take-profit when both could apply to a
    single supplied price update (adverse-first, matching BacktestService).
    Interactive paper trading only ever receives a single current price per
    update (no OHLC bar), so true same-bar intrabar collision detection
    does not apply here the way it does in BacktestService; adverse-first
    means the stop condition is evaluated first.
"""
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional

from core.database.database import DB_PATH, initialise_account, initialise_database
from core.execution.paper_orders_repository import (
    apply_entry_fill,
    apply_exit_fill,
    get_account_row,
    get_all_position_rows,
    get_order_row,
    get_order_rows,
    get_position_row,
    get_trade_rows,
    insert_audit_event,
    insert_order,
    sum_realised_pnl,
    update_order_status,
    update_position_levels as repository_update_position_levels,
    update_position_prices,
)
from core.execution.trade_queue import get_pending_trades, update_trade_status
from core.pipeline.models import TradingDecision


# ----------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------

class PaperTradingServiceError(Exception):
    """Base class for PaperTradingService-level failures."""


class InvalidPaperOrderError(PaperTradingServiceError):
    """Raised when an order request cannot be created/validated as given."""


class InvalidOrderStateTransitionError(PaperTradingServiceError):
    """Raised when an order-status transition is not allowed from its current state."""


class InsufficientCashError(PaperTradingServiceError):
    """Raised when an order cannot be sized above zero shares with available cash."""


class PositionNotFoundError(PaperTradingServiceError):
    """Raised when an operation references a symbol with no open position."""


class PaperTradingPersistenceError(PaperTradingServiceError):
    """Raised when paper-trading state cannot be persisted."""


class ReconciliationError(PaperTradingServiceError):
    """Raised when reconciliation itself cannot be computed (not for mismatches, which are returned)."""


# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------

class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ExitReason(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    MANUAL = "MANUAL"
    SIGNAL = "SIGNAL"


_ALLOWED_TRANSITIONS = {
    OrderStatus.CREATED: {OrderStatus.VALIDATED, OrderStatus.REJECTED, OrderStatus.CANCELLED},
    OrderStatus.VALIDATED: {OrderStatus.SUBMITTED, OrderStatus.REJECTED, OrderStatus.CANCELLED},
    OrderStatus.SUBMITTED: {OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELLED, OrderStatus.EXPIRED},
    OrderStatus.FILLED: set(),
    OrderStatus.REJECTED: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.EXPIRED: set(),
}

_CANCELLABLE_STATUSES = {OrderStatus.CREATED, OrderStatus.VALIDATED, OrderStatus.SUBMITTED}


# ----------------------------------------------------------------------
# Typed models
# ----------------------------------------------------------------------

@dataclass
class PaperAccount:
    account_id: str
    starting_balance: float
    cash: float
    equity: float
    realised_pnl: float
    unrealised_pnl: float
    reserved_cash: float
    buying_power: float
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class PaperOrder:
    order_id: int
    symbol: str
    side: str
    quantity: int
    order_type: str
    requested_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    strategy_name: Optional[str]
    strategy_mode: Optional[str]
    source_reference: Optional[str]
    status: str
    rejection_reason: Optional[str]
    fill_price: Optional[float]
    fill_timestamp: Optional[str]
    fees: Optional[float]
    created_at: str
    updated_at: str


@dataclass
class PaperPosition:
    symbol: str
    quantity: int
    average_entry_price: float
    current_price: float
    market_value: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    unrealised_pnl: float
    realised_pnl: float
    opened_at: Optional[str]
    updated_at: str
    strategy_name: Optional[str] = None
    strategy_mode: Optional[str] = None


@dataclass
class PaperTrade:
    trade_id: int
    symbol: str
    quantity: int
    entry_price: Optional[float]
    exit_price: float
    entry_timestamp: Optional[str]
    exit_timestamp: str
    gross_pnl: Optional[float]
    fees: Optional[float]
    net_pnl: Optional[float]
    exit_reason: Optional[str]
    strategy_name: Optional[str] = None
    strategy_mode: Optional[str] = None


@dataclass
class PaperTradingResult:
    account: PaperAccount
    orders_created: List[PaperOrder] = field(default_factory=list)
    orders_filled: List[PaperOrder] = field(default_factory=list)
    orders_rejected: List[PaperOrder] = field(default_factory=list)
    positions_opened: List[str] = field(default_factory=list)
    positions_closed: List[str] = field(default_factory=list)
    trades: List[PaperTrade] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    statistics: dict = field(default_factory=dict)


@dataclass
class ReconciliationResult:
    balanced: bool
    differences: dict = field(default_factory=dict)


@dataclass
class _OrderRequest:
    symbol: str
    side: OrderSide
    quantity: int
    reference_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    strategy_name: str
    strategy_mode: str
    source_reference: str


# ----------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------

class PaperTradingService:
    def __init__(
        self,
        db_path: str = DB_PATH,
        account_id: str = "default",
        starting_balance: float = 100000.0,
        commission: float = 0.0,
        slippage_percent: float = 0.0,
        max_open_positions: int = 10,
        max_position_percent: float = 25.0,
        require_stop_loss: bool = False,
        require_take_profit: bool = False,
        get_pending_trades_fn: Callable = get_pending_trades,
        update_trade_status_fn: Callable = update_trade_status,
        logger: Optional[logging.Logger] = None,
    ):
        self._db_path = db_path
        self._account_id = account_id
        self._starting_balance = starting_balance
        self._commission = commission
        self._slippage_percent = slippage_percent
        self._max_open_positions = max_open_positions
        self._max_position_percent = max_position_percent
        self._require_stop_loss = require_stop_loss
        self._require_take_profit = require_take_profit
        self._get_pending_trades_fn = get_pending_trades_fn
        self._update_trade_status_fn = update_trade_status_fn
        self._logger = logger or logging.getLogger(__name__)

        self.initialise_account()

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def initialise_account(self) -> PaperAccount:
        try:
            initialise_database(self._db_path)
            initialise_account(self._starting_balance, self._db_path)
        except Exception as exc:
            self._logger.exception("Failed to initialise paper account.")
            raise PaperTradingPersistenceError(
                "Failed to initialise the paper trading account."
            ) from exc

        return self.get_account()

    def get_account(self) -> PaperAccount:
        row = get_account_row(self._db_path)

        if row is None:
            raise PaperTradingPersistenceError("Paper account state is missing.")

        positions = get_all_position_rows(self._db_path)
        position_value = sum(p["market_value"] for p in positions)
        unrealised_pnl = sum(p["unrealised_pnl"] for p in positions)
        cash = row["cash"]
        reserved_cash = row["reserved_cash"] or 0.0
        equity = cash + position_value

        return PaperAccount(
            account_id=self._account_id,
            starting_balance=row["starting_balance"],
            cash=cash,
            equity=equity,
            realised_pnl=row["realised_pnl"] or 0.0,
            unrealised_pnl=unrealised_pnl,
            reserved_cash=reserved_cash,
            buying_power=cash - reserved_cash,
            updated_at=row["updated_at"],
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_positions(self) -> List[PaperPosition]:
        return [self._position_from_row(row) for row in get_all_position_rows(self._db_path)]

    def get_orders(self, status: Optional[OrderStatus] = None) -> List[PaperOrder]:
        status_value = status.value if isinstance(status, OrderStatus) else status
        return [self._order_from_row(row) for row in get_order_rows(status_value, self._db_path)]

    def get_trades(self) -> List[PaperTrade]:
        """Completed round-trip trades only (fill rows with an exit_reason);
        entry-only fill rows are excluded since they have no exit yet."""
        return [
            self._trade_from_row(row)
            for row in get_trade_rows(self._db_path)
            if row["exit_reason"] is not None
        ]

    # ------------------------------------------------------------------
    # Order creation
    # ------------------------------------------------------------------

    def create_order_from_decision(
        self,
        decision: TradingDecision,
        quantity: Optional[int] = None,
        source_reference: Optional[str] = None,
        auto_fill: bool = True,
    ) -> PaperOrder:
        if decision.final_signal != "BUY":
            raise InvalidPaperOrderError(
                "Only an actionable BUY decision (final_signal == 'BUY') can "
                "create a paper order."
            )

        strategy_mode = (
            decision.strategy_mode.value
            if hasattr(decision.strategy_mode, "value")
            else str(decision.strategy_mode)
        )

        order_request = _OrderRequest(
            symbol=decision.symbol,
            side=OrderSide.BUY,
            quantity=quantity if quantity is not None else decision.suggested_shares,
            reference_price=decision.current_price,
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
            strategy_name=decision.strategy_name,
            strategy_mode=strategy_mode,
            source_reference=source_reference or f"decision:{decision.symbol}",
        )

        return self._create_order(order_request, auto_fill=auto_fill)

    def process_queue(
        self,
        enabled: bool = False,
        limit: Optional[int] = None,
        auto_fill: bool = True,
        queue_ids: Optional[List[int]] = None,
    ) -> PaperTradingResult:
        result = PaperTradingResult(account=self.get_account())

        if not enabled:
            result.warnings.append(
                "Queue processing is disabled (PAPER_PROCESS_QUEUE=False); "
                "no queued signals were processed."
            )
            return result

        try:
            pending = self._get_pending_trades_fn(db_path=self._db_path)
        except Exception as exc:
            self._logger.exception("Failed to read pending trade-queue entries.")
            raise PaperTradingPersistenceError(
                "Failed to read pending trade-queue entries."
            ) from exc

        rows = pending.to_dict("records") if hasattr(pending, "to_dict") else list(pending)

        if queue_ids is not None:
            wanted = set(queue_ids)
            rows = [row for row in rows if row.get("ID") in wanted]

        if limit is not None:
            rows = rows[:limit]

        for row in rows:
            queue_id = row.get("ID")

            try:
                order_request = _OrderRequest(
                    symbol=str(row.get("Symbol", "")).upper(),
                    side=OrderSide.BUY,
                    quantity=int(row.get("Shares") or 0),
                    reference_price=row.get("Price"),
                    stop_loss=row.get("Stop Loss"),
                    take_profit=row.get("Take Profit"),
                    strategy_name="Queued Signal",
                    strategy_mode="queue",
                    source_reference=f"trade_queue:{queue_id}",
                )

                order = self._create_order(order_request, auto_fill=auto_fill)
                result.orders_created.append(order)

                if order.status == OrderStatus.FILLED.value:
                    result.orders_filled.append(order)
                    result.positions_opened.append(order.symbol)
                    self._update_queue_status(queue_id, "EXECUTED")
                elif order.status == OrderStatus.REJECTED.value:
                    result.orders_rejected.append(order)
                    self._update_queue_status(queue_id, "REJECTED")
            except Exception as exc:
                self._logger.exception(
                    "Failed to process queued trade %s; isolating failure.", queue_id
                )
                result.errors.append(f"Queue item {queue_id}: {exc}")
                self._update_queue_status(queue_id, "REJECTED")

        result.account = self.get_account()
        result.statistics = {
            "processed": len(rows),
            "filled": len(result.orders_filled),
            "rejected": len(result.orders_rejected),
        }

        return result

    def _update_queue_status(self, queue_id, status) -> None:
        if queue_id is None:
            return

        try:
            self._update_trade_status_fn(queue_id, status, db_path=self._db_path)
        except Exception:
            self._logger.exception(
                "Failed to update trade_queue status for item %s.", queue_id
            )

    # ------------------------------------------------------------------
    # Core order lifecycle
    # ------------------------------------------------------------------

    def _create_order(self, order_request: _OrderRequest, auto_fill: bool) -> PaperOrder:
        order_id = insert_order(
            symbol=order_request.symbol,
            side=order_request.side.value,
            quantity=order_request.quantity,
            order_type=OrderType.MARKET.value,
            requested_price=order_request.reference_price,
            stop_loss=order_request.stop_loss,
            take_profit=order_request.take_profit,
            strategy_name=order_request.strategy_name,
            strategy_mode=order_request.strategy_mode,
            source_reference=order_request.source_reference,
            status=OrderStatus.CREATED.value,
            db_path=self._db_path,
        )
        insert_audit_event(
            "ORDER_CREATED", symbol=order_request.symbol, order_id=order_id,
            details=order_request.source_reference, db_path=self._db_path,
        )

        final_quantity, fill_price, fees, rejection_reason = self._validate_order(order_request)

        if rejection_reason is not None:
            update_order_status(
                order_id, OrderStatus.REJECTED.value,
                rejection_reason=rejection_reason, db_path=self._db_path,
            )
            insert_audit_event(
                "ORDER_REJECTED", symbol=order_request.symbol, order_id=order_id,
                details=rejection_reason, db_path=self._db_path,
            )
            return self._order_from_row(get_order_row(order_id, self._db_path))

        update_order_status(
            order_id, OrderStatus.VALIDATED.value,
            quantity=final_quantity, db_path=self._db_path,
        )
        insert_audit_event(
            "ORDER_VALIDATED", symbol=order_request.symbol, order_id=order_id,
            db_path=self._db_path,
        )

        if not auto_fill:
            return self._order_from_row(get_order_row(order_id, self._db_path))

        self.submit_order(order_id)
        self._fill_entry_order(
            order_id, order_request.symbol, final_quantity, fill_price, fees,
            order_request.stop_loss, order_request.take_profit,
            order_request.strategy_name, order_request.strategy_mode,
        )

        return self._order_from_row(get_order_row(order_id, self._db_path))

    def _validate_order(self, order_request: _OrderRequest):
        """Returns (final_quantity, fill_price, fees, rejection_reason).
        rejection_reason is None when the order is valid."""
        if not order_request.symbol:
            return None, None, None, "Symbol is required."

        if order_request.side is not OrderSide.BUY:
            return None, None, None, (
                "Only BUY orders are created here; use close_position to exit."
            )

        if order_request.quantity is None or order_request.quantity <= 0:
            return None, None, None, "Quantity must be greater than zero."

        if self._require_stop_loss and order_request.stop_loss is None:
            return None, None, None, "Stop-loss is required."

        if self._require_take_profit and order_request.take_profit is None:
            return None, None, None, "Take-profit is required."

        if not order_request.reference_price or order_request.reference_price <= 0:
            return None, None, None, "A valid reference price is required."

        fill_price = order_request.reference_price * (1 + self._slippage_percent / 100)
        fees = self._commission

        account = self.get_account()
        existing_position = get_position_row(order_request.symbol, self._db_path)
        open_position_count = len(get_all_position_rows(self._db_path))

        if existing_position is None and open_position_count >= self._max_open_positions:
            return None, None, None, "Maximum open positions exceeded."

        max_affordable = (
            int((account.cash - fees) // fill_price) if fill_price > 0 else 0
        )
        max_by_position_limit = (
            int((account.equity * self._max_position_percent / 100) // fill_price)
            if fill_price > 0 else 0
        )

        final_quantity = min(order_request.quantity, max_affordable, max_by_position_limit)

        if final_quantity <= 0:
            if max_affordable <= 0:
                return None, None, None, "Insufficient cash for this order."
            if max_by_position_limit <= 0:
                return None, None, None, "Maximum position size would be exceeded."
            return None, None, None, "Invalid order quantity after sizing constraints."

        return final_quantity, fill_price, fees, None

    def submit_order(self, order_id: int) -> PaperOrder:
        row = self._require_order(order_id)
        self._validate_transition(OrderStatus(row["status"]), OrderStatus.SUBMITTED)

        update_order_status(order_id, OrderStatus.SUBMITTED.value, db_path=self._db_path)
        insert_audit_event(
            "ORDER_SUBMITTED", symbol=row["symbol"], order_id=order_id, db_path=self._db_path
        )

        return self._order_from_row(get_order_row(order_id, self._db_path))

    def _fill_entry_order(
        self, order_id, symbol, quantity, fill_price, fees,
        stop_loss, take_profit, strategy_name, strategy_mode,
    ) -> None:
        try:
            apply_entry_fill(
                order_id=order_id, symbol=symbol, quantity=quantity,
                fill_price=fill_price, fees=fees, stop_loss=stop_loss,
                take_profit=take_profit, strategy_name=strategy_name,
                strategy_mode=strategy_mode, db_path=self._db_path,
            )
        except Exception as exc:
            self._logger.exception("Failed to apply entry fill for order %s.", order_id)
            raise PaperTradingPersistenceError(
                f"Failed to apply fill for order {order_id}."
            ) from exc

        insert_audit_event(
            "ORDER_FILLED", symbol=symbol, order_id=order_id,
            details=f"{quantity}@{fill_price:.4f}", db_path=self._db_path,
        )

    def fill_order(self, order_id: int, reference_price: Optional[float] = None) -> PaperOrder:
        """Explicit SUBMITTED -> FILLED transition for orders created with
        auto_fill=False. Recomputes the fill price from the supplied (or
        stored) reference price using the same slippage convention."""
        row = self._require_order(order_id)
        self._validate_transition(OrderStatus(row["status"]), OrderStatus.FILLED)

        price = reference_price if reference_price is not None else row["requested_price"]

        if not price or price <= 0:
            raise InvalidPaperOrderError("A valid reference price is required to fill this order.")

        fill_price = price * (1 + self._slippage_percent / 100)

        self._fill_entry_order(
            order_id, row["symbol"], row["quantity"], fill_price, self._commission,
            row["stop_loss"], row["take_profit"], row["strategy_name"], row["strategy_mode"],
        )

        return self._order_from_row(get_order_row(order_id, self._db_path))

    def cancel_order(self, order_id: int) -> PaperOrder:
        row = self._require_order(order_id)
        current = OrderStatus(row["status"])

        if current not in _CANCELLABLE_STATUSES:
            raise InvalidOrderStateTransitionError(
                f"Order {order_id} cannot be cancelled from status {current.value}."
            )

        self._validate_transition(current, OrderStatus.CANCELLED)

        update_order_status(order_id, OrderStatus.CANCELLED.value, db_path=self._db_path)
        insert_audit_event(
            "ORDER_CANCELLED", symbol=row["symbol"], order_id=order_id, db_path=self._db_path
        )

        return self._order_from_row(get_order_row(order_id, self._db_path))

    def _require_order(self, order_id: int):
        row = get_order_row(order_id, self._db_path)

        if row is None:
            raise InvalidPaperOrderError(f"No paper order with id {order_id}.")

        return row

    @staticmethod
    def _validate_transition(current: OrderStatus, target: OrderStatus) -> None:
        if target not in _ALLOWED_TRANSITIONS.get(current, set()):
            raise InvalidOrderStateTransitionError(
                f"Cannot transition order from {current.value} to {target.value}."
            )

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

    def update_positions(self, price_map: Dict[str, float]) -> None:
        for symbol, price in price_map.items():
            if get_position_row(symbol, self._db_path) is not None:
                update_position_prices(symbol, price, self._db_path)

    def update_position_levels(
        self, symbol: str, stop_loss: Optional[float] = None, take_profit: Optional[float] = None
    ) -> PaperPosition:
        row = get_position_row(symbol, self._db_path)

        if row is None:
            raise PositionNotFoundError(f"No open position for {symbol}.")

        repository_update_position_levels(symbol, stop_loss, take_profit, self._db_path)

        return self._position_from_row(get_position_row(symbol, self._db_path))

    def check_exits(self, price_map: Dict[str, float]) -> List[PaperTrade]:
        """Evaluates stop-loss/take-profit against a single current-price
        update per symbol. Stop-loss is checked before take-profit
        (adverse-first) when a position has both configured."""
        closed_trades = []

        for symbol, price in price_map.items():
            row = get_position_row(symbol, self._db_path)

            if row is None:
                continue

            stop_loss = row["stop_loss"]
            take_profit = row["take_profit"]

            reason = None

            if stop_loss is not None and price <= stop_loss:
                reason = ExitReason.STOP_LOSS
            elif take_profit is not None and price >= take_profit:
                reason = ExitReason.TAKE_PROFIT

            if reason is not None:
                closed_trades.append(
                    self.close_position(symbol, price=price, reason=reason)
                )

        return closed_trades

    def close_position(
        self,
        symbol: str,
        quantity: Optional[int] = None,
        price: Optional[float] = None,
        reason: ExitReason = ExitReason.MANUAL,
    ) -> PaperTrade:
        row = get_position_row(symbol, self._db_path)

        if row is None:
            raise PositionNotFoundError(f"No open position for {symbol}.")

        close_quantity = quantity if quantity is not None else row["shares"]

        if close_quantity <= 0 or close_quantity > row["shares"]:
            raise InvalidPaperOrderError(
                f"Cannot close {close_quantity} shares of {symbol}; "
                f"{row['shares']} are held."
            )

        reference_price = price if price is not None else row["current_price"]

        if not reference_price or reference_price <= 0:
            raise InvalidPaperOrderError("A valid close price is required.")

        fill_price = reference_price * (1 - self._slippage_percent / 100)
        reason_value = reason.value if isinstance(reason, ExitReason) else str(reason)

        try:
            apply_exit_fill(
                symbol=symbol, quantity=close_quantity, fill_price=fill_price,
                fees=self._commission, exit_reason=reason_value,
                strategy_name=row["strategy_name"], strategy_mode=row["strategy_mode"],
                db_path=self._db_path,
            )
        except Exception as exc:
            self._logger.exception("Failed to close position for %s.", symbol)
            raise PaperTradingPersistenceError(
                f"Failed to close position for {symbol}."
            ) from exc

        insert_audit_event(
            "POSITION_CLOSED", symbol=symbol,
            details=f"{close_quantity}@{fill_price:.4f} ({reason_value})",
            db_path=self._db_path,
        )

        trades = get_trade_rows(self._db_path)
        latest = trades[0]

        return self._trade_from_row(latest)

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------

    def reconcile(self) -> ReconciliationResult:
        account_row = get_account_row(self._db_path)

        if account_row is None:
            raise ReconciliationError("Paper account state is missing.")

        positions = get_all_position_rows(self._db_path)
        cash = account_row["cash"]
        stored_realised = account_row["realised_pnl"] or 0.0

        position_value = sum(p["market_value"] for p in positions)
        expected_realised = sum_realised_pnl(self._db_path)

        issues = {}

        if cash < -1e-6:
            issues["cash_mismatch"] = {"value": cash, "issue": "cash is negative"}

        if abs(stored_realised - expected_realised) > 0.01:
            issues["realised_pnl_mismatch"] = {
                "stored": stored_realised,
                "expected_from_trades": expected_realised,
            }

        for row in positions:
            if row["shares"] <= 0:
                issues.setdefault("position_mismatches", []).append(
                    {"symbol": row["symbol"], "issue": "non-positive share count"}
                )

        return ReconciliationResult(
            balanced=len(issues) == 0,
            differences={
                **issues,
                "cash": cash,
                "position_value": position_value,
                "equity": cash + position_value,
                "realised_pnl": stored_realised,
            },
        )

    # ------------------------------------------------------------------
    # Row -> model mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _position_from_row(row) -> PaperPosition:
        return PaperPosition(
            symbol=row["symbol"],
            quantity=row["shares"],
            average_entry_price=row["entry_price"],
            current_price=row["current_price"],
            market_value=row["market_value"],
            stop_loss=row["stop_loss"],
            take_profit=row["take_profit"],
            unrealised_pnl=row["unrealised_pnl"],
            realised_pnl=row["realised_pnl"] or 0.0,
            opened_at=row["opened_at"],
            updated_at=row["updated_at"],
            strategy_name=row["strategy_name"],
            strategy_mode=row["strategy_mode"],
        )

    @staticmethod
    def _order_from_row(row) -> PaperOrder:
        return PaperOrder(
            order_id=row["id"],
            symbol=row["symbol"],
            side=row["side"],
            quantity=row["quantity"],
            order_type=row["order_type"],
            requested_price=row["requested_price"],
            stop_loss=row["stop_loss"],
            take_profit=row["take_profit"],
            strategy_name=row["strategy_name"],
            strategy_mode=row["strategy_mode"],
            source_reference=row["source_reference"],
            status=row["status"],
            rejection_reason=row["rejection_reason"],
            fill_price=row["fill_price"],
            fill_timestamp=row["fill_timestamp"],
            fees=row["fees"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _trade_from_row(row) -> PaperTrade:
        return PaperTrade(
            trade_id=row["id"],
            symbol=row["symbol"],
            quantity=row["shares"],
            entry_price=row["entry_price"],
            exit_price=row["price"],
            entry_timestamp=None,
            exit_timestamp=row["timestamp"],
            gross_pnl=row["gross_pnl"],
            fees=row["fees"],
            net_pnl=row["net_pnl"],
            exit_reason=row["exit_reason"],
            strategy_name=row["strategy_name"],
            strategy_mode=row["strategy_mode"],
        )
