import ast
import logging
from pathlib import Path

import pandas as pd
import pytest

from config.defaults import DEFAULT_SETTINGS
from core.runtime.context import RuntimeContext
from core.runtime.modes import RuntimeMode
from core.runtime.scanner_runtime import build_scan_request, run_scanner
from core.services.scanner_service import (
    ScanRequest,
    ScannerPersistenceError,
    ScanResult,
    ScanStatistics,
    ScanStrategyMode,
    SymbolScanOutcome,
    TradeQueuePersistenceError,
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
        mode=RuntimeMode.SCANNER,
        logger=logging.getLogger("test.scanner_runtime"),
    )


class FakeScannerService:
    def __init__(self, result=None, raises=None):
        self.received_requests = []
        self.received_progress_callbacks = []
        self._result = result or ScanResult(
            outcomes=[
                SymbolScanOutcome(
                    symbol="SPY", status="OK", strategy="EMA Trend", final_signal="BUY"
                )
            ],
            legacy_results=[],
            ranked=pd.DataFrame(),
            queued_count=0,
            statistics=ScanStatistics(
                symbols_requested=1,
                symbols_processed=1,
                successful_symbols=1,
                failed_symbols=0,
                buy_signals=1,
                no_trade_signals=0,
                queued_trades=0,
            ),
        )
        self._raises = raises

    def scan(self, request, progress_callback=None):
        self.received_requests.append(request)
        self.received_progress_callbacks.append(progress_callback)

        if progress_callback is not None:
            progress_callback(1, len(request.symbols), request.symbols[0])

        if self._raises:
            raise self._raises

        return self._result


# ---------------------------------------------------------------------------
# build_scan_request
# ---------------------------------------------------------------------------

def test_build_scan_request_uses_scanner_defaults_when_settings_empty():
    request = build_scan_request({})

    assert request.symbols == DEFAULT_SETTINGS["SCANNER_SYMBOLS"]
    assert request.strategy_mode == ScanStrategyMode.SINGLE
    assert request.strategy_name == DEFAULT_SETTINGS["SCANNER_STRATEGY_NAME"]
    assert request.period == DEFAULT_SETTINGS["SCANNER_PERIOD"]
    assert request.queue_trades == DEFAULT_SETTINGS["SCANNER_QUEUE_TRADES"]
    assert request.queue_trades is False


def test_build_scan_request_honours_injected_settings():
    settings = {
        "SCANNER_SYMBOLS": ["MSFT", "NVDA"],
        "SCANNER_STRATEGY_MODE": "voting",
        "SCANNER_MINIMUM_ALPHA_SCORE": 55,
        "SCANNER_QUEUE_TRADES": True,
    }

    request = build_scan_request(settings)

    assert request.symbols == ["MSFT", "NVDA"]
    assert request.strategy_mode == ScanStrategyMode.VOTING
    assert request.minimum_alpha_score == 55
    assert request.queue_trades is True


def test_build_scan_request_returns_scan_request_instance():
    assert isinstance(build_scan_request({}), ScanRequest)


# ---------------------------------------------------------------------------
# run_scanner
# ---------------------------------------------------------------------------

def test_run_scanner_routes_to_scanner_service():
    fake_service = FakeScannerService()

    result = run_scanner(make_context(), service=fake_service)

    assert len(fake_service.received_requests) == 1
    assert result.mode is RuntimeMode.SCANNER
    assert result.status == "completed"


def test_run_scanner_builds_request_from_settings():
    fake_service = FakeScannerService()
    settings = {"SCANNER_SYMBOLS": ["AAPL"], "SCANNER_STRATEGY_MODE": "single"}

    run_scanner(make_context(settings), service=fake_service)

    request = fake_service.received_requests[0]
    assert request.symbols == ["AAPL"]
    assert request.strategy_mode == ScanStrategyMode.SINGLE


def test_run_scanner_supplies_a_progress_callback():
    fake_service = FakeScannerService()

    run_scanner(make_context(), service=fake_service)

    assert fake_service.received_progress_callbacks[0] is not None


def test_run_scanner_returns_concise_summary_with_statistics():
    fake_service = FakeScannerService()

    result = run_scanner(make_context(), service=fake_service)

    assert "1/1" in result.message
    assert "1 BUY signal" in result.message


def test_run_scanner_represents_partial_failure_in_summary():
    result_with_failure = ScanResult(
        outcomes=[],
        legacy_results=[],
        ranked=pd.DataFrame(),
        queued_count=0,
        statistics=ScanStatistics(
            symbols_requested=3,
            symbols_processed=3,
            successful_symbols=2,
            failed_symbols=1,
            buy_signals=1,
            no_trade_signals=1,
            queued_trades=0,
        ),
    )
    fake_service = FakeScannerService(result=result_with_failure)

    result = run_scanner(make_context(), service=fake_service)

    assert "2/3" in result.message
    assert "1 failed" in result.message


def test_run_scanner_raises_controlled_error_on_persistence_failure():
    fake_service = FakeScannerService(raises=ScannerPersistenceError("disk full"))

    with pytest.raises(ScannerPersistenceError):
        run_scanner(make_context(), service=fake_service)


def test_run_scanner_raises_controlled_error_on_queue_persistence_failure():
    fake_service = FakeScannerService(raises=TradeQueuePersistenceError("db locked"))

    with pytest.raises(TradeQueuePersistenceError):
        run_scanner(make_context(), service=fake_service)


def test_run_scanner_never_submits_live_orders_or_touches_broker_modules():
    """Static guard: the runtime module itself must not import broker,
    live-execution, or Streamlit code."""
    module_path = Path(__file__).resolve().parents[2] / "core" / "runtime" / "scanner_runtime.py"
    tree = ast.parse(module_path.read_text())

    imported_modules = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    for module_name in imported_modules:
        assert not module_name.startswith(FORBIDDEN_IMPORT_PREFIXES), (
            f"scanner_runtime.py must not import '{module_name}'"
        )


def test_run_scanner_makes_no_streamlit_import():
    module_path = Path(__file__).resolve().parents[2] / "core" / "runtime" / "scanner_runtime.py"
    tree = ast.parse(module_path.read_text())

    imported_modules = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    assert not any(name.startswith("streamlit") for name in imported_modules)
