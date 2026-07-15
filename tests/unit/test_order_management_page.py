import ast
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import core.services.paper_trading_service as paper_trading_service_module
from core.services.paper_trading_service import (
    ExitReason,
    InvalidOrderStateTransitionError,
    OrderStatus,
    PaperOrder,
    PaperPosition,
    PaperTrade,
    PositionNotFoundError,
)

PAGE_PATH = "pages/6_Order_Management.py"
PAGE_SOURCE_PATH = Path(__file__).resolve().parents[2] / PAGE_PATH

FORBIDDEN_MODULE_PREFIXES = (
    "core.execution.paper_trader",
    "core.execution.paper_orders_repository",
    "core.database",
)


def make_order(**overrides):
    fields = dict(
        order_id=1, symbol="AAPL", side="BUY", quantity=10, order_type="MARKET",
        requested_price=100.0, stop_loss=None, take_profit=None, strategy_name="Manual",
        strategy_mode="single", source_reference="manual", status=OrderStatus.VALIDATED.value,
        rejection_reason=None, fill_price=None, fill_timestamp=None, fees=0.0,
        created_at="now", updated_at="now",
    )
    fields.update(overrides)
    return PaperOrder(**fields)


def make_position(**overrides):
    fields = dict(
        symbol="AAPL", quantity=10, average_entry_price=100.0, current_price=105.0,
        market_value=1050.0, stop_loss=95.0, take_profit=120.0, unrealised_pnl=50.0,
        realised_pnl=0.0, opened_at="now", updated_at="now",
    )
    fields.update(overrides)
    return PaperPosition(**fields)


class FakePaperTradingService:
    instances = []
    orders = []
    positions = []
    submit_order_raises = None
    fill_order_raises = None
    cancel_order_raises = None
    close_position_raises = None
    close_position_result = None
    update_levels_raises = None

    def __init__(self, *args, **kwargs):
        self.submit_calls = []
        self.fill_calls = []
        self.cancel_calls = []
        self.close_calls = []
        self.update_levels_calls = []
        FakePaperTradingService.instances.append(self)

    def get_orders(self, status=None):
        return FakePaperTradingService.orders

    def get_positions(self):
        return FakePaperTradingService.positions

    def submit_order(self, order_id):
        self.submit_calls.append(order_id)
        if FakePaperTradingService.submit_order_raises:
            raise FakePaperTradingService.submit_order_raises

    def fill_order(self, order_id):
        self.fill_calls.append(order_id)
        if FakePaperTradingService.fill_order_raises:
            raise FakePaperTradingService.fill_order_raises

    def cancel_order(self, order_id):
        self.cancel_calls.append(order_id)
        if FakePaperTradingService.cancel_order_raises:
            raise FakePaperTradingService.cancel_order_raises

    def close_position(self, symbol, quantity=None, price=None, reason=ExitReason.MANUAL):
        self.close_calls.append((symbol, quantity, price, reason))
        if FakePaperTradingService.close_position_raises:
            raise FakePaperTradingService.close_position_raises
        return FakePaperTradingService.close_position_result or PaperTrade(
            trade_id=1, symbol=symbol, quantity=quantity or 1, entry_price=100.0,
            exit_price=price or 100.0, entry_timestamp="now", exit_timestamp="now",
            gross_pnl=10.0, fees=0.0, net_pnl=10.0, exit_reason=reason.value if hasattr(reason, "value") else reason,
        )

    def update_position_levels(self, symbol, stop_loss=None, take_profit=None):
        self.update_levels_calls.append((symbol, stop_loss, take_profit))
        if FakePaperTradingService.update_levels_raises:
            raise FakePaperTradingService.update_levels_raises


@pytest.fixture(autouse=True)
def isolate_page_collaborators(monkeypatch):
    FakePaperTradingService.instances = []
    FakePaperTradingService.orders = []
    FakePaperTradingService.positions = []
    FakePaperTradingService.submit_order_raises = None
    FakePaperTradingService.fill_order_raises = None
    FakePaperTradingService.cancel_order_raises = None
    FakePaperTradingService.close_position_raises = None
    FakePaperTradingService.close_position_result = None
    FakePaperTradingService.update_levels_raises = None

    monkeypatch.setattr(paper_trading_service_module, "PaperTradingService", FakePaperTradingService)

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
            f"6_Order_Management.py must not import '{module}'"
        )


def test_page_runs_without_exception():
    at = run_page()
    assert not at.exception


def test_no_orders_shows_info():
    at = run_page()
    assert any("No orders yet" in i.value for i in at.info)


def test_no_positions_shows_info():
    at = run_page()
    assert any("No open positions to manage" in i.value for i in at.info)


def test_cancellable_order_offers_review_controls():
    FakePaperTradingService.orders = [make_order(status=OrderStatus.VALIDATED.value)]

    at = run_page()

    assert any("Review Held Orders" in h.value for h in at.subheader)
    assert len(at.button) >= 2


def test_cancel_button_calls_service():
    FakePaperTradingService.orders = [make_order(status=OrderStatus.VALIDATED.value)]

    at = run_page()
    cancel_button = next(b for b in at.button if b.label == "Cancel Order")
    cancel_button.click().run(timeout=30)

    total_calls = sum(len(i.cancel_calls) for i in FakePaperTradingService.instances)
    assert total_calls == 1


def test_cancel_invalid_transition_shows_error():
    FakePaperTradingService.orders = [make_order(status=OrderStatus.VALIDATED.value)]
    FakePaperTradingService.cancel_order_raises = InvalidOrderStateTransitionError(
        "Cannot transition order from FILLED to CANCELLED."
    )

    at = run_page()
    cancel_button = next(b for b in at.button if b.label == "Cancel Order")
    cancel_button.click().run(timeout=30)

    assert not at.exception
    assert any("Cannot transition order" in e.value for e in at.error)


def test_fill_now_submits_and_fills_validated_order():
    FakePaperTradingService.orders = [make_order(status=OrderStatus.VALIDATED.value)]

    at = run_page()
    fill_button = next(b for b in at.button if b.label == "Fill Now")
    fill_button.click().run(timeout=30)

    total_submit = sum(len(i.submit_calls) for i in FakePaperTradingService.instances)
    total_fill = sum(len(i.fill_calls) for i in FakePaperTradingService.instances)
    assert total_submit == 1
    assert total_fill == 1


def test_close_position_calls_service():
    FakePaperTradingService.positions = [make_position()]

    at = run_page()
    close_button = next(b for b in at.button if b.label == "Close Full Position")
    close_button.click().run(timeout=30)

    total_calls = sum(len(i.close_calls) for i in FakePaperTradingService.instances)
    assert total_calls == 1


def test_close_position_not_found_shows_error():
    FakePaperTradingService.positions = [make_position()]
    FakePaperTradingService.close_position_raises = PositionNotFoundError("No open position for AAPL.")

    at = run_page()
    close_button = next(b for b in at.button if b.label == "Close Full Position")
    close_button.click().run(timeout=30)

    assert not at.exception
    assert any("No open position for AAPL" in e.value for e in at.error)


def test_update_levels_calls_service():
    FakePaperTradingService.positions = [make_position()]

    at = run_page()
    save_button = next(b for b in at.button if b.label == "Save Order Levels")
    save_button.click().run(timeout=30)

    total_calls = sum(len(i.update_levels_calls) for i in FakePaperTradingService.instances)
    assert total_calls == 1


def test_no_real_streamlit_server_is_started():
    at = run_page()
    assert at is not None
    assert not at.exception
