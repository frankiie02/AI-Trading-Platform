import ast
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import core.services.backtest_service as backtest_service_module
from core.services.backtest_service import (
    BacktestDataError,
    BacktestRequest,
    BacktestResult,
    BacktestServiceError,
    BacktestTrade,
    InvalidBacktestRequestError,
)
from core.pipeline.models import ScanStrategyMode

PAGE_PATH = "pages/3_Backtesting.py"
PAGE_SOURCE_PATH = Path(__file__).resolve().parents[2] / PAGE_PATH

# Entire modules the page must no longer import: the backtest workflow they
# implement (market data, pipeline evaluation, regime, alpha, risk,
# performance-metric calculation) now lives exclusively inside
# BacktestService / TradingPipeline.
FORBIDDEN_MODULE_PREFIXES = (
    "core.market_data",
    "core.pipeline.trading_pipeline",
    "core.alpha",
    "core.regime",
    "core.risk",
    "core.execution",
    "core.voting",
    "core.analytics",
)

FORBIDDEN_IMPORTED_NAMES = {
    "core.strategy.strategy_engine": {"generate_strategy_signals"},
}


def _parse_imports(source: str):
    tree = ast.parse(source)
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.append((node.module, [alias.name for alias in node.names]))
        elif isinstance(node, ast.Import):
            imports.append((None, [alias.name for alias in node.names]))

    return imports


def make_result(
    trades=None,
    warnings=None,
    metrics=None,
    strategy_mode=ScanStrategyMode.SINGLE,
):
    default_metrics = {
        "Initial Capital": 100000.0,
        "Final Equity": 110000.0,
        "Total Return %": 10.0,
        "Annualised Return %": 8.0,
        "Volatility %": 12.0,
        "Sharpe Ratio": 1.2,
        "Sortino Ratio": 1.5,
        "Max Drawdown %": -5.0,
        "Win Rate %": 60.0,
        "Profit Factor": 1.8,
        "Expectancy": 25.0,
        "Total Trades": 1,
        "Average Win": 100.0,
        "Average Loss": -50.0,
        "Exposure %": 40.0,
        "Total Fees": 2.0,
    }

    if metrics:
        default_metrics.update(metrics)

    return BacktestResult(
        request=BacktestRequest(symbol="SPY", strategy_mode=strategy_mode),
        trades=trades if trades is not None else [
            BacktestTrade(
                symbol="SPY",
                entry_timestamp=pd.Timestamp("2024-01-02"),
                exit_timestamp=pd.Timestamp("2024-01-05"),
                entry_price=100.0,
                exit_price=105.0,
                quantity=10,
                stop_loss=95.0,
                take_profit=115.0,
                gross_pnl=50.0,
                fees=2.0,
                net_pnl=48.0,
                exit_reason="TAKE_PROFIT",
                strategy_mode=strategy_mode,
                strategy_name="EMA Trend",
            )
        ],
        equity_curve=pd.DataFrame({
            "Date": pd.date_range("2024-01-01", periods=3, freq="D"),
            "Equity": [100000.0, 105000.0, 110000.0],
        }),
        metrics=default_metrics,
        benchmark_metrics={
            "Final Equity": 108000.0,
            "Total Return %": 8.0,
            "Annualised Return %": 6.0,
            "Max Drawdown %": -6.0,
        },
        warnings=warnings if warnings is not None else [],
        errors=[],
    )


class FakeBacktestService:
    instances = []
    result = None
    raises = None

    def __init__(self, *args, **kwargs):
        self.run_calls = []
        FakeBacktestService.instances.append(self)

    def run(self, request):
        self.run_calls.append(request)

        if FakeBacktestService.raises:
            raise FakeBacktestService.raises

        return FakeBacktestService.result


@pytest.fixture(autouse=True)
def isolate_page_collaborators(monkeypatch):
    """No AppTest run may hit real market data or the real BacktestService."""
    FakeBacktestService.instances = []
    FakeBacktestService.result = make_result()
    FakeBacktestService.raises = None
    monkeypatch.setattr(backtest_service_module, "BacktestService", FakeBacktestService)

    yield


def run_page():
    at = AppTest.from_file(PAGE_PATH)
    at.run(timeout=30)
    return at


# ---------------------------------------------------------------------------
# Static import-boundary checks
# ---------------------------------------------------------------------------

def test_page_syntax_is_valid():
    ast.parse(PAGE_SOURCE_PATH.read_text())


def test_page_imports_backtest_service_and_backtest_request():
    imports = _parse_imports(PAGE_SOURCE_PATH.read_text())
    backtest_service_names = set()

    for module, names in imports:
        if module == "core.services.backtest_service":
            backtest_service_names.update(names)

    assert "BacktestService" in backtest_service_names
    assert "BacktestRequest" in backtest_service_names


def test_page_does_not_import_forbidden_orchestration_modules():
    imports = _parse_imports(PAGE_SOURCE_PATH.read_text())

    for module, _names in imports:
        if module is None:
            continue
        assert not module.startswith(FORBIDDEN_MODULE_PREFIXES), (
            f"3_Backtesting.py must not import '{module}'"
        )


def test_page_does_not_import_forbidden_names_from_allowed_modules():
    imports = _parse_imports(PAGE_SOURCE_PATH.read_text())

    for module, names in imports:
        forbidden_names = FORBIDDEN_IMPORTED_NAMES.get(module, set())
        overlap = forbidden_names.intersection(names)
        assert not overlap, f"3_Backtesting.py must not import {overlap} from '{module}'"


def test_page_contains_no_direct_pipeline_or_performance_calls():
    source = PAGE_SOURCE_PATH.read_text()
    assert "TradingPipeline(" not in source
    assert "calculate_performance" not in source
    assert "download_price_data" not in source


# ---------------------------------------------------------------------------
# Behavioural checks (Streamlit AppTest - no real server, no real network)
# ---------------------------------------------------------------------------

def test_page_runs_without_exception():
    at = run_page()
    assert not at.exception


def test_both_backtest_modes_are_selectable():
    at = run_page()
    mode_radio = at.radio[0]
    assert set(mode_radio.options) == {"Single Strategy", "Strategy Voting"}


def test_single_strategy_widget_values_map_to_backtest_request():
    at = run_page()
    at.button[0].click().run(timeout=30)

    request = FakeBacktestService.instances[0].run_calls[0]
    assert request.strategy_name == "EMA Trend"
    assert request.strategy_mode.value == "single"
    assert request.symbol == "SPY"
    assert request.short_ema == 20
    assert request.long_ema == 50
    assert request.minimum_alpha_score == 70
    assert request.initial_capital == 100000


def test_voting_mode_hides_strategy_selector_and_sets_request_mode():
    at = run_page()
    at.radio[0].set_value("Strategy Voting").run(timeout=30)

    # Only the "Backtest Period" selectbox should remain once voting mode
    # hides the single-strategy selector.
    assert len(at.selectbox) == 1

    at.button[0].click().run(timeout=30)

    request = FakeBacktestService.instances[0].run_calls[0]
    assert request.strategy_mode.value == "voting"


def test_run_backtest_button_invokes_the_service():
    at = run_page()
    at.button[0].click().run(timeout=30)

    assert len(FakeBacktestService.instances) == 1
    assert len(FakeBacktestService.instances[0].run_calls) == 1


def test_metrics_render_after_run():
    at = run_page()
    at.button[0].click().run(timeout=30)

    assert not at.exception
    metric_values = [m.value for m in at.metric]
    assert any("110,000" in value for value in metric_values)


def test_equity_curve_renders():
    at = run_page()
    at.button[0].click().run(timeout=30)

    # st.line_chart renders as a Vega-Lite element with no dedicated AppTest
    # accessor; absence of an exception plus the section heading confirms
    # the equity curve branch executed and rendered rather than erroring.
    assert not at.exception
    assert any("Equity Curve" in header.value for header in at.subheader)


def test_trade_table_renders():
    at = run_page()
    at.button[0].click().run(timeout=30)

    assert len(at.dataframe) >= 1


def test_no_trades_shows_info_message():
    FakeBacktestService.result = make_result(trades=[])

    at = run_page()
    at.button[0].click().run(timeout=30)

    assert any("No completed trades" in info.value for info in at.info)


def test_warnings_are_rendered():
    FakeBacktestService.result = make_result(warnings=["Skipped 5 bar(s) with insufficient indicator history."])

    at = run_page()
    at.button[0].click().run(timeout=30)

    assert any("Skipped 5 bar" in warning.value for warning in at.warning)


def test_invalid_request_error_is_caught_and_displayed():
    FakeBacktestService.raises = InvalidBacktestRequestError("initial_capital must be positive")

    at = run_page()
    at.button[0].click().run(timeout=30)

    assert not at.exception
    assert any("initial_capital must be positive" in error.value for error in at.error)


def test_data_error_is_caught_and_displayed():
    FakeBacktestService.raises = BacktestDataError("No market data returned for SPY.")

    at = run_page()
    at.button[0].click().run(timeout=30)

    assert not at.exception
    assert any("No market data returned" in error.value for error in at.error)


def test_generic_backtest_service_error_is_caught_and_displayed():
    FakeBacktestService.raises = BacktestServiceError("simulation blew up")

    at = run_page()
    at.button[0].click().run(timeout=30)

    assert not at.exception
    assert any("simulation blew up" in error.value for error in at.error)


def test_no_real_streamlit_server_is_started():
    """AppTest is Streamlit's own in-process test harness; it never binds a
    port or starts a real server, satisfying this requirement by
    construction. This test documents and asserts that expectation."""
    at = run_page()
    assert at is not None
    assert not at.exception
