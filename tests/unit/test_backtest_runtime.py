import ast
import logging
from pathlib import Path

import pandas as pd
import pytest

from config.defaults import DEFAULT_SETTINGS
from core.pipeline.models import ScanStrategyMode
from core.runtime.context import RuntimeContext
from core.runtime.modes import RuntimeMode
from core.runtime.backtest_runtime import build_backtest_request, run_backtest
from core.services.backtest_service import (
    BacktestDataError,
    BacktestRequest,
    BacktestResult,
)

FORBIDDEN_IMPORT_PREFIXES = (
    "streamlit",
    "pages",
    "dashboard",
    "core.broker",
    "ib_insync",
)


def make_context(settings=None):
    return RuntimeContext(
        settings=settings if settings is not None else {},
        mode=RuntimeMode.BACKTEST,
        logger=logging.getLogger("test.backtest_runtime"),
    )


class FakeBacktestService:
    def __init__(self, result=None, raises=None):
        self.received_requests = []
        self._result = result or BacktestResult(
            request=BacktestRequest(symbol="SPY"),
            trades=[],
            equity_curve=pd.DataFrame({"Date": [], "Equity": []}),
            metrics={
                "Total Trades": 3,
                "Total Return %": 12.5,
                "Max Drawdown %": -4.2,
                "Final Equity": 112500.0,
            },
            benchmark_metrics={},
            warnings=[],
            errors=[],
        )
        self._raises = raises

    def run(self, request):
        self.received_requests.append(request)

        if self._raises:
            raise self._raises

        return self._result


# ---------------------------------------------------------------------------
# build_backtest_request
# ---------------------------------------------------------------------------

def test_build_backtest_request_uses_backtest_defaults_when_settings_empty():
    request = build_backtest_request({})

    assert request.symbol == DEFAULT_SETTINGS["BACKTEST_SYMBOL"]
    assert request.strategy_mode == ScanStrategyMode.SINGLE
    assert request.strategy_name == DEFAULT_SETTINGS["BACKTEST_STRATEGY"]
    assert request.period == DEFAULT_SETTINGS["BACKTEST_PERIOD"]
    assert request.initial_capital == DEFAULT_SETTINGS["BACKTEST_INITIAL_CAPITAL"]


def test_build_backtest_request_honours_injected_settings():
    settings = {
        "BACKTEST_SYMBOL": "QQQ",
        "BACKTEST_STRATEGY_MODE": "voting",
        "BACKTEST_MINIMUM_ALPHA_SCORE": 55,
        "BACKTEST_COMMISSION": 1.5,
    }

    request = build_backtest_request(settings)

    assert request.symbol == "QQQ"
    assert request.strategy_mode == ScanStrategyMode.VOTING
    assert request.minimum_alpha_score == 55
    assert request.commission == 1.5


def test_build_backtest_request_returns_backtest_request_instance():
    assert isinstance(build_backtest_request({}), BacktestRequest)


# ---------------------------------------------------------------------------
# run_backtest
# ---------------------------------------------------------------------------

def test_run_backtest_routes_to_backtest_service():
    fake_service = FakeBacktestService()

    result = run_backtest(make_context(), service=fake_service)

    assert len(fake_service.received_requests) == 1
    assert result.mode is RuntimeMode.BACKTEST
    assert result.status == "completed"


def test_run_backtest_builds_request_from_settings():
    fake_service = FakeBacktestService()
    settings = {"BACKTEST_SYMBOL": "AAPL", "BACKTEST_STRATEGY_MODE": "single"}

    run_backtest(make_context(settings), service=fake_service)

    request = fake_service.received_requests[0]
    assert request.symbol == "AAPL"
    assert request.strategy_mode == ScanStrategyMode.SINGLE


def test_run_backtest_returns_concise_summary():
    fake_service = FakeBacktestService()

    result = run_backtest(make_context(), service=fake_service)

    assert "3 trade" in result.message
    assert "12.50%" in result.message
    assert "-4.20%" in result.message


def test_run_backtest_raises_controlled_error_on_data_failure():
    fake_service = FakeBacktestService(raises=BacktestDataError("no data"))

    with pytest.raises(BacktestDataError):
        run_backtest(make_context(), service=fake_service)


def test_run_backtest_never_touches_broker_or_streamlit_modules():
    module_path = Path(__file__).resolve().parents[2] / "core" / "runtime" / "backtest_runtime.py"
    tree = ast.parse(module_path.read_text())

    imported_modules = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    for module_name in imported_modules:
        assert not module_name.startswith(FORBIDDEN_IMPORT_PREFIXES), (
            f"backtest_runtime.py must not import '{module_name}'"
        )


def test_run_backtest_makes_no_streamlit_import():
    module_path = Path(__file__).resolve().parents[2] / "core" / "runtime" / "backtest_runtime.py"
    tree = ast.parse(module_path.read_text())

    imported_modules = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    assert not any(name.startswith("streamlit") for name in imported_modules)
