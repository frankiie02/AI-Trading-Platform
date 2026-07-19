import ast
import dataclasses
from datetime import datetime
from pathlib import Path

import pytest

from core.broker.base import BrokerInterface
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
from core.services.paper_trading_service import PaperTradingService
from core.services.portfolio_service import PortfolioService

BASE_PATH = Path(__file__).resolve().parents[2] / "core" / "broker" / "base.py"


# ----------------------------------------------------------------------
# 1-2: ABC instantiation / conformance
# ----------------------------------------------------------------------

def test_broker_interface_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        BrokerInterface()


def test_broker_interface_is_an_abc_with_abstract_methods():
    tree = ast.parse(BASE_PATH.read_text())
    class_node = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "BrokerInterface"
    )
    method_names = {
        node.name for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    expected = {
        "broker_name", "is_connected", "connect", "disconnect",
        "get_connection_status", "get_account", "get_positions",
        "get_open_orders", "get_order", "submit_order", "cancel_order",
        "get_fills",
    }
    assert expected <= method_names


def test_paper_broker_satisfies_every_abstract_method(tmp_path):
    db_path = str(tmp_path / "models_test.db")
    paper = PaperTradingService(db_path=db_path, starting_balance=1000.0)
    portfolio = PortfolioService(db_path=db_path, starting_balance=1000.0, paper_trading_service=paper)

    broker = PaperBroker(paper, portfolio)
    assert isinstance(broker, BrokerInterface)

    # PaperBroker successfully constructing above already proves every
    # abstract method is implemented (Python refuses to instantiate a
    # subclass with any left over); assert it explicitly too.
    assert PaperBroker.__abstractmethods__ == frozenset()


def test_paper_broker_no_missing_methods():
    for name in (
        "broker_name", "is_connected", "connect", "disconnect",
        "get_connection_status", "get_account", "get_positions",
        "get_open_orders", "get_order", "submit_order", "cancel_order",
        "get_fills",
    ):
        assert hasattr(PaperBroker, name), f"PaperBroker missing {name}"


# ----------------------------------------------------------------------
# 3: enum stability
# ----------------------------------------------------------------------

def test_broker_environment_values():
    assert {e.value for e in BrokerEnvironment} == {"PAPER", "LIVE", "SIMULATION"}


def test_broker_connection_state_values():
    assert {e.value for e in BrokerConnectionState} == {"DISCONNECTED", "CONNECTED"}


def test_broker_order_side_values():
    assert {e.value for e in BrokerOrderSide} == {"BUY", "SELL"}


def test_broker_order_type_values():
    assert {e.value for e in BrokerOrderType} == {"MARKET", "LIMIT", "STOP"}


def test_broker_time_in_force_values():
    assert {e.value for e in BrokerTimeInForce} == {"DAY", "GTC"}


def test_broker_order_status_values():
    assert {e.value for e in BrokerOrderStatus} == {
        "PENDING", "SUBMITTED", "FILLED", "PARTIALLY_FILLED",
        "REJECTED", "CANCELLED", "EXPIRED",
    }


# ----------------------------------------------------------------------
# 4/6: BrokerOrderRequest normalisation (business validation lives in
# PaperBroker - covered in test_paper_broker.py)
# ----------------------------------------------------------------------

def test_order_request_normalises_symbol():
    request = BrokerOrderRequest(symbol="  aapl ", side=BrokerOrderSide.BUY, quantity=10)
    assert request.symbol == "AAPL"


def test_order_request_coerces_enum_values_from_strings():
    request = BrokerOrderRequest(symbol="AAPL", side="BUY", quantity=10, order_type="MARKET", time_in_force="GTC")
    assert request.side is BrokerOrderSide.BUY
    assert request.order_type is BrokerOrderType.MARKET
    assert request.time_in_force is BrokerTimeInForce.GTC


def test_order_request_defaults():
    request = BrokerOrderRequest(symbol="AAPL", side=BrokerOrderSide.BUY, quantity=10)
    assert request.order_type is BrokerOrderType.MARKET
    assert request.time_in_force is BrokerTimeInForce.DAY
    assert request.metadata == {}


# ----------------------------------------------------------------------
# 9: remaining quantity calculation
# ----------------------------------------------------------------------

def _make_order(**overrides):
    fields = dict(
        broker_order_id="1", client_order_id=None, symbol="AAPL", side=BrokerOrderSide.BUY,
        requested_quantity=10, filled_quantity=0, order_type=BrokerOrderType.MARKET,
        status=BrokerOrderStatus.PENDING,
    )
    fields.update(overrides)
    return BrokerOrder(**fields)


def test_remaining_quantity_when_unfilled():
    order = _make_order(requested_quantity=10, filled_quantity=0)
    assert order.remaining_quantity == 10


def test_remaining_quantity_when_fully_filled():
    order = _make_order(requested_quantity=10, filled_quantity=10)
    assert order.remaining_quantity == 0


def test_remaining_quantity_never_negative():
    order = _make_order(requested_quantity=10, filled_quantity=15)
    assert order.remaining_quantity == 0


# ----------------------------------------------------------------------
# 10: typed timestamps
# ----------------------------------------------------------------------

def test_broker_order_timestamps_are_datetime_typed():
    now = datetime(2026, 1, 1, 12, 0, 0)
    order = _make_order(created_at=now, updated_at=now)
    assert isinstance(order.created_at, datetime)
    assert isinstance(order.updated_at, datetime)


def test_broker_connection_timestamp_is_datetime_typed():
    connection = BrokerConnection(
        broker_name="paper", state=BrokerConnectionState.CONNECTED,
        environment=BrokerEnvironment.PAPER, connected_at=datetime(2026, 1, 1),
    )
    assert isinstance(connection.connected_at, datetime)


def test_broker_account_timestamp_is_optional_and_datetime_typed():
    account = BrokerAccount(
        account_id="default", currency="USD", cash=100.0, reserved_cash=0.0,
        buying_power=100.0, market_value=0.0, equity=100.0, realised_pnl=0.0,
        unrealised_pnl=0.0, total_pnl=0.0, status="ACTIVE", timestamp=datetime(2026, 1, 1),
    )
    assert isinstance(account.timestamp, datetime)

    account_without_timestamp = BrokerAccount(
        account_id="default", currency="USD", cash=100.0, reserved_cash=0.0,
        buying_power=100.0, market_value=0.0, equity=100.0, realised_pnl=0.0,
        unrealised_pnl=0.0, total_pnl=0.0, status="ACTIVE",
    )
    assert account_without_timestamp.timestamp is None


# ----------------------------------------------------------------------
# 11: model serialization/conversion (dataclasses.asdict, the project's
# existing ambient serialization mechanism for typed models)
# ----------------------------------------------------------------------

def test_broker_order_serializes_via_dataclasses_asdict():
    order = _make_order(created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1))
    as_dict = dataclasses.asdict(order)

    assert as_dict["broker_order_id"] == "1"
    assert as_dict["side"] == BrokerOrderSide.BUY
    assert as_dict["requested_quantity"] == 10


def test_broker_fill_serializes_via_dataclasses_asdict():
    fill = BrokerFill(
        fill_id="1", broker_order_id="1", symbol="AAPL", side=BrokerOrderSide.BUY,
        quantity=10, fill_price=100.0, commission=1.0, timestamp=datetime(2026, 1, 1),
    )
    as_dict = dataclasses.asdict(fill)
    assert as_dict["symbol"] == "AAPL"
    assert as_dict["quantity"] == 10


def test_broker_position_serializes_via_dataclasses_asdict():
    position = BrokerPosition(
        symbol="AAPL", quantity=10, average_entry_price=100.0, current_price=105.0,
        cost_basis=1000.0, market_value=1050.0, unrealised_pnl=50.0, realised_pnl=0.0,
        side=BrokerOrderSide.BUY,
    )
    as_dict = dataclasses.asdict(position)
    assert as_dict["market_value"] == 1050.0


# ----------------------------------------------------------------------
# Import-boundary / no-broker-SDK / no-Streamlit guards for the whole package
# ----------------------------------------------------------------------

BROKER_PACKAGE_FILES = [
    "core/broker/__init__.py",
    "core/broker/base.py",
    "core/broker/models.py",
    "core/broker/errors.py",
    "core/broker/paper_broker.py",
    "core/broker/factory.py",
]

# These specific files must remain entirely IBKR/ib_insync-free, proving
# PaperBroker's isolation from the (now-present) IBKR adapter. factory.py
# and __init__.py are intentionally excluded here - they legitimately
# reference IBKRBroker/create_ibkr_broker/ib_insync in prose and imports
# now that the IBKR milestone exists (covered by test_ibkr_broker.py
# instead).
PAPER_ONLY_FILES = [
    "core/broker/base.py",
    "core/broker/models.py",
    "core/broker/errors.py",
    "core/broker/paper_broker.py",
]

FORBIDDEN_IMPORT_PREFIXES = (
    "streamlit",
    "pages",
    "dashboard",
    "ib_insync",
    "core.execution.execution_router",
    "core.execution.paper_trader",
)


def _imports(path: Path):
    tree = ast.parse(path.read_text())
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


@pytest.mark.parametrize("relative_path", BROKER_PACKAGE_FILES)
def test_broker_package_has_no_forbidden_imports(relative_path):
    path = Path(__file__).resolve().parents[2] / relative_path
    imports = _imports(path)

    for module in imports:
        for forbidden in FORBIDDEN_IMPORT_PREFIXES:
            assert not module.startswith(forbidden), f"{relative_path} imports forbidden module: {module}"


@pytest.mark.parametrize("relative_path", BROKER_PACKAGE_FILES)
def test_broker_package_source_never_mentions_legacy_execution_or_sql(relative_path):
    path = Path(__file__).resolve().parents[2] / relative_path
    source = path.read_text()

    assert "ExecutionRouter" not in source
    assert "PaperTrader(" not in source
    assert "sqlite3" not in source
    assert "cursor.execute(" not in source


@pytest.mark.parametrize("relative_path", PAPER_ONLY_FILES)
def test_paper_only_files_never_mention_ibkr_or_broker_sdks(relative_path):
    """base.py/models.py/errors.py/paper_broker.py must stay entirely
    IBKR-free, proving PaperBroker's isolation from the IBKR adapter that
    now exists alongside it (ibkr_broker.py/ibkr_client.py are covered by
    test_ibkr_broker.py instead, since referencing ib_insync there is the
    whole point of those two files)."""
    path = Path(__file__).resolve().parents[2] / relative_path
    source = path.read_text()

    assert "ib_insync" not in source
    assert "ibapi" not in source


def test_paper_broker_source_has_no_direct_sql():
    path = Path(__file__).resolve().parents[2] / "core" / "broker" / "paper_broker.py"
    source = path.read_text()
    assert "get_connection(" not in source
    assert "conn.execute(" not in source
