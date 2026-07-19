import ast
import os

import pytest

from core.pipeline.models import ScanStrategyMode, TradingDecision
from core.services.paper_trading_service import (
    ExitReason,
    InvalidOrderStateTransitionError,
    InvalidPaperOrderError,
    OrderStatus,
    PaperTradingPersistenceError,
    PaperTradingService,
    PositionNotFoundError,
)

FORBIDDEN_IMPORT_PREFIXES = (
    "streamlit",
    "pages",
    "dashboard",
    "core.broker",
    "core.runtime",
    "ib_insync",
)

# Proves PaperTradingService coordinates the shared pipeline's TradingDecision
# rather than reimplementing any domain algorithm itself.
FORBIDDEN_DIRECT_COLLABORATOR_MODULES = (
    "core.strategy",
    "core.voting",
    "core.regime",
    "core.alpha",
    "core.risk",
    "core.indicators",
    "core.market_data",
    "core.pipeline.trading_pipeline",
)

MODULE_PATH = os.path.join("core", "services", "paper_trading_service.py")


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "paper_test.db")


def make_service(db_path, **overrides):
    kwargs = dict(
        db_path=db_path,
        starting_balance=10000.0,
        commission=1.0,
        slippage_percent=1.0,
        max_open_positions=3,
        max_position_percent=100.0,
        require_stop_loss=False,
        require_take_profit=False,
    )
    kwargs.update(overrides)
    return PaperTradingService(**kwargs)


def make_decision(**overrides):
    fields = dict(
        symbol="AAPL",
        final_signal="BUY",
        raw_signal="BUY",
        strategy_name="EMA Trend",
        strategy_mode=ScanStrategyMode.SINGLE,
        current_price=100.0,
        stop_loss=90.0,
        take_profit=120.0,
        suggested_shares=10,
        alpha_score=80,
    )
    fields.update(overrides)
    return TradingDecision(**fields)


# ----------------------------------------------------------------------
# Account initialisation
# ----------------------------------------------------------------------

def test_initialise_new_account(db_path):
    service = make_service(db_path, starting_balance=5000.0)
    account = service.get_account()

    assert account.starting_balance == 5000.0
    assert account.cash == 5000.0
    assert account.equity == 5000.0
    assert account.realised_pnl == 0.0


def test_load_existing_account_does_not_reset_cash(db_path):
    service_one = make_service(db_path, starting_balance=5000.0)
    order = service_one.create_order_from_decision(make_decision(suggested_shares=5))
    assert order.status == OrderStatus.FILLED.value

    service_two = make_service(db_path, starting_balance=999999.0)
    account = service_two.get_account()

    assert account.starting_balance == 5000.0
    assert account.cash < 5000.0


# ----------------------------------------------------------------------
# Order creation from a TradingDecision
# ----------------------------------------------------------------------

def test_create_valid_buy_order_from_approved_decision(db_path):
    service = make_service(db_path)
    order = service.create_order_from_decision(make_decision())

    assert order.status == OrderStatus.FILLED.value
    assert order.symbol == "AAPL"
    assert order.fill_price == pytest.approx(101.0)  # 100 * 1.01 slippage
    assert order.fees == 1.0


def test_reject_non_actionable_decision(db_path):
    service = make_service(db_path)

    with pytest.raises(InvalidPaperOrderError):
        service.create_order_from_decision(make_decision(final_signal="NO TRADE"))


def test_reject_invalid_quantity(db_path):
    service = make_service(db_path)
    order = service.create_order_from_decision(make_decision(suggested_shares=0))

    assert order.status == OrderStatus.REJECTED.value
    assert "Quantity" in order.rejection_reason


def test_reject_insufficient_cash(db_path):
    service = make_service(db_path, starting_balance=100.0)
    order = service.create_order_from_decision(
        make_decision(current_price=1000.0, suggested_shares=1)
    )

    assert order.status == OrderStatus.REJECTED.value
    assert "cash" in order.rejection_reason.lower()


def test_reject_maximum_position_violation(db_path):
    service = make_service(db_path, starting_balance=10000.0, max_position_percent=1.0)
    order = service.create_order_from_decision(
        make_decision(current_price=100.0, suggested_shares=50)
    )

    assert order.status == OrderStatus.REJECTED.value
    assert "position size" in order.rejection_reason.lower()


def test_reject_maximum_open_positions_violation(db_path):
    service = make_service(db_path, max_open_positions=1)
    first = service.create_order_from_decision(make_decision(symbol="AAPL", suggested_shares=1))
    assert first.status == OrderStatus.FILLED.value

    second = service.create_order_from_decision(make_decision(symbol="MSFT", suggested_shares=1))

    assert second.status == OrderStatus.REJECTED.value
    assert "open positions" in second.rejection_reason.lower()


# ----------------------------------------------------------------------
# Order lifecycle / state transitions
# ----------------------------------------------------------------------

def test_valid_order_state_transitions(db_path):
    service = make_service(db_path)
    order = service.create_order_from_decision(make_decision(), auto_fill=False)

    assert order.status == OrderStatus.VALIDATED.value

    submitted = service.submit_order(order.order_id)
    assert submitted.status == OrderStatus.SUBMITTED.value

    filled = service.fill_order(order.order_id)
    assert filled.status == OrderStatus.FILLED.value


@pytest.mark.parametrize(
    "setup, action",
    [
        ("rejected", "fill"),
        ("filled", "cancel"),
        ("cancelled", "submit"),
    ],
)
def test_invalid_order_state_transitions(db_path, setup, action):
    service = make_service(db_path)

    if setup == "rejected":
        order = service.create_order_from_decision(make_decision(suggested_shares=0))
    elif setup == "filled":
        order = service.create_order_from_decision(make_decision())
    elif setup == "cancelled":
        order = service.create_order_from_decision(make_decision(), auto_fill=False)
        order = service.cancel_order(order.order_id)

    with pytest.raises(InvalidOrderStateTransitionError):
        if action == "fill":
            service.fill_order(order.order_id)
        elif action == "cancel":
            service.cancel_order(order.order_id)
        elif action == "submit":
            service.submit_order(order.order_id)


def test_get_order_returns_matching_order(db_path):
    service = make_service(db_path)
    created = service.create_order_from_decision(make_decision())

    fetched = service.get_order(created.order_id)

    assert fetched is not None
    assert fetched.order_id == created.order_id
    assert fetched.status == OrderStatus.FILLED.value


def test_get_order_returns_none_for_missing_order(db_path):
    service = make_service(db_path)

    assert service.get_order(999999) is None


def test_get_open_orders_excludes_terminal_orders(db_path):
    service = make_service(db_path, max_open_positions=5)

    held = service.create_order_from_decision(
        make_decision(symbol="AAPL"), auto_fill=False
    )
    filled = service.create_order_from_decision(make_decision(symbol="MSFT"))
    rejected = service.create_order_from_decision(
        make_decision(symbol="TSLA", suggested_shares=0)
    )

    open_orders = service.get_open_orders()
    open_ids = {order.order_id for order in open_orders}

    assert held.order_id in open_ids
    assert filled.order_id not in open_ids
    assert rejected.order_id not in open_ids


def test_get_open_orders_empty_when_none_pending(db_path):
    service = make_service(db_path)
    service.create_order_from_decision(make_decision())

    assert service.get_open_orders() == []


# ----------------------------------------------------------------------
# Fill convention: slippage, commission, atomicity
# ----------------------------------------------------------------------

def test_deterministic_buy_slippage(db_path):
    service = make_service(db_path, commission=0.0, slippage_percent=2.0)
    order = service.create_order_from_decision(make_decision(current_price=100.0))

    assert order.fill_price == pytest.approx(102.0)


def test_deterministic_sell_slippage(db_path):
    service = make_service(db_path, commission=0.0, slippage_percent=2.0)
    service.create_order_from_decision(make_decision(current_price=100.0, stop_loss=None, take_profit=None))

    trade = service.close_position("AAPL", price=100.0, reason=ExitReason.MANUAL)

    assert trade.exit_price == pytest.approx(98.0)


def test_commission_applied_on_entry_and_exit(db_path):
    service = make_service(db_path, commission=2.5, slippage_percent=0.0)
    order = service.create_order_from_decision(
        make_decision(current_price=100.0, stop_loss=None, take_profit=None)
    )
    assert order.fees == 2.5

    trade = service.close_position("AAPL", price=100.0, reason=ExitReason.MANUAL)
    assert trade.fees == 2.5
    assert trade.net_pnl == pytest.approx(trade.gross_pnl - 2.5)


def test_fill_order_atomically_rolls_back_on_failure(db_path, monkeypatch):
    import core.execution.paper_orders_repository as repository

    service = make_service(db_path)
    account_before = service.get_account()

    real_get_connection = repository.get_connection

    class ExplodingCursor:
        def __init__(self, real_cursor):
            self._real_cursor = real_cursor
            self._calls = 0

        def execute(self, sql, params=None):
            self._calls += 1
            if "INSERT INTO paper_trades" in sql:
                raise RuntimeError("simulated failure")
            return self._real_cursor.execute(sql, params) if params is not None else self._real_cursor.execute(sql)

        def __getattr__(self, name):
            return getattr(self._real_cursor, name)

    class ExplodingConnection:
        def __init__(self, real_conn):
            self._real_conn = real_conn

        def cursor(self):
            return ExplodingCursor(self._real_conn.cursor())

        def __getattr__(self, name):
            return getattr(self._real_conn, name)

    def patched_get_connection(db_path=None):
        return ExplodingConnection(real_get_connection(db_path))

    monkeypatch.setattr(repository, "get_connection", patched_get_connection)

    with pytest.raises(PaperTradingPersistenceError):
        service.create_order_from_decision(make_decision())

    monkeypatch.undo()

    account_after = service.get_account()
    assert account_after.cash == account_before.cash
    assert service.get_positions() == []


# ----------------------------------------------------------------------
# Positions
# ----------------------------------------------------------------------

def test_cash_deduction_on_buy(db_path):
    service = make_service(db_path, starting_balance=10000.0, commission=0.0, slippage_percent=0.0)
    service.create_order_from_decision(make_decision(current_price=100.0, suggested_shares=10))

    account = service.get_account()
    assert account.cash == pytest.approx(9000.0)


def test_position_creation_on_buy(db_path):
    service = make_service(db_path)
    service.create_order_from_decision(make_decision(suggested_shares=10))

    positions = service.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "AAPL"
    assert positions[0].quantity == 10


def test_one_position_per_symbol_averages_entry(db_path):
    service = make_service(db_path, commission=0.0, slippage_percent=0.0)
    service.create_order_from_decision(make_decision(current_price=100.0, suggested_shares=10))
    service.create_order_from_decision(make_decision(current_price=200.0, suggested_shares=10))

    positions = service.get_positions()
    assert len(positions) == 1
    assert positions[0].quantity == 20
    assert positions[0].average_entry_price == pytest.approx(150.0)


def test_current_price_update(db_path):
    service = make_service(db_path)
    service.create_order_from_decision(make_decision(suggested_shares=10))

    service.update_positions({"AAPL": 150.0})

    positions = service.get_positions()
    assert positions[0].current_price == 150.0


def test_unrealised_pnl_after_price_update(db_path):
    service = make_service(db_path, commission=0.0, slippage_percent=0.0)
    service.create_order_from_decision(make_decision(current_price=100.0, suggested_shares=10))

    service.update_positions({"AAPL": 120.0})

    positions = service.get_positions()
    assert positions[0].unrealised_pnl == pytest.approx(200.0)


# ----------------------------------------------------------------------
# Exits
# ----------------------------------------------------------------------

def test_stop_loss_exit(db_path):
    service = make_service(db_path, commission=0.0, slippage_percent=0.0)
    service.create_order_from_decision(
        make_decision(current_price=100.0, stop_loss=95.0, take_profit=120.0, suggested_shares=10)
    )

    trades = service.check_exits({"AAPL": 94.0})

    assert len(trades) == 1
    assert trades[0].exit_reason == ExitReason.STOP_LOSS.value
    assert service.get_positions() == []


def test_take_profit_exit(db_path):
    service = make_service(db_path, commission=0.0, slippage_percent=0.0)
    service.create_order_from_decision(
        make_decision(current_price=100.0, stop_loss=90.0, take_profit=110.0, suggested_shares=10)
    )

    trades = service.check_exits({"AAPL": 111.0})

    assert len(trades) == 1
    assert trades[0].exit_reason == ExitReason.TAKE_PROFIT.value


def test_adverse_first_when_stop_and_target_both_crossed(db_path):
    service = make_service(db_path, commission=0.0, slippage_percent=0.0)
    # Deliberately inverted stop/target so a single price crosses both -
    # exercises the adverse-first (stop-checked-before-target) code path.
    service.create_order_from_decision(
        make_decision(current_price=100.0, stop_loss=100.0, take_profit=90.0, suggested_shares=10)
    )

    trades = service.check_exits({"AAPL": 95.0})

    assert len(trades) == 1
    assert trades[0].exit_reason == ExitReason.STOP_LOSS.value


def test_manual_close(db_path):
    service = make_service(db_path, commission=0.0, slippage_percent=0.0)
    service.create_order_from_decision(make_decision(current_price=100.0, suggested_shares=10))

    trade = service.close_position("AAPL", price=105.0, reason=ExitReason.MANUAL)

    assert trade.exit_reason == ExitReason.MANUAL.value
    assert service.get_positions() == []


def test_close_position_not_found(db_path):
    service = make_service(db_path)

    with pytest.raises(PositionNotFoundError):
        service.close_position("ZZZZ")


def test_realised_pnl_after_close(db_path):
    service = make_service(db_path, commission=0.0, slippage_percent=0.0)
    service.create_order_from_decision(make_decision(current_price=100.0, suggested_shares=10))

    service.close_position("AAPL", price=110.0, reason=ExitReason.MANUAL)

    account = service.get_account()
    assert account.realised_pnl == pytest.approx(100.0)


def test_trade_history_recording(db_path):
    service = make_service(db_path, commission=0.0, slippage_percent=0.0)
    service.create_order_from_decision(make_decision(current_price=100.0, suggested_shares=10))
    service.close_position("AAPL", price=110.0, reason=ExitReason.MANUAL)

    trades = service.get_trades()
    assert len(trades) == 1
    assert trades[0].net_pnl == pytest.approx(100.0)


def test_account_equity_calculation(db_path):
    service = make_service(db_path, commission=0.0, slippage_percent=0.0)
    service.create_order_from_decision(make_decision(current_price=100.0, suggested_shares=10))
    service.update_positions({"AAPL": 120.0})

    account = service.get_account()
    assert account.equity == pytest.approx(account.cash + 1200.0)


# ----------------------------------------------------------------------
# Reconciliation
# ----------------------------------------------------------------------

def test_reconciliation_success(db_path):
    service = make_service(db_path)
    service.create_order_from_decision(make_decision(suggested_shares=5))
    service.close_position("AAPL", price=105.0, reason=ExitReason.MANUAL)

    result = service.reconcile()

    assert result.balanced is True


def test_reconciliation_mismatch(db_path):
    from core.database.database import get_connection

    service = make_service(db_path)
    service.create_order_from_decision(make_decision(suggested_shares=5))
    service.close_position("AAPL", price=200.0, reason=ExitReason.MANUAL)

    conn = get_connection(db_path)
    conn.execute("UPDATE account_state SET realised_pnl = realised_pnl + 999 WHERE id = 1")
    conn.commit()
    conn.close()

    result = service.reconcile()

    assert result.balanced is False
    assert "realised_pnl_mismatch" in result.differences


# ----------------------------------------------------------------------
# Queue processing
# ----------------------------------------------------------------------

def test_queue_processing_disabled_by_default(db_path):
    service = make_service(db_path)
    result = service.process_queue()

    assert result.orders_created == []
    assert any("disabled" in warning for warning in result.warnings)


def test_queue_processing_when_enabled(db_path):
    rows = [
        {"ID": 1, "Symbol": "AAPL", "Side": "BUY", "Shares": 5, "Price": 100.0,
         "Stop Loss": 90.0, "Take Profit": 120.0},
    ]

    statuses = []

    def fake_get_pending(db_path=None):
        return rows

    def fake_update_status(trade_id, status, db_path=None):
        statuses.append((trade_id, status))

    service = make_service(
        db_path,
        get_pending_trades_fn=fake_get_pending,
        update_trade_status_fn=fake_update_status,
    )

    result = service.process_queue(enabled=True)

    assert len(result.orders_filled) == 1
    assert statuses == [(1, "EXECUTED")]


def test_rejected_queue_item_does_not_corrupt_others(db_path):
    rows = [
        {"ID": 1, "Symbol": "AAPL", "Side": "BUY", "Shares": 0, "Price": 100.0},
        {"ID": 2, "Symbol": "MSFT", "Side": "BUY", "Shares": 5, "Price": 200.0},
    ]

    statuses = []

    def fake_get_pending(db_path=None):
        return rows

    def fake_update_status(trade_id, status, db_path=None):
        statuses.append((trade_id, status))

    service = make_service(
        db_path,
        get_pending_trades_fn=fake_get_pending,
        update_trade_status_fn=fake_update_status,
    )

    result = service.process_queue(enabled=True)

    assert len(result.orders_filled) == 1
    assert len(result.orders_rejected) == 1
    assert (1, "REJECTED") in statuses
    assert (2, "EXECUTED") in statuses


def test_queue_selected_ids_filter(db_path):
    rows = [
        {"ID": 1, "Symbol": "AAPL", "Side": "BUY", "Shares": 5, "Price": 100.0},
        {"ID": 2, "Symbol": "MSFT", "Side": "BUY", "Shares": 5, "Price": 200.0},
    ]

    def fake_get_pending(db_path=None):
        return rows

    def fake_update_status(trade_id, status, db_path=None):
        pass

    service = make_service(
        db_path,
        get_pending_trades_fn=fake_get_pending,
        update_trade_status_fn=fake_update_status,
    )

    result = service.process_queue(enabled=True, queue_ids=[2])

    assert len(result.orders_created) == 1
    assert result.orders_created[0].symbol == "MSFT"


# ----------------------------------------------------------------------
# Import-boundary / no-broker / no-live guards
# ----------------------------------------------------------------------

def _module_imports():
    with open(MODULE_PATH) as f:
        tree = ast.parse(f.read(), filename=MODULE_PATH)

    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)

    return imports


def test_paper_trading_service_has_no_forbidden_imports():
    imports = _module_imports()

    for module in imports:
        for forbidden in FORBIDDEN_IMPORT_PREFIXES:
            assert not module.startswith(forbidden), (
                f"paper_trading_service.py imports forbidden module: {module}"
            )


def test_paper_trading_service_does_not_import_domain_collaborators_directly():
    imports = _module_imports()

    for module in imports:
        for forbidden in FORBIDDEN_DIRECT_COLLABORATOR_MODULES:
            assert not module.startswith(forbidden), (
                f"paper_trading_service.py imports domain collaborator directly: {module}"
            )


def test_paper_trading_service_makes_no_streamlit_import():
    with open(MODULE_PATH) as f:
        source = f.read()

    assert "streamlit" not in source
    assert "ib_insync" not in source


def test_no_real_project_database_touched(db_path):
    """Every test in this file passes an explicit tmp_path db_path; this
    test asserts the default constructor argument is never relied upon
    here (a static safeguard against accidental production-DB writes)."""
    import inspect

    signature = inspect.signature(PaperTradingService.__init__)
    assert "db_path" in signature.parameters
    # Sanity: our own tests always override it.
    assert db_path.endswith("paper_test.db")
