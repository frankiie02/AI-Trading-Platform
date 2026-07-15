import ast
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import core.market_data.yahoo_data as yahoo_data_module
import core.services.paper_trading_service as paper_trading_service_module
from core.services.paper_trading_service import PaperAccount, PaperPosition, PaperTrade

PAGE_PATH = "pages/2_Portfolio.py"
PAGE_SOURCE_PATH = Path(__file__).resolve().parents[2] / PAGE_PATH

FORBIDDEN_MODULE_PREFIXES = (
    "core.execution.paper_trader",
    "core.execution.paper_orders_repository",
    "core.portfolio.position_monitor",
    "core.database",
)


def make_account(**overrides):
    fields = dict(
        account_id="default", starting_balance=100000.0, cash=90000.0, equity=98000.0,
        realised_pnl=500.0, unrealised_pnl=-100.0, reserved_cash=0.0, buying_power=90000.0,
    )
    fields.update(overrides)
    return PaperAccount(**fields)


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
    account = None
    positions = []

    def __init__(self, *args, **kwargs):
        self.update_positions_calls = []
        self.check_exits_calls = []
        FakePaperTradingService.instances.append(self)

    def get_account(self):
        return FakePaperTradingService.account

    def get_positions(self):
        return FakePaperTradingService.positions

    def update_positions(self, price_map):
        self.update_positions_calls.append(price_map)

    def check_exits(self, price_map):
        self.check_exits_calls.append(price_map)
        return []


@pytest.fixture(autouse=True)
def isolate_page_collaborators(monkeypatch):
    FakePaperTradingService.instances = []
    FakePaperTradingService.account = make_account()
    FakePaperTradingService.positions = []

    monkeypatch.setattr(paper_trading_service_module, "PaperTradingService", FakePaperTradingService)
    monkeypatch.setattr(
        yahoo_data_module, "download_price_data", lambda **kwargs: pd.DataFrame({"Close": [111.0]})
    )

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
            f"2_Portfolio.py must not import '{module}'"
        )


def test_page_runs_without_exception():
    at = run_page()
    assert not at.exception


def test_account_metrics_render():
    at = run_page()
    values = [m.value for m in at.metric]
    assert any("90,000" in v for v in values)


def test_no_positions_shows_info():
    at = run_page()
    assert any("No open positions" in i.value for i in at.info)


def test_refresh_prices_calls_update_positions_and_reruns():
    FakePaperTradingService.positions = [make_position()]

    at = run_page()
    at.button[0].click().run(timeout=30)

    total_calls = sum(len(i.update_positions_calls) for i in FakePaperTradingService.instances)
    assert total_calls == 1


def test_refresh_prices_with_no_positions_shows_warning():
    at = run_page()
    at.button[0].click().run(timeout=30)

    assert not at.exception
    assert any("No open positions to refresh" in w.value for w in at.warning)


def test_no_real_streamlit_server_is_started():
    at = run_page()
    assert at is not None
    assert not at.exception
