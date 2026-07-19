import socket

import pytest

from core.broker.errors import (
    BrokerCancellationError,
    BrokerConnectionError,
    BrokerOrderNotFoundError,
    BrokerUnsupportedOperationError,
    BrokerValidationError,
)
from core.broker.models import (
    BrokerConnectionState,
    BrokerOrderRequest,
    BrokerOrderSide,
    BrokerOrderStatus,
    BrokerOrderType,
)
from core.broker.paper_broker import PaperBroker
from core.database.database import get_connection
from core.runtime.modes import RuntimeMode
from core.services.paper_trading_service import PaperTradingService
from core.services.portfolio_service import PortfolioService


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "paper_broker_test.db")


def make_broker(db_path, connect=True, **paper_kwargs):
    kwargs = dict(
        db_path=db_path, starting_balance=10000.0, commission=1.0, slippage_percent=0.0,
        max_open_positions=10, max_position_percent=100.0,
    )
    kwargs.update(paper_kwargs)
    paper = PaperTradingService(**kwargs)
    portfolio = PortfolioService(
        db_path=db_path, starting_balance=kwargs["starting_balance"], paper_trading_service=paper
    )
    broker = PaperBroker(paper, portfolio)

    if connect:
        broker.connect()

    return broker, paper, portfolio


def buy_request(**overrides):
    fields = dict(symbol="AAPL", side=BrokerOrderSide.BUY, quantity=10, limit_price=100.0)
    fields.update(overrides)
    return BrokerOrderRequest(**fields)


# ----------------------------------------------------------------------
# Connection semantics (12-19)
# ----------------------------------------------------------------------

def test_initial_connection_state_is_disconnected(db_path):
    broker, _, _ = make_broker(db_path, connect=False)
    assert broker.is_connected is False
    assert broker.get_connection_status().state is BrokerConnectionState.DISCONNECTED


def test_connect_marks_connected(db_path):
    broker, _, _ = make_broker(db_path, connect=False)
    connection = broker.connect()
    assert broker.is_connected is True
    assert connection.state is BrokerConnectionState.CONNECTED
    assert connection.connected_at is not None


def test_repeated_connect_is_idempotent(db_path):
    broker, _, _ = make_broker(db_path, connect=False)
    first = broker.connect()
    second = broker.connect()
    assert first.connected_at == second.connected_at
    assert broker.is_connected is True


def test_disconnect_marks_disconnected(db_path):
    broker, _, _ = make_broker(db_path)
    broker.disconnect()
    assert broker.is_connected is False


def test_repeated_disconnect_is_idempotent(db_path):
    broker, _, _ = make_broker(db_path)
    broker.disconnect()
    broker.disconnect()
    assert broker.is_connected is False


@pytest.mark.parametrize("operation", ["get_account", "get_positions", "get_open_orders", "get_fills"])
def test_operations_fail_while_disconnected(db_path, operation):
    broker, _, _ = make_broker(db_path, connect=False)
    with pytest.raises(BrokerConnectionError):
        getattr(broker, operation)()


def test_submit_order_fails_while_disconnected(db_path):
    broker, _, _ = make_broker(db_path, connect=False)
    with pytest.raises(BrokerConnectionError):
        broker.submit_order(buy_request())


def test_cancel_order_fails_while_disconnected(db_path):
    broker, _, _ = make_broker(db_path, connect=False)
    with pytest.raises(BrokerConnectionError):
        broker.cancel_order("1")


def test_no_network_call_during_full_workflow(monkeypatch, db_path):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("socket.socket() must not be called by PaperBroker")

    monkeypatch.setattr(socket, "socket", fail_if_called)

    broker, _, _ = make_broker(db_path, connect=False)
    broker.connect()
    broker.get_account()
    order = broker.submit_order(buy_request())
    broker.get_positions()
    broker.get_fills()
    held = broker.submit_order(buy_request(symbol="MSFT", metadata={"hold_for_review": True}))
    broker.cancel_order(held.broker_order_id)
    broker.disconnect()
    assert order.status is BrokerOrderStatus.FILLED


def test_connect_disconnect_do_not_mutate_database(db_path):
    broker, _, _ = make_broker(db_path, connect=False)

    conn = get_connection(db_path)
    before = conn.execute("SELECT cash FROM account_state WHERE id = 1").fetchone()
    conn.close()

    broker.connect()
    broker.disconnect()
    broker.connect()

    conn = get_connection(db_path)
    after = conn.execute("SELECT cash FROM account_state WHERE id = 1").fetchone()
    conn.close()

    assert before["cash"] == after["cash"]


# ----------------------------------------------------------------------
# Account / positions (20-33)
# ----------------------------------------------------------------------

def test_empty_account(db_path):
    broker, _, _ = make_broker(db_path, starting_balance=5000.0)
    account = broker.get_account()

    assert account.cash == 5000.0
    assert account.equity == 5000.0
    assert account.market_value == 0


def test_account_with_one_position(db_path):
    broker, _, _ = make_broker(db_path)
    broker.submit_order(buy_request())

    account = broker.get_account()
    assert account.market_value > 0
    assert account.cash < 10000.0


def test_account_cash(db_path):
    broker, _, _ = make_broker(db_path, commission=0.0)
    broker.submit_order(buy_request(quantity=10, limit_price=100.0))
    assert broker.get_account().cash == pytest.approx(9000.0)


def test_account_reserved_cash_is_zero(db_path):
    """PaperTradingService never holds cash aside pre-fill (only FILLED
    orders debit cash), so reserved_cash is always 0 - documented, not a
    gap: there is nothing to reserve in this milestone."""
    broker, _, _ = make_broker(db_path)
    broker.submit_order(buy_request(metadata={"hold_for_review": True}))
    assert broker.get_account().reserved_cash == 0.0


def test_account_buying_power_formula(db_path):
    broker, _, _ = make_broker(db_path)
    account = broker.get_account()
    assert account.buying_power == max(account.cash - account.reserved_cash, 0.0)


def test_account_market_value(db_path):
    broker, _, _ = make_broker(db_path, commission=0.0)
    broker.submit_order(buy_request(quantity=10, limit_price=100.0))
    assert broker.get_account().market_value == pytest.approx(1000.0)


def test_account_equity(db_path):
    broker, _, _ = make_broker(db_path, commission=0.0)
    broker.submit_order(buy_request(quantity=10, limit_price=100.0))
    account = broker.get_account()
    assert account.equity == pytest.approx(account.cash + account.market_value)


def test_account_realised_pnl(db_path):
    broker, paper, _ = make_broker(db_path, commission=0.0)
    broker.submit_order(buy_request(quantity=10, limit_price=100.0))
    paper.close_position("AAPL", price=110.0)
    assert broker.get_account().realised_pnl == pytest.approx(100.0)


def test_account_unrealised_pnl(db_path):
    broker, paper, _ = make_broker(db_path, commission=0.0)
    broker.submit_order(buy_request(quantity=10, limit_price=100.0))
    paper.update_positions({"AAPL": 120.0})
    assert broker.get_account().unrealised_pnl == pytest.approx(200.0)


def test_account_equity_not_double_counting_unrealised_pnl(db_path):
    broker, paper, _ = make_broker(db_path, commission=0.0)
    broker.submit_order(buy_request(quantity=10, limit_price=100.0))
    paper.update_positions({"AAPL": 150.0})

    account = broker.get_account()
    # equity must equal cash + market_value only, never
    # cash + market_value + unrealised_pnl (which would double-count it).
    assert account.equity == pytest.approx(account.cash + account.market_value)
    assert account.equity != pytest.approx(account.cash + account.market_value + account.unrealised_pnl)


def test_get_positions_one_position(db_path):
    broker, _, _ = make_broker(db_path)
    broker.submit_order(buy_request())
    positions = broker.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "AAPL"


def test_get_positions_multiple_positions(db_path):
    broker, _, _ = make_broker(db_path)
    broker.submit_order(buy_request(symbol="AAPL", quantity=5))
    broker.submit_order(buy_request(symbol="MSFT", quantity=5, limit_price=200.0))
    positions = broker.get_positions()
    assert {p.symbol for p in positions} == {"AAPL", "MSFT"}


def test_position_long_side_mapping(db_path):
    broker, _, _ = make_broker(db_path)
    broker.submit_order(buy_request())
    assert broker.get_positions()[0].side is BrokerOrderSide.BUY


def test_position_metadata_mapping(db_path):
    broker, _, _ = make_broker(db_path)
    broker.submit_order(buy_request(strategy_name="MyStrategy"))
    position = broker.get_positions()[0]
    assert position.strategy_name == "MyStrategy"
    assert position.strategy_mode == "single"


# ----------------------------------------------------------------------
# Orders (34-52)
# ----------------------------------------------------------------------

def test_submit_valid_market_order_fills(db_path):
    broker, _, _ = make_broker(db_path)
    order = broker.submit_order(buy_request())
    assert order.status is BrokerOrderStatus.FILLED
    assert order.filled_quantity == order.requested_quantity


def test_submit_held_order_stays_pending(db_path):
    broker, _, _ = make_broker(db_path)
    order = broker.submit_order(buy_request(metadata={"hold_for_review": True}))
    assert order.status is BrokerOrderStatus.PENDING
    assert order.filled_quantity == 0


def test_filled_order_mapping_fields(db_path):
    broker, _, _ = make_broker(db_path, commission=2.0)
    order = broker.submit_order(buy_request(quantity=10, limit_price=100.0))

    assert order.average_fill_price == pytest.approx(100.0)
    assert order.commission == pytest.approx(2.0)
    assert order.order_type is BrokerOrderType.MARKET
    assert order.created_at is not None
    assert order.updated_at is not None


def test_rejected_order_mapping(db_path):
    broker, _, _ = make_broker(db_path, starting_balance=100.0)
    order = broker.submit_order(buy_request(quantity=1, limit_price=999999.0))

    assert order.status is BrokerOrderStatus.REJECTED
    assert order.rejection_reason is not None
    assert order.filled_quantity == 0


def test_insufficient_cash_rejection_is_a_broker_order_not_an_exception(db_path):
    broker, _, _ = make_broker(db_path, starting_balance=50.0)
    order = broker.submit_order(buy_request(quantity=1, limit_price=999999.0))
    assert order.status is BrokerOrderStatus.REJECTED
    assert "cash" in order.rejection_reason.lower()


def test_invalid_quantity_raises_validation_error(db_path):
    broker, _, _ = make_broker(db_path)
    with pytest.raises(BrokerValidationError):
        broker.submit_order(buy_request(quantity=0))


def test_negative_quantity_raises_validation_error(db_path):
    broker, _, _ = make_broker(db_path)
    with pytest.raises(BrokerValidationError):
        broker.submit_order(buy_request(quantity=-5))


def test_unsupported_side_raises_unsupported_operation(db_path):
    broker, _, _ = make_broker(db_path)
    with pytest.raises(BrokerUnsupportedOperationError):
        broker.submit_order(buy_request(side=BrokerOrderSide.SELL))


def test_unsupported_order_type_raises_unsupported_operation(db_path):
    broker, _, _ = make_broker(db_path)
    with pytest.raises(BrokerUnsupportedOperationError):
        broker.submit_order(buy_request(order_type=BrokerOrderType.LIMIT))


def test_missing_reference_price_raises_validation_error(db_path):
    broker, _, _ = make_broker(db_path)
    with pytest.raises(BrokerValidationError):
        broker.submit_order(buy_request(limit_price=None))


def test_stop_loss_and_take_profit_on_filled_order_result(db_path):
    broker, paper, _ = make_broker(db_path)
    broker.submit_order(buy_request(stop_loss=90.0, take_profit=120.0))
    positions = paper.get_positions()
    assert positions[0].stop_loss == 90.0
    assert positions[0].take_profit == 120.0


def test_client_order_id_propagation(db_path):
    broker, _, _ = make_broker(db_path)
    order = broker.submit_order(buy_request(client_order_id="my-client-id-1"))
    assert order.client_order_id == "my-client-id-1"

    refetched = broker.get_order(order.broker_order_id)
    assert refetched.client_order_id == "my-client-id-1"


def test_strategy_metadata_propagation(db_path):
    broker, _, _ = make_broker(db_path)
    order = broker.submit_order(buy_request(strategy_name="Momentum"))
    assert order.metadata.get("strategy_name") == "Momentum"


def test_commission_mapping(db_path):
    broker, _, _ = make_broker(db_path, commission=3.5)
    order = broker.submit_order(buy_request())
    assert order.commission == pytest.approx(3.5)


def test_slippage_fill_price_mapping(db_path):
    broker, _, _ = make_broker(db_path, commission=0.0, slippage_percent=2.0)
    order = broker.submit_order(buy_request(limit_price=100.0))
    assert order.average_fill_price == pytest.approx(102.0)


def test_open_order_listing(db_path):
    broker, _, _ = make_broker(db_path)
    held = broker.submit_order(buy_request(symbol="AAPL", metadata={"hold_for_review": True}))
    broker.submit_order(buy_request(symbol="MSFT", limit_price=200.0))  # filled, not open

    open_orders = broker.get_open_orders()
    assert len(open_orders) == 1
    assert open_orders[0].broker_order_id == held.broker_order_id


def test_order_retrieval(db_path):
    broker, _, _ = make_broker(db_path)
    order = broker.submit_order(buy_request())

    fetched = broker.get_order(order.broker_order_id)
    assert fetched is not None
    assert fetched.broker_order_id == order.broker_order_id
    assert fetched.status is BrokerOrderStatus.FILLED


def test_missing_order_returns_none(db_path):
    broker, _, _ = make_broker(db_path)
    assert broker.get_order("999999") is None


def test_invalid_order_id_raises_validation_error(db_path):
    broker, _, _ = make_broker(db_path)
    with pytest.raises(BrokerValidationError):
        broker.get_order("not-a-number")


def test_order_status_mapping_pending_for_held_order(db_path):
    broker, _, _ = make_broker(db_path)
    order = broker.submit_order(buy_request(metadata={"hold_for_review": True}))
    assert order.status is BrokerOrderStatus.PENDING


def test_order_status_mapping_filled(db_path):
    broker, _, _ = make_broker(db_path)
    order = broker.submit_order(buy_request())
    assert order.status is BrokerOrderStatus.FILLED


def test_order_status_mapping_rejected(db_path):
    broker, _, _ = make_broker(db_path, starting_balance=1.0)
    order = broker.submit_order(buy_request(limit_price=999999.0))
    assert order.status is BrokerOrderStatus.REJECTED


def test_order_status_mapping_cancelled(db_path):
    broker, _, _ = make_broker(db_path)
    held = broker.submit_order(buy_request(metadata={"hold_for_review": True}))
    cancelled = broker.cancel_order(held.broker_order_id)
    assert cancelled.status is BrokerOrderStatus.CANCELLED


def test_repeated_get_order_does_not_mutate_state(db_path):
    broker, _, _ = make_broker(db_path)
    order = broker.submit_order(buy_request())

    first = broker.get_order(order.broker_order_id)
    second = broker.get_order(order.broker_order_id)

    assert first.updated_at == second.updated_at
    assert first.status == second.status


# ----------------------------------------------------------------------
# Cancellation (53-61)
# ----------------------------------------------------------------------

def test_cancel_pending_order(db_path):
    broker, _, _ = make_broker(db_path)
    held = broker.submit_order(buy_request(metadata={"hold_for_review": True}))
    cancelled = broker.cancel_order(held.broker_order_id)
    assert cancelled.status is BrokerOrderStatus.CANCELLED


def test_cancel_does_not_change_cash(db_path):
    """No cash is reserved pre-fill, so cancellation has nothing to
    release; cash must simply be unaffected."""
    broker, _, _ = make_broker(db_path)
    before = broker.get_account().cash
    held = broker.submit_order(buy_request(metadata={"hold_for_review": True}))
    broker.cancel_order(held.broker_order_id)
    after = broker.get_account().cash
    assert before == after


def test_cancellation_audit_event_created(db_path):
    broker, paper, _ = make_broker(db_path)
    held = broker.submit_order(buy_request(metadata={"hold_for_review": True}))
    broker.cancel_order(held.broker_order_id)

    conn = get_connection(paper.db_path)
    row = conn.execute(
        "SELECT * FROM paper_audit_events WHERE event_type = 'ORDER_CANCELLED' AND order_id = ?",
        (int(held.broker_order_id),),
    ).fetchone()
    conn.close()

    assert row is not None


def test_cancel_filled_order_rejected(db_path):
    broker, _, _ = make_broker(db_path)
    order = broker.submit_order(buy_request())
    with pytest.raises(BrokerCancellationError):
        broker.cancel_order(order.broker_order_id)


def test_cancel_rejected_order_rejected(db_path):
    broker, _, _ = make_broker(db_path, starting_balance=1.0)
    order = broker.submit_order(buy_request(limit_price=999999.0))
    with pytest.raises(BrokerCancellationError):
        broker.cancel_order(order.broker_order_id)


def test_cancel_unknown_order_raises_not_found(db_path):
    broker, _, _ = make_broker(db_path)
    with pytest.raises(BrokerOrderNotFoundError):
        broker.cancel_order("999999")


def test_repeated_cancellation_raises_on_second_attempt(db_path):
    broker, _, _ = make_broker(db_path)
    held = broker.submit_order(buy_request(metadata={"hold_for_review": True}))
    broker.cancel_order(held.broker_order_id)

    with pytest.raises(BrokerCancellationError):
        broker.cancel_order(held.broker_order_id)


def test_cancellation_does_not_affect_positions_or_trades(db_path):
    broker, paper, _ = make_broker(db_path)
    broker.submit_order(buy_request(symbol="AAPL"))
    held = broker.submit_order(buy_request(symbol="MSFT", limit_price=200.0, metadata={"hold_for_review": True}))

    positions_before = paper.get_positions()
    trades_before = paper.get_trades()

    broker.cancel_order(held.broker_order_id)

    assert paper.get_positions() == positions_before
    assert paper.get_trades() == trades_before


# ----------------------------------------------------------------------
# Fills (62-68)
# ----------------------------------------------------------------------

def test_get_all_fills(db_path):
    broker, _, _ = make_broker(db_path)
    broker.submit_order(buy_request(symbol="AAPL"))
    broker.submit_order(buy_request(symbol="MSFT", limit_price=200.0))

    fills = broker.get_fills()
    assert len(fills) == 2


def test_filter_fills_by_order(db_path):
    broker, _, _ = make_broker(db_path)
    order = broker.submit_order(buy_request(symbol="AAPL"))
    broker.submit_order(buy_request(symbol="MSFT", limit_price=200.0))

    fills = broker.get_fills(order_id=order.broker_order_id)
    assert len(fills) == 1
    assert fills[0].symbol == "AAPL"


def test_fill_quantity(db_path):
    broker, _, _ = make_broker(db_path)
    broker.submit_order(buy_request(quantity=7))
    fills = broker.get_fills()
    assert fills[0].quantity == 7


def test_fill_price(db_path):
    broker, _, _ = make_broker(db_path, commission=0.0, slippage_percent=0.0)
    broker.submit_order(buy_request(limit_price=150.0))
    fills = broker.get_fills()
    assert fills[0].fill_price == pytest.approx(150.0)


def test_fill_commission(db_path):
    broker, _, _ = make_broker(db_path, commission=4.25)
    broker.submit_order(buy_request())
    fills = broker.get_fills()
    assert fills[0].commission == pytest.approx(4.25)


def test_fills_chronological_ordering(db_path):
    broker, _, _ = make_broker(db_path)
    broker.submit_order(buy_request(symbol="AAPL"))
    broker.submit_order(buy_request(symbol="MSFT", limit_price=200.0))
    broker.submit_order(buy_request(symbol="TSLA", limit_price=300.0))

    fills = broker.get_fills()
    ids = [int(f.fill_id) for f in fills]
    assert ids == sorted(ids)


def test_fills_limit_handling(db_path):
    broker, _, _ = make_broker(db_path)
    broker.submit_order(buy_request(symbol="AAPL"))
    broker.submit_order(buy_request(symbol="MSFT", limit_price=200.0))
    broker.submit_order(buy_request(symbol="TSLA", limit_price=300.0))

    fills = broker.get_fills(limit=2)
    assert len(fills) == 2
    # limit returns the most recent N, still chronological
    assert fills[-1].symbol == "TSLA"


# ----------------------------------------------------------------------
# Isolation / safety (69-78)
# ----------------------------------------------------------------------

def test_uses_temporary_database_only(db_path):
    assert db_path.endswith("paper_broker_test.db")
    assert "data/trading_platform.db" not in db_path


def test_runtime_mode_live_remains_disabled():
    from core.runtime.router import RuntimeRouter
    from core.runtime.context import RuntimeContext
    from core.runtime.exceptions import LiveModeDisabledError
    import logging

    router = RuntimeRouter()
    context = RuntimeContext(settings={}, mode=RuntimeMode.LIVE, logger=logging.getLogger("test"))

    with pytest.raises(LiveModeDisabledError):
        router.route(context)


def test_no_direct_sql_in_paper_broker_module():
    import inspect
    from core.broker import paper_broker as module

    source = inspect.getsource(module)
    assert "sqlite3" not in source
    assert "get_connection(" not in source
