import ast
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import core.services.paper_trading_service as paper_trading_service_module
from core.services.paper_trading_service import PaperTrade, PaperTradingServiceError

PAGE_PATH = "pages/3_Trade_History.py"
PAGE_SOURCE_PATH = Path(__file__).resolve().parents[2] / PAGE_PATH

FORBIDDEN_MODULE_PREFIXES = (
    "core.execution.paper_trader",
    "core.execution.paper_orders_repository",
    "core.database",
)


def make_trade(**overrides):
    fields = dict(
        trade_id=1, symbol="AAPL", quantity=10, entry_price=100.0, exit_price=110.0,
        entry_timestamp="now", exit_timestamp="now", gross_pnl=100.0, fees=0.0,
        net_pnl=100.0, exit_reason="MANUAL", strategy_name="EMA Trend",
    )
    fields.update(overrides)
    return PaperTrade(**fields)


class FakePaperTradingService:
    instances = []
    trades = []
    raises = None

    def __init__(self, *args, **kwargs):
        FakePaperTradingService.instances.append(self)

    def get_trades(self):
        if FakePaperTradingService.raises:
            raise FakePaperTradingService.raises
        return FakePaperTradingService.trades


@pytest.fixture(autouse=True)
def isolate_page_collaborators(monkeypatch):
    FakePaperTradingService.instances = []
    FakePaperTradingService.trades = []
    FakePaperTradingService.raises = None

    monkeypatch.setattr(paper_trading_service_module, "PaperTradingService", FakePaperTradingService)

    yield


def run_page():
    at = AppTest.from_file(PAGE_PATH)
    at.run(timeout=30)
    return at


def test_page_syntax_is_valid():
    ast.parse(PAGE_SOURCE_PATH.read_text())


def test_page_is_no_longer_empty():
    assert len(PAGE_SOURCE_PATH.read_text().strip()) > 0


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
            f"3_Trade_History.py must not import '{module}'"
        )


def test_page_is_read_only_no_button_widgets():
    """Trade History is specified as a thin read-only view."""
    at = run_page()
    assert len(at.button) == 0


def test_page_runs_without_exception():
    at = run_page()
    assert not at.exception


def test_no_trades_shows_info():
    at = run_page()
    assert any("No completed trades yet" in i.value for i in at.info)


def test_trades_render_in_table_and_summary():
    FakePaperTradingService.trades = [make_trade(net_pnl=100.0), make_trade(trade_id=2, net_pnl=-40.0)]

    at = run_page()

    assert not at.exception
    assert len(at.dataframe) == 1
    metric_values = [m.value for m in at.metric]
    assert any("2" == v for v in metric_values)


def test_controlled_error_is_displayed():
    FakePaperTradingService.raises = PaperTradingServiceError("db locked")

    at = run_page()

    assert not at.exception
    assert any("db locked" in e.value for e in at.error)


def test_no_real_streamlit_server_is_started():
    at = run_page()
    assert at is not None
    assert not at.exception
