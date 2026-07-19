import ast
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import core.market_data.yahoo_data as yahoo_data_module
import core.services.paper_trading_service as paper_trading_service_module
import core.services.portfolio_service as portfolio_service_module
from core.services.paper_trading_service import ReconciliationResult
from core.services.portfolio_service import (
    PortfolioAnalysis,
    PortfolioPerformance,
    PortfolioPosition,
    PortfolioSnapshot,
    PortfolioSummary,
)

PAGE_PATH = "pages/2_Portfolio.py"
PAGE_SOURCE_PATH = Path(__file__).resolve().parents[2] / PAGE_PATH

FORBIDDEN_MODULE_PREFIXES = (
    "core.execution.paper_trader",
    "core.execution.paper_orders_repository",
    "core.portfolio.position_monitor",
    "core.portfolio.portfolio_repository",
    "core.database",
)

# Patterns that would indicate the page is computing portfolio statistics
# itself again, rather than reading them from PortfolioAnalysis.
FORBIDDEN_SOURCE_SNIPPETS = (
    ".mean()",
    ".max()",
    "average_position =",
    "largest_position =",
)


def make_summary(**overrides):
    fields = dict(
        starting_capital=100000.0, cash=90000.0, reserved_cash=0.0, invested_capital=9000.0,
        market_value=9500.0, equity=99500.0, realised_pnl=500.0, unrealised_pnl=500.0,
        total_pnl=1000.0, total_return_pct=1.0, gross_exposure_pct=9.55, net_exposure_pct=9.55,
        cash_pct=90.45, position_count=1, largest_position_pct=9.55, average_position_value=9500.0,
    )
    fields.update(overrides)
    return PortfolioSummary(**fields)


def make_position(**overrides):
    fields = dict(
        symbol="AAPL", quantity=10, average_entry_price=100.0, current_price=105.0,
        cost_basis=1000.0, market_value=1050.0, unrealised_pnl=50.0, unrealised_return_pct=5.0,
        realised_pnl=0.0, portfolio_weight_pct=10.5, stop_loss=None, take_profit=None,
        opened_at="now",
    )
    fields.update(overrides)
    return PortfolioPosition(**fields)


def make_performance(**overrides):
    fields = dict()
    fields.update(overrides)
    return PortfolioPerformance(**fields)


def make_analysis(**overrides):
    fields = dict(
        summary=make_summary(),
        positions=[],
        performance=make_performance(),
        allocation=[],
        snapshots=[],
        warnings=[],
        reconciliation=ReconciliationResult(balanced=True, differences={}),
    )
    fields.update(overrides)
    return PortfolioAnalysis(**fields)


class FakePaperTradingService:
    instances = []

    def __init__(self, *args, **kwargs):
        self.update_positions_calls = []
        self.check_exits_calls = []
        FakePaperTradingService.instances.append(self)

    def update_positions(self, price_map):
        self.update_positions_calls.append(price_map)

    def check_exits(self, price_map):
        self.check_exits_calls.append(price_map)
        return []


class FakePortfolioService:
    instances = []
    positions = []
    analysis = None
    analysis_raises = None
    create_snapshot_result = None
    create_snapshot_raises = None

    def __init__(self, *args, **kwargs):
        self.create_snapshot_calls = 0
        FakePortfolioService.instances.append(self)

    def get_positions(self):
        return FakePortfolioService.positions

    def get_analysis(self, snapshot_limit=None):
        if FakePortfolioService.analysis_raises:
            raise FakePortfolioService.analysis_raises

        return FakePortfolioService.analysis or make_analysis()

    def create_snapshot(self):
        self.create_snapshot_calls += 1

        if FakePortfolioService.create_snapshot_raises:
            raise FakePortfolioService.create_snapshot_raises

        return FakePortfolioService.create_snapshot_result or PortfolioSnapshot(
            snapshot_id=1, timestamp="now", cash=90000.0, market_value=9500.0,
            equity=99500.0, realised_pnl=500.0, unrealised_pnl=500.0,
            gross_exposure_pct=9.55, position_count=1,
        )


@pytest.fixture(autouse=True)
def isolate_page_collaborators(monkeypatch):
    FakePaperTradingService.instances = []
    FakePortfolioService.instances = []
    FakePortfolioService.positions = []
    FakePortfolioService.analysis = make_analysis()
    FakePortfolioService.analysis_raises = None
    FakePortfolioService.create_snapshot_result = None
    FakePortfolioService.create_snapshot_raises = None

    monkeypatch.setattr(paper_trading_service_module, "PaperTradingService", FakePaperTradingService)
    monkeypatch.setattr(portfolio_service_module, "PortfolioService", FakePortfolioService)
    monkeypatch.setattr(
        yahoo_data_module, "download_price_data", lambda **kwargs: pd.DataFrame({"Close": [111.0]})
    )

    yield


def run_page():
    at = AppTest.from_file(PAGE_PATH)
    at.run(timeout=30)
    return at


# ---------------------------------------------------------------------------
# Static checks
# ---------------------------------------------------------------------------

def test_page_syntax_is_valid():
    ast.parse(PAGE_SOURCE_PATH.read_text())


def test_page_imports_portfolio_service():
    source = PAGE_SOURCE_PATH.read_text()
    assert "PortfolioService" in source


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


def test_page_no_longer_computes_statistics_itself():
    source = PAGE_SOURCE_PATH.read_text()

    for snippet in FORBIDDEN_SOURCE_SNIPPETS:
        assert snippet not in source, (
            f"2_Portfolio.py must not compute statistics itself (found '{snippet}')"
        )


def test_page_contains_no_direct_sql():
    source = PAGE_SOURCE_PATH.read_text()
    assert "sqlite3" not in source
    assert "cursor.execute" not in source
    assert "conn.execute" not in source
    assert "get_connection" not in source


def test_page_never_mentions_paper_trader():
    source = PAGE_SOURCE_PATH.read_text()
    assert "PaperTrader" not in source


# ---------------------------------------------------------------------------
# Behavioural checks
# ---------------------------------------------------------------------------

def test_page_runs_without_exception():
    at = run_page()
    assert not at.exception


def test_summary_metrics_render():
    at = run_page()
    values = [m.value for m in at.metric]
    assert any("90,000" in v for v in values)
    assert any("99,500" in v for v in values)


def test_no_positions_shows_info():
    at = run_page()
    assert any("No open positions" in i.value for i in at.info)


def test_positions_render():
    FakePortfolioService.analysis = make_analysis(positions=[make_position()])

    at = run_page()

    assert not at.exception
    assert len(at.dataframe) >= 1


def test_allocation_renders():
    FakePortfolioService.analysis = make_analysis(
        positions=[make_position()],
        allocation=[{"symbol": "AAPL", "market_value": 1050.0, "weight_pct": 10.5}],
    )

    at = run_page()

    assert not at.exception
    assert not any("No allocation to display" in i.value for i in at.info)


def test_equity_curve_renders_when_snapshots_exist():
    performance = make_performance(
        equity_curve=[{"timestamp": "t1", "equity": 100000.0}, {"timestamp": "t2", "equity": 101000.0}],
        current_drawdown_pct=0.0,
        max_drawdown_pct=-1.0,
        sharpe_ratio=0.5,
    )
    FakePortfolioService.analysis = make_analysis(performance=performance)

    at = run_page()

    assert not at.exception
    assert not any("No portfolio snapshots yet" in i.value for i in at.info)


def test_insufficient_history_message_renders():
    FakePortfolioService.analysis = make_analysis(
        performance=make_performance(),  # empty equity_curve
    )

    at = run_page()

    assert not at.exception
    assert any("No portfolio snapshots yet" in i.value for i in at.info)


def test_analysis_warnings_render():
    FakePortfolioService.analysis = make_analysis(
        warnings=["Only 1 snapshot(s) available; volatility/Sharpe/Sortino require at least 2 snapshots."]
    )

    at = run_page()

    assert not at.exception
    assert any("Only 1 snapshot" in w.value for w in at.warning)


def test_reconciliation_balanced_shows_success():
    FakePortfolioService.analysis = make_analysis(
        reconciliation=ReconciliationResult(balanced=True, differences={})
    )

    at = run_page()

    assert any("reconciliation balanced" in s.value.lower() for s in at.success)


def test_reconciliation_mismatch_shows_error():
    FakePortfolioService.analysis = make_analysis(
        reconciliation=ReconciliationResult(
            balanced=False, differences={"cash_mismatch": {"value": -5.0}}
        )
    )

    at = run_page()

    assert not at.exception
    assert any("Reconciliation mismatch" in e.value for e in at.error)


def test_create_snapshot_button_calls_service():
    at = run_page()
    snapshot_button = next(b for b in at.button if b.label == "Create Portfolio Snapshot")
    snapshot_button.click().run(timeout=30)

    total_calls = sum(i.create_snapshot_calls for i in FakePortfolioService.instances)
    assert total_calls == 1


def test_create_snapshot_error_renders():
    from core.services.portfolio_service import PortfolioServiceError

    FakePortfolioService.create_snapshot_raises = PortfolioServiceError("disk full")

    at = run_page()
    snapshot_button = next(b for b in at.button if b.label == "Create Portfolio Snapshot")
    snapshot_button.click().run(timeout=30)

    assert not at.exception
    assert any("disk full" in e.value for e in at.error)


def test_refresh_prices_uses_paper_trading_service():
    FakePortfolioService.positions = [make_position()]

    at = run_page()
    refresh_button = next(b for b in at.button if b.label == "Refresh Position Prices")
    refresh_button.click().run(timeout=30)

    total_calls = sum(len(i.update_positions_calls) for i in FakePaperTradingService.instances)
    assert total_calls == 1


def test_refresh_prices_with_no_positions_shows_warning():
    at = run_page()
    refresh_button = next(b for b in at.button if b.label == "Refresh Position Prices")
    refresh_button.click().run(timeout=30)

    assert not at.exception
    assert any("No open positions to refresh" in w.value for w in at.warning)


def test_analysis_error_is_caught_and_displayed():
    from core.services.portfolio_service import PortfolioServiceError

    FakePortfolioService.analysis_raises = PortfolioServiceError("db locked")

    at = run_page()

    assert not at.exception
    assert any("db locked" in e.value for e in at.error)


def test_no_real_streamlit_server_is_started():
    at = run_page()
    assert at is not None
    assert not at.exception
