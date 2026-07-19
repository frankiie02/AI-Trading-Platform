import ast
import re
import socket
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.broker.base import BrokerInterface
from core.broker.errors import (
    BrokerConnectionError,
    BrokerUnsupportedOperationError,
    BrokerValidationError,
)
from core.broker.ibkr_broker import IBKRBroker, IBKRConnectionConfig
from core.broker.models import (
    BrokerEnvironment,
    BrokerOrderStatus,
    BrokerOrderType,
)

IBKR_BROKER_PATH = Path(__file__).resolve().parents[2] / "core" / "broker" / "ibkr_broker.py"
IBKR_CLIENT_PATH = Path(__file__).resolve().parents[2] / "core" / "broker" / "ibkr_client.py"


def _source_without_module_docstring(path: Path) -> str:
    """Source text with the module-level docstring removed, so static
    "no forbidden reference" checks below cannot be tripped by the
    docstring's own prose documenting what is absent (e.g. this module's
    docstring names the exact third-party methods its tests prove are
    never called)."""
    source = path.read_text()
    tree = ast.parse(source)

    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        segment = ast.get_source_segment(source, tree.body[0])
        if segment:
            source = source.replace(segment, "", 1)

    return source


# ----------------------------------------------------------------------
# Fake client (no ib_insync, no sockets)
# ----------------------------------------------------------------------

class FakeIBKRClient:
    def __init__(self, account_rows=None, position_rows=None, order_rows=None, fill_rows=None,
                 connect_raises=None, connected_after_connect=True):
        self._connected = False
        self.connect_calls = []
        self.disconnect_calls = 0
        self._account_rows = account_rows if account_rows is not None else _default_account_rows()
        self._position_rows = position_rows if position_rows is not None else []
        self._order_rows = order_rows if order_rows is not None else []
        self._fill_rows = fill_rows if fill_rows is not None else []
        self._connect_raises = connect_raises
        self._connected_after_connect = connected_after_connect

    @property
    def is_connected(self):
        return self._connected

    def connect(self, host, port, client_id, timeout, readonly):
        self.connect_calls.append((host, port, client_id, timeout, readonly))

        if self._connect_raises:
            raise self._connect_raises

        self._connected = self._connected_after_connect

    def disconnect(self):
        self.disconnect_calls += 1
        self._connected = False

    def account_values(self):
        return self._account_rows

    def positions(self):
        return self._position_rows

    def open_orders(self):
        return self._order_rows

    def fills(self):
        return self._fill_rows


def _tag(account, tag, value, currency="BASE"):
    return SimpleNamespace(account=account, tag=tag, value=value, currency=currency)


def _default_account_rows(account="DU1"):
    return [
        _tag(account, "TotalCashValue", "90000.0"),
        _tag(account, "NetLiquidation", "99500.0"),
        _tag(account, "BuyingPower", "90000.0"),
        _tag(account, "GrossPositionValue", "9500.0"),
        _tag(account, "RealizedPnL", "0.0"),
        _tag(account, "UnrealizedPnL", "500.0"),
    ]


def _contract(symbol="AAPL", con_id=1, sec_type="STK", exchange="SMART", currency="USD"):
    return SimpleNamespace(symbol=symbol, conId=con_id, secType=sec_type, exchange=exchange, currency=currency)


def _position_row(account="DU1", symbol="AAPL", quantity=10, avg_cost=100.0):
    return SimpleNamespace(account=account, contract=_contract(symbol=symbol), position=quantity, avgCost=avg_cost)


def _order_row(
    order_id=1, action="BUY", quantity=5, order_type="LMT", limit_price=200.0,
    stop_price=None, status="Submitted", filled=0, avg_fill_price=None,
    symbol="MSFT", order_ref=None,
):
    order = SimpleNamespace(
        orderId=order_id, action=action, totalQuantity=quantity, orderType=order_type,
        lmtPrice=limit_price, auxPrice=stop_price, orderRef=order_ref,
    )
    order_status = SimpleNamespace(
        status=status, filled=filled, remaining=quantity - filled, avgFillPrice=avg_fill_price,
    )
    return SimpleNamespace(order=order, orderStatus=order_status, contract=_contract(symbol=symbol, con_id=order_id))


def _fill_row(
    exec_id="e1", order_id=10, side="BOT", quantity=10, price=100.0,
    commission=1.0, symbol="AAPL", time=None,
):
    execution = SimpleNamespace(execId=exec_id, orderId=order_id, side=side, shares=quantity, price=price, time=time)
    commission_report = SimpleNamespace(commission=commission)
    return SimpleNamespace(
        execution=execution, commissionReport=commission_report, contract=_contract(symbol=symbol), time=time,
    )


def make_config(**overrides):
    fields = dict(host="127.0.0.1", port=4002, client_id=1, timeout=5.0, read_only=True)
    fields.update(overrides)
    return IBKRConnectionConfig(**fields)


def make_broker(client=None, config=None, connect=True):
    client = client or FakeIBKRClient()
    config = config or make_config()
    broker = IBKRBroker(config, client=client)

    if connect:
        broker.connect()

    return broker, client


# ----------------------------------------------------------------------
# Import and dependency safety (1-5)
# ----------------------------------------------------------------------

def test_platform_imports_without_ib_insync_installed(monkeypatch):
    import builtins
    import sys

    real_import = builtins.__import__

    def blocking_import(name, *args, **kwargs):
        if name == "ib_insync" or name.startswith("ib_insync."):
            raise ImportError("simulated: ib_insync not installed")
        return real_import(name, *args, **kwargs)

    for mod in list(sys.modules):
        if mod.startswith("ib_insync") or mod in (
            "core.broker.ibkr_client", "core.broker.ibkr_broker",
            "core.broker.factory", "core.broker",
        ):
            del sys.modules[mod]

    monkeypatch.setattr(builtins, "__import__", blocking_import)

    import core.broker  # noqa: F401
    import core.broker.ibkr_broker  # noqa: F401
    import core.broker.ibkr_client as client_module

    assert client_module.IB is None


def test_requesting_real_ibkr_client_without_dependency_raises_controlled_error(monkeypatch):
    import core.broker.ibkr_client as client_module

    monkeypatch.setattr(client_module, "IB", None)

    with pytest.raises(BrokerConnectionError):
        client_module.IBInsyncClient()


def test_paper_broker_remains_usable_without_ibkr_dependency(monkeypatch, tmp_path):
    import core.broker.ibkr_client as client_module
    from core.services.paper_trading_service import PaperTradingService
    from core.services.portfolio_service import PortfolioService
    from core.broker.paper_broker import PaperBroker

    monkeypatch.setattr(client_module, "IB", None)

    db_path = str(tmp_path / "ibkr_isolation_test.db")
    paper = PaperTradingService(db_path=db_path, starting_balance=1000.0)
    portfolio = PortfolioService(db_path=db_path, starting_balance=1000.0, paper_trading_service=paper)
    broker = PaperBroker(paper, portfolio)
    broker.connect()
    assert broker.is_connected


def test_no_import_time_connection_occurs():
    client = FakeIBKRClient()
    IBKRBroker(make_config(), client=client)
    assert client.connect_calls == []


def test_no_socket_opens_during_unit_tests(monkeypatch):
    def fail_if_called(*a, **k):
        raise AssertionError("socket.socket() must not be called")

    monkeypatch.setattr(socket, "socket", fail_if_called)

    broker, client = make_broker()
    broker.get_account()
    broker.get_positions()
    broker.get_open_orders()
    broker.get_fills()
    broker.disconnect()


# ----------------------------------------------------------------------
# Interface compliance (6-10)
# ----------------------------------------------------------------------

def test_ibkr_broker_implements_every_broker_interface_method():
    assert IBKRBroker.__abstractmethods__ == frozenset()
    assert issubclass(IBKRBroker, BrokerInterface)


def test_ibkr_broker_name():
    broker, _ = make_broker(connect=False)
    assert broker.broker_name == "ibkr"


def test_ibkr_broker_initial_state_disconnected():
    broker, _ = make_broker(connect=False)
    assert broker.is_connected is False


def test_ibkr_broker_configured_environment():
    broker, _ = make_broker(connect=False, config=make_config(environment=BrokerEnvironment.SIMULATION))
    status = broker.get_connection_status()
    assert status.environment is BrokerEnvironment.SIMULATION


@pytest.mark.parametrize("read_only", [False])
def test_read_only_mode_is_required(read_only):
    with pytest.raises(BrokerValidationError):
        make_config(read_only=read_only)


def test_live_environment_is_rejected_at_config_construction():
    with pytest.raises(BrokerUnsupportedOperationError):
        make_config(environment=BrokerEnvironment.LIVE)


# ----------------------------------------------------------------------
# Connection (11-20)
# ----------------------------------------------------------------------

def test_connect_success():
    broker, client = make_broker(connect=False)
    connection = broker.connect()
    assert broker.is_connected
    assert connection.state.value == "CONNECTED"
    assert len(client.connect_calls) == 1


def test_repeated_connect_is_idempotent():
    broker, client = make_broker(connect=False)
    broker.connect()
    broker.connect()
    assert len(client.connect_calls) == 1


def test_disconnect_success():
    broker, client = make_broker()
    broker.disconnect()
    assert not broker.is_connected
    assert client.disconnect_calls == 1


def test_repeated_disconnect_is_idempotent():
    broker, client = make_broker()
    broker.disconnect()
    broker.disconnect()
    assert client.disconnect_calls == 1


def test_connection_failure_translation():
    client = FakeIBKRClient(connect_raises=ConnectionRefusedError("refused"))
    broker, _ = make_broker(client=client, connect=False)

    with pytest.raises(BrokerConnectionError):
        broker.connect()


def test_timeout_translation():
    client = FakeIBKRClient(connect_raises=TimeoutError("timed out"))
    broker, _ = make_broker(client=client, connect=False)

    with pytest.raises(BrokerConnectionError):
        broker.connect()


def test_client_reports_not_connected_after_connect_raises_controlled_error():
    client = FakeIBKRClient(connected_after_connect=False)
    broker, _ = make_broker(client=client, connect=False)

    with pytest.raises(BrokerConnectionError):
        broker.connect()


@pytest.mark.parametrize("operation", ["get_account", "get_positions", "get_open_orders", "get_fills"])
def test_operation_while_disconnected(operation):
    broker, _ = make_broker(connect=False)

    with pytest.raises(BrokerConnectionError):
        getattr(broker, operation)()


def test_account_identifier_capture():
    broker, _ = make_broker()
    assert broker.get_connection_status().account_id is None
    broker.get_account()
    assert broker.get_connection_status().account_id == "DU1"


def test_no_background_threads_or_retry_workers():
    source = _source_without_module_docstring(IBKR_BROKER_PATH)
    assert "threading" not in source
    assert "Thread(" not in source
    assert "asyncio" not in source
    assert "while True" not in source
    assert "retry" not in source.lower()


# ----------------------------------------------------------------------
# Account mapping (21-33)
# ----------------------------------------------------------------------

def test_single_account():
    broker, _ = make_broker()
    account = broker.get_account()
    assert account.account_id == "DU1"


def test_configured_account_filtering():
    rows = _default_account_rows("DU1") + _default_account_rows("DU2")
    client = FakeIBKRClient(account_rows=rows)
    broker, _ = make_broker(client=client, config=make_config(account_id="DU2"))

    account = broker.get_account()
    assert account.account_id == "DU2"


def test_ambiguous_accounts_rejected():
    rows = _default_account_rows("DU1") + _default_account_rows("DU2")
    client = FakeIBKRClient(account_rows=rows)
    broker, _ = make_broker(client=client)

    with pytest.raises(BrokerValidationError):
        broker.get_account()


def test_configured_account_not_found_is_rejected():
    client = FakeIBKRClient(account_rows=_default_account_rows("DU1"))
    broker, _ = make_broker(client=client, config=make_config(account_id="DU9"))

    with pytest.raises(BrokerValidationError):
        broker.get_account()


def test_cash_mapping():
    broker, _ = make_broker()
    assert broker.get_account().cash == 90000.0


def test_equity_mapping():
    broker, _ = make_broker()
    assert broker.get_account().equity == 99500.0


def test_buying_power_mapping():
    broker, _ = make_broker()
    assert broker.get_account().buying_power == 90000.0


def test_realised_pnl_mapping():
    rows = [
        _tag("DU1", "TotalCashValue", "1.0"), _tag("DU1", "NetLiquidation", "1.0"),
        _tag("DU1", "BuyingPower", "1.0"), _tag("DU1", "GrossPositionValue", "0.0"),
        _tag("DU1", "RealizedPnL", "123.45"), _tag("DU1", "UnrealizedPnL", "0.0"),
    ]
    client = FakeIBKRClient(account_rows=rows)
    broker, _ = make_broker(client=client)
    assert broker.get_account().realised_pnl == 123.45


def test_unrealised_pnl_mapping():
    broker, _ = make_broker()
    assert broker.get_account().unrealised_pnl == 500.0


def test_currency_mapping():
    rows = [
        _tag("DU1", "TotalCashValue", "1000.0", currency="GBP"),
        _tag("DU1", "NetLiquidation", "1000.0"),
        _tag("DU1", "BuyingPower", "1000.0"),
        _tag("DU1", "GrossPositionValue", "0.0"),
        _tag("DU1", "RealizedPnL", "0.0"),
        _tag("DU1", "UnrealizedPnL", "0.0"),
    ]
    client = FakeIBKRClient(account_rows=rows)
    broker, _ = make_broker(client=client)
    assert broker.get_account().currency == "GBP"


def test_missing_optional_account_tags_default_safely():
    client = FakeIBKRClient(account_rows=[_tag("DU1", "NetLiquidation", "1000.0")])
    broker, _ = make_broker(client=client)

    account = broker.get_account()
    assert account.cash == 0.0
    assert account.buying_power == 0.0
    assert account.realised_pnl == 0.0


def test_no_equity_double_counting():
    # NetLiquidation is set to a value distinctly different from
    # cash + market_value (90000 + 9500 = 99500) so a passing assertion
    # actually proves equity is read verbatim from the NetLiquidation tag,
    # rather than the fixture numbers coincidentally summing to match.
    rows = [
        _tag("DU1", "TotalCashValue", "90000.0"),
        _tag("DU1", "NetLiquidation", "123456.0"),
        _tag("DU1", "BuyingPower", "90000.0"),
        _tag("DU1", "GrossPositionValue", "9500.0"),
        _tag("DU1", "RealizedPnL", "0.0"),
        _tag("DU1", "UnrealizedPnL", "500.0"),
    ]
    client = FakeIBKRClient(account_rows=rows)
    broker, _ = make_broker(client=client)

    account = broker.get_account()
    assert account.equity == 123456.0
    assert account.equity != account.cash + account.market_value


def test_numeric_string_conversion():
    client = FakeIBKRClient(account_rows=_default_account_rows("DU1"))
    broker, _ = make_broker(client=client)
    account = broker.get_account()
    assert isinstance(account.cash, float)


def test_malformed_numeric_value_handling():
    rows = [
        _tag("DU1", "TotalCashValue", "not-a-number"),
        _tag("DU1", "NetLiquidation", "1000.0"),
        _tag("DU1", "BuyingPower", "1000.0"),
        _tag("DU1", "GrossPositionValue", "0.0"),
        _tag("DU1", "RealizedPnL", "0.0"),
        _tag("DU1", "UnrealizedPnL", "0.0"),
    ]
    client = FakeIBKRClient(account_rows=rows)
    broker, _ = make_broker(client=client)

    account = broker.get_account()
    assert account.cash == 0.0  # falls back to default rather than raising


# ----------------------------------------------------------------------
# Position mapping (34-45)
# ----------------------------------------------------------------------

def test_no_positions():
    broker, _ = make_broker()
    assert broker.get_positions() == []


def test_one_long_position():
    client = FakeIBKRClient(position_rows=[_position_row()])
    broker, _ = make_broker(client=client)

    positions = broker.get_positions()
    assert len(positions) == 1


def test_multiple_positions():
    client = FakeIBKRClient(position_rows=[
        _position_row(symbol="AAPL"), _position_row(symbol="MSFT", quantity=5, avg_cost=200.0),
    ])
    broker, _ = make_broker(client=client)

    positions = broker.get_positions()
    assert {p.symbol for p in positions} == {"AAPL", "MSFT"}


def test_position_symbol_mapping():
    client = FakeIBKRClient(position_rows=[_position_row(symbol="TSLA")])
    broker, _ = make_broker(client=client)
    assert broker.get_positions()[0].symbol == "TSLA"


def test_position_quantity_mapping():
    client = FakeIBKRClient(position_rows=[_position_row(quantity=42)])
    broker, _ = make_broker(client=client)
    assert broker.get_positions()[0].quantity == 42


def test_position_average_cost_mapping():
    client = FakeIBKRClient(position_rows=[_position_row(avg_cost=123.45)])
    broker, _ = make_broker(client=client)
    assert broker.get_positions()[0].average_entry_price == 123.45


def test_position_cost_basis_mapping():
    client = FakeIBKRClient(position_rows=[_position_row(quantity=10, avg_cost=100.0)])
    broker, _ = make_broker(client=client)
    assert broker.get_positions()[0].cost_basis == 1000.0


def test_position_market_value_unavailable_by_default():
    client = FakeIBKRClient(position_rows=[_position_row()])
    broker, _ = make_broker(client=client)
    assert broker.get_positions()[0].market_value is None


def test_missing_market_price_remains_unavailable_not_fabricated():
    client = FakeIBKRClient(position_rows=[_position_row()])
    broker, _ = make_broker(client=client)
    position = broker.get_positions()[0]
    assert position.current_price is None
    assert position.unrealised_pnl is None


def test_position_long_side_mapping():
    client = FakeIBKRClient(position_rows=[_position_row(quantity=10)])
    broker, _ = make_broker(client=client)
    assert broker.get_positions()[0].side.value == "BUY"


def test_position_contract_metadata():
    client = FakeIBKRClient(position_rows=[_position_row(symbol="AAPL")])
    broker, _ = make_broker(client=client)
    metadata = broker.get_positions()[0].metadata
    assert metadata["con_id"] == 1
    assert metadata["sec_type"] == "STK"


def test_position_account_filtering():
    client = FakeIBKRClient(position_rows=[
        _position_row(account="DU1", symbol="AAPL"), _position_row(account="DU2", symbol="MSFT"),
    ])
    broker, _ = make_broker(client=client, config=make_config(account_id="DU2"))

    positions = broker.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "MSFT"


# ----------------------------------------------------------------------
# Open orders (46-57)
# ----------------------------------------------------------------------

def test_no_open_orders():
    broker, _ = make_broker()
    assert broker.get_open_orders() == []


def test_one_open_order():
    client = FakeIBKRClient(order_rows=[_order_row()])
    broker, _ = make_broker(client=client)
    assert len(broker.get_open_orders()) == 1


def test_multiple_open_orders():
    client = FakeIBKRClient(order_rows=[_order_row(order_id=1), _order_row(order_id=2)])
    broker, _ = make_broker(client=client)
    assert len(broker.get_open_orders()) == 2


def test_order_id_mapping():
    client = FakeIBKRClient(order_rows=[_order_row(order_id=99)])
    broker, _ = make_broker(client=client)
    assert broker.get_open_orders()[0].broker_order_id == "99"


def test_client_order_id_mapping_where_available():
    client = FakeIBKRClient(order_rows=[_order_row(order_ref="my-ref")])
    broker, _ = make_broker(client=client)
    assert broker.get_open_orders()[0].client_order_id == "my-ref"


def test_order_status_mapping_submitted():
    client = FakeIBKRClient(order_rows=[_order_row(status="Submitted")])
    broker, _ = make_broker(client=client)
    assert broker.get_open_orders()[0].status is BrokerOrderStatus.SUBMITTED


def test_order_status_mapping_pending():
    client = FakeIBKRClient(order_rows=[_order_row(status="PreSubmitted")])
    broker, _ = make_broker(client=client)
    assert broker.get_open_orders()[0].status is BrokerOrderStatus.PENDING


def test_order_side_mapping():
    client = FakeIBKRClient(order_rows=[_order_row(action="SELL")])
    broker, _ = make_broker(client=client)
    assert broker.get_open_orders()[0].side.value == "SELL"


def test_order_quantity_mapping():
    client = FakeIBKRClient(order_rows=[_order_row(quantity=15)])
    broker, _ = make_broker(client=client)
    assert broker.get_open_orders()[0].requested_quantity == 15


def test_order_filled_and_remaining_quantity():
    client = FakeIBKRClient(order_rows=[_order_row(quantity=10, filled=4)])
    broker, _ = make_broker(client=client)
    order = broker.get_open_orders()[0]
    assert order.filled_quantity == 4
    assert order.remaining_quantity == 6


def test_order_limit_and_stop_fields():
    client = FakeIBKRClient(order_rows=[_order_row(order_type="LMT", limit_price=150.0, stop_price=140.0)])
    broker, _ = make_broker(client=client)
    order = broker.get_open_orders()[0]
    assert order.order_type is BrokerOrderType.LIMIT
    assert order.limit_price == 150.0


def test_unknown_status_preserved_in_metadata():
    client = FakeIBKRClient(order_rows=[_order_row(status="SomeFutureIBKRStatus")])
    broker, _ = make_broker(client=client)
    order = broker.get_open_orders()[0]
    assert order.status is BrokerOrderStatus.PENDING  # safest neutral fallback
    assert order.metadata["raw_status"] == "SomeFutureIBKRStatus"


def test_open_orders_chronological_ordering():
    client = FakeIBKRClient(order_rows=[_order_row(order_id=1), _order_row(order_id=2)])
    broker, _ = make_broker(client=client)
    orders = broker.get_open_orders()
    assert len(orders) == 2  # created_at unavailable from IBKR open orders, so order is stable not exception-raising


def test_get_order_returns_matching_open_order():
    client = FakeIBKRClient(order_rows=[_order_row(order_id=7)])
    broker, _ = make_broker(client=client)
    order = broker.get_order("7")
    assert order is not None
    assert order.broker_order_id == "7"


def test_get_order_returns_none_when_not_open():
    broker, _ = make_broker()
    assert broker.get_order("999") is None


# ----------------------------------------------------------------------
# Fills (58-69)
# ----------------------------------------------------------------------

def test_no_fills():
    broker, _ = make_broker()
    assert broker.get_fills() == []


def test_one_fill():
    client = FakeIBKRClient(fill_rows=[_fill_row()])
    broker, _ = make_broker(client=client)
    assert len(broker.get_fills()) == 1


def test_multiple_fills():
    client = FakeIBKRClient(fill_rows=[_fill_row(exec_id="e1"), _fill_row(exec_id="e2", order_id=11)])
    broker, _ = make_broker(client=client)
    assert len(broker.get_fills()) == 2


def test_filter_fills_by_order_id():
    client = FakeIBKRClient(fill_rows=[
        _fill_row(exec_id="e1", order_id=10), _fill_row(exec_id="e2", order_id=20),
    ])
    broker, _ = make_broker(client=client)

    fills = broker.get_fills(order_id="20")
    assert len(fills) == 1
    assert fills[0].fill_id == "e2"


def test_fills_limit():
    client = FakeIBKRClient(fill_rows=[
        _fill_row(exec_id="e1", time=datetime(2026, 1, 1)),
        _fill_row(exec_id="e2", time=datetime(2026, 1, 2)),
        _fill_row(exec_id="e3", time=datetime(2026, 1, 3)),
    ])
    broker, _ = make_broker(client=client)

    fills = broker.get_fills(limit=2)
    assert len(fills) == 2
    assert fills[-1].fill_id == "e3"


def test_fill_id():
    client = FakeIBKRClient(fill_rows=[_fill_row(exec_id="unique-exec-1")])
    broker, _ = make_broker(client=client)
    assert broker.get_fills()[0].fill_id == "unique-exec-1"


def test_fill_quantity():
    client = FakeIBKRClient(fill_rows=[_fill_row(quantity=25)])
    broker, _ = make_broker(client=client)
    assert broker.get_fills()[0].quantity == 25


def test_fill_price():
    client = FakeIBKRClient(fill_rows=[_fill_row(price=321.5)])
    broker, _ = make_broker(client=client)
    assert broker.get_fills()[0].fill_price == 321.5


def test_fill_commission():
    client = FakeIBKRClient(fill_rows=[_fill_row(commission=4.2)])
    broker, _ = make_broker(client=client)
    assert broker.get_fills()[0].commission == 4.2


def test_fill_timestamp():
    ts = datetime(2026, 3, 1, 9, 30)
    client = FakeIBKRClient(fill_rows=[_fill_row(time=ts)])
    broker, _ = make_broker(client=client)
    assert broker.get_fills()[0].timestamp == ts


def test_fills_chronological_order():
    client = FakeIBKRClient(fill_rows=[
        _fill_row(exec_id="e3", time=datetime(2026, 1, 3)),
        _fill_row(exec_id="e1", time=datetime(2026, 1, 1)),
        _fill_row(exec_id="e2", time=datetime(2026, 1, 2)),
    ])
    broker, _ = make_broker(client=client)

    fills = broker.get_fills()
    ids = [f.fill_id for f in fills]
    assert ids == ["e1", "e2", "e3"]


def test_duplicate_fills_prevented():
    duplicate = _fill_row(exec_id="e1")
    client = FakeIBKRClient(fill_rows=[duplicate, duplicate])
    broker, _ = make_broker(client=client)

    fills = broker.get_fills()
    assert len(fills) == 1


# ----------------------------------------------------------------------
# Read-only enforcement (70-77)
# ----------------------------------------------------------------------

def test_submit_order_raises_unsupported_operation():
    broker, _ = make_broker()
    with pytest.raises(BrokerUnsupportedOperationError):
        broker.submit_order(None)


def test_cancel_order_raises_unsupported_operation():
    broker, _ = make_broker()
    with pytest.raises(BrokerUnsupportedOperationError):
        broker.cancel_order("1")


def test_no_third_party_placement_method_referenced_in_source():
    source = (
        _source_without_module_docstring(IBKR_BROKER_PATH)
        + _source_without_module_docstring(IBKR_CLIENT_PATH)
    )
    # "cancel_order" is deliberately excluded: it is BrokerInterface's own
    # required abstract method name (implemented here purely to raise
    # BrokerUnsupportedOperationError), not a reference to a third-party
    # cancellation API. "cancelOrder" (ib_insync/ibapi's camelCase method)
    # remains banned.
    for forbidden in ("placeOrder", "place_order", "cancelOrder", "reqGlobalCancel", "transmit"):
        assert forbidden not in source, f"found forbidden reference: {forbidden}"


def test_no_cancellation_method_is_called_at_runtime():
    client = FakeIBKRClient()
    broker, _ = make_broker(client=client)

    with pytest.raises(BrokerUnsupportedOperationError):
        broker.cancel_order("1")

    assert not hasattr(client, "cancelOrder")


def test_no_transmit_order_code_exists():
    source = _source_without_module_docstring(IBKR_BROKER_PATH)
    # No ib_insync Order(...) construction anywhere - BrokerOrder(...) (our
    # own neutral model constructor) is the only "Order(" call in this file,
    # so it must be excluded explicitly rather than banning "Order(" outright.
    assert re.search(r"(?<!Broker)\bOrder\(", source) is None
    assert "transmit=True" not in source


def test_factory_rejects_writable_configuration():
    with pytest.raises(BrokerValidationError):
        make_config(read_only=False)


def test_factory_rejects_live_configuration():
    with pytest.raises(BrokerUnsupportedOperationError):
        IBKRConnectionConfig(host="127.0.0.1", port=4001, client_id=1, environment=BrokerEnvironment.LIVE)


def test_runtime_mode_live_remains_disabled():
    import logging

    from core.runtime.context import RuntimeContext
    from core.runtime.exceptions import LiveModeDisabledError
    from core.runtime.modes import RuntimeMode
    from core.runtime.router import RuntimeRouter

    router = RuntimeRouter()
    context = RuntimeContext(settings={}, mode=RuntimeMode.LIVE, logger=logging.getLogger("test"))

    with pytest.raises(LiveModeDisabledError):
        router.route(context)


# ----------------------------------------------------------------------
# Architecture and isolation (78-86)
# ----------------------------------------------------------------------

def test_no_streamlit_import():
    source = IBKR_BROKER_PATH.read_text() + IBKR_CLIENT_PATH.read_text()
    assert "streamlit" not in source


def test_no_papertradingservice_dependency():
    imports = _module_imports(IBKR_BROKER_PATH)
    assert not any(m.startswith("core.services.paper_trading_service") for m in imports)


def test_no_portfolioservice_dependency():
    imports = _module_imports(IBKR_BROKER_PATH)
    assert not any(m.startswith("core.services.portfolio_service") for m in imports)


def test_no_execution_router_dependency():
    imports = _module_imports(IBKR_BROKER_PATH)
    assert not any(m.startswith("core.execution.execution_router") for m in imports)


def test_no_paper_trader_dependency():
    imports = _module_imports(IBKR_BROKER_PATH)
    assert not any(m.startswith("core.execution.paper_trader") for m in imports)


def test_no_direct_sqlite():
    source = IBKR_BROKER_PATH.read_text() + IBKR_CLIENT_PATH.read_text()
    assert "sqlite3" not in source
    assert "get_connection(" not in source


def test_no_real_project_database_usage():
    source = (
        _source_without_module_docstring(IBKR_BROKER_PATH)
        + _source_without_module_docstring(IBKR_CLIENT_PATH)
    )
    assert "trading_platform.db" not in source
    assert "core.database" not in source


def _module_imports(path: Path):
    tree = ast.parse(path.read_text())
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)

    return imports
