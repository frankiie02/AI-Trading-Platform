import ast
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import core.execution.trade_queue as trade_queue_module
import core.services.paper_trading_service as paper_trading_service_module
from core.services.paper_trading_service import (
    InvalidPaperOrderError,
    OrderStatus,
    PaperAccount,
    PaperOrder,
    PaperTradingResult,
    PaperTradingServiceError,
)

PAGE_PATH = "pages/4_Paper_Trading.py"
PAGE_SOURCE_PATH = Path(__file__).resolve().parents[2] / PAGE_PATH

FORBIDDEN_MODULE_PREFIXES = (
    "core.execution.paper_trader",
    "core.execution.paper_orders_repository",
    "core.database",
)


def make_account(**overrides):
    fields = dict(
        account_id="default", starting_balance=100000.0, cash=90000.0, equity=98000.0,
        realised_pnl=500.0, unrealised_pnl=-100.0, reserved_cash=0.0, buying_power=90000.0,
    )
    fields.update(overrides)
    return PaperAccount(**fields)


def make_order(**overrides):
    fields = dict(
        order_id=1, symbol="AAPL", side="BUY", quantity=10, order_type="MARKET",
        requested_price=100.0, stop_loss=None, take_profit=None, strategy_name="Manual",
        strategy_mode="single", source_reference="manual", status=OrderStatus.FILLED.value,
        rejection_reason=None, fill_price=101.0, fill_timestamp="now", fees=0.0,
        created_at="now", updated_at="now",
    )
    fields.update(overrides)
    return PaperOrder(**fields)


class FakePaperTradingService:
    instances = []
    account = None
    positions = []
    orders = []
    create_order_raises = None
    process_queue_result = None
    process_queue_raises = None

    def __init__(self, *args, **kwargs):
        self.create_order_calls = []
        self.process_queue_calls = []
        FakePaperTradingService.instances.append(self)

    def get_account(self):
        return FakePaperTradingService.account

    def get_positions(self):
        return FakePaperTradingService.positions

    def get_orders(self, status=None):
        return FakePaperTradingService.orders

    def create_order_from_decision(self, decision, source_reference=None, auto_fill=True, quantity=None):
        self.create_order_calls.append((decision, source_reference, auto_fill))

        if FakePaperTradingService.create_order_raises:
            raise FakePaperTradingService.create_order_raises

        return make_order(symbol=decision.symbol)

    def process_queue(self, enabled=False, queue_ids=None, auto_fill=True, limit=None):
        self.process_queue_calls.append((enabled, queue_ids, auto_fill))

        if FakePaperTradingService.process_queue_raises:
            raise FakePaperTradingService.process_queue_raises

        return FakePaperTradingService.process_queue_result or PaperTradingResult(
            account=FakePaperTradingService.account
        )


@pytest.fixture(autouse=True)
def isolate_page_collaborators(monkeypatch):
    FakePaperTradingService.instances = []
    FakePaperTradingService.account = make_account()
    FakePaperTradingService.positions = []
    FakePaperTradingService.orders = []
    FakePaperTradingService.create_order_raises = None
    FakePaperTradingService.process_queue_result = None
    FakePaperTradingService.process_queue_raises = None

    monkeypatch.setattr(paper_trading_service_module, "PaperTradingService", FakePaperTradingService)
    monkeypatch.setattr(trade_queue_module, "get_pending_trades", lambda db_path=None: pd.DataFrame())

    yield


def run_page():
    at = AppTest.from_file(PAGE_PATH)
    at.run(timeout=30)
    return at


def test_page_syntax_is_valid():
    ast.parse(PAGE_SOURCE_PATH.read_text())


def test_page_does_not_import_forbidden_modules():
    tree = ast.parse(PAGE_SOURCE_PATH.read_text())
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)

    for module in imports:
        assert not module.startswith(FORBIDDEN_MODULE_PREFIXES), (
            f"4_Paper_Trading.py must not import '{module}'"
        )


def test_page_imports_paper_trading_service():
    source = PAGE_SOURCE_PATH.read_text()
    assert "PaperTradingService" in source


def test_page_runs_without_exception():
    at = run_page()
    assert not at.exception


def test_account_metrics_render():
    at = run_page()
    values = [m.value for m in at.metric]
    assert any("90,000" in v for v in values)


def test_place_trade_button_calls_service():
    at = run_page()
    at.button[0].click().run(timeout=30)

    total_calls = sum(len(i.create_order_calls) for i in FakePaperTradingService.instances)
    assert total_calls == 1


def test_rejected_order_shows_error():
    FakePaperTradingService.create_order_raises = InvalidPaperOrderError("Quantity must be greater than zero.")

    at = run_page()
    at.button[0].click().run(timeout=30)

    assert not at.exception
    assert any("Quantity must be greater than zero" in e.value for e in at.error)


def test_generic_service_error_is_caught_and_displayed():
    FakePaperTradingService.create_order_raises = PaperTradingServiceError("db locked")

    at = run_page()
    at.button[0].click().run(timeout=30)

    assert not at.exception
    assert any("db locked" in e.value for e in at.error)


def test_no_queued_signals_shows_info():
    at = run_page()
    assert any("No queued signals pending" in i.value for i in at.info)


def test_open_positions_empty_shows_info():
    at = run_page()
    assert any("No open paper positions yet" in i.value for i in at.info)


def test_no_real_streamlit_server_is_started():
    at = run_page()
    assert at is not None
    assert not at.exception
