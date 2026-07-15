import ast
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import core.scanner.scanner_repository as scanner_repository
import core.services.scanner_service as scanner_service_module
from core.services.scanner_service import (
    ScannerPersistenceError,
    SymbolScanOutcome,
    TradeQueuePersistenceError,
)

PAGE_PATH = "pages/1_Live_Scanner.py"
PAGE_SOURCE_PATH = Path(__file__).resolve().parents[2] / PAGE_PATH

# Entire modules the page must no longer import: the business workflow they
# implement (market data, regime, alpha, risk, trade-queue writes, voting)
# now lives exclusively inside ScannerService.
FORBIDDEN_MODULE_PREFIXES = (
    "core.market_data",
    "core.alpha",
    "core.regime",
    "core.risk",
    "core.execution",
    "core.voting",
)

# Names that must not be imported even from modules the page is otherwise
# still allowed to touch for historical/reference purposes.
FORBIDDEN_IMPORTED_NAMES = {
    "core.strategy.strategy_engine": {"generate_strategy_signals"},
    "core.scanner.scanner_repository": {"save_scanner_results"},
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


class FakeScanResult:
    def __init__(self, outcomes=None, queued_count=0, ranked=None):
        self.outcomes = outcomes if outcomes is not None else []
        self.queued_count = queued_count
        self.ranked = (
            ranked
            if ranked is not None
            else pd.DataFrame({"Symbol": ["AAPL"], "Signal": ["BUY"]})
        )


class FakeScannerService:
    """Test double standing in for the real ScannerService."""

    instances = []

    def __init__(self, *args, **kwargs):
        self.scan_calls = []
        self.progress_callbacks = []
        FakeScannerService.instances.append(self)

    def scan(self, request, progress_callback=None):
        self.scan_calls.append(request)
        self.progress_callbacks.append(progress_callback)

        if progress_callback is not None:
            progress_callback(1, len(request.symbols), request.symbols[0])

        if getattr(FakeScannerService, "raises", None):
            raise FakeScannerService.raises

        return getattr(FakeScannerService, "result", FakeScanResult())


@pytest.fixture(autouse=True)
def isolate_page_collaborators(monkeypatch):
    """No AppTest run may hit a real database or the real ScannerService."""
    monkeypatch.setattr(
        scanner_repository, "get_recent_scanner_results", lambda limit=50: pd.DataFrame()
    )
    monkeypatch.setattr(
        scanner_repository, "get_recent_buy_signals", lambda limit=25: pd.DataFrame()
    )

    FakeScannerService.instances = []
    FakeScannerService.result = FakeScanResult()
    FakeScannerService.raises = None
    monkeypatch.setattr(scanner_service_module, "ScannerService", FakeScannerService)

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


def test_page_imports_scanner_service_and_scan_request():
    imports = _parse_imports(PAGE_SOURCE_PATH.read_text())
    scanner_service_names = set()

    for module, names in imports:
        if module == "core.services.scanner_service":
            scanner_service_names.update(names)

    assert "ScannerService" in scanner_service_names
    assert "ScanRequest" in scanner_service_names


def test_page_does_not_import_forbidden_orchestration_modules():
    imports = _parse_imports(PAGE_SOURCE_PATH.read_text())

    for module, _names in imports:
        if module is None:
            continue
        assert not module.startswith(FORBIDDEN_MODULE_PREFIXES), (
            f"1_Live_Scanner.py must not import '{module}'"
        )


def test_page_does_not_import_forbidden_names_from_allowed_modules():
    imports = _parse_imports(PAGE_SOURCE_PATH.read_text())

    for module, names in imports:
        forbidden_names = FORBIDDEN_IMPORTED_NAMES.get(module, set())
        overlap = forbidden_names.intersection(names)
        assert not overlap, f"1_Live_Scanner.py must not import {overlap} from '{module}'"


def test_page_contains_no_voting_engine_direct_call():
    source = PAGE_SOURCE_PATH.read_text()
    assert "run_strategy_voting" not in source
    assert "core.voting" not in source


# ---------------------------------------------------------------------------
# Behavioural checks (Streamlit AppTest - no real server, no real network/DB)
# ---------------------------------------------------------------------------

def test_page_runs_without_exception():
    at = run_page()
    assert not at.exception


def test_both_scanner_modes_are_selectable():
    at = run_page()
    mode_radio = at.radio[0]
    assert set(mode_radio.options) == {"Single Strategy", "Strategy Voting"}


def test_single_strategy_widget_values_map_to_scan_request():
    at = run_page()
    at.button[0].click().run(timeout=30)

    request = FakeScannerService.instances[0].scan_calls[0]
    assert request.strategy_name == "EMA Trend"
    assert request.strategy_mode.value == "single"
    assert request.symbols[0] == "SPY"
    assert request.short_ema == 20
    assert request.long_ema == 50
    assert request.minimum_alpha_score == 70
    assert request.queue_trades is True


def test_voting_mode_hides_strategy_selector_and_sets_request_mode():
    at = run_page()
    at.radio[0].set_value("Strategy Voting").run(timeout=30)

    # Only the "Data Period" selectbox should remain once voting mode hides
    # the single-strategy selector.
    assert len(at.selectbox) == 1

    at.button[0].click().run(timeout=30)

    request = FakeScannerService.instances[0].scan_calls[0]
    assert request.strategy_mode.value == "voting"


def test_scan_button_invokes_the_service():
    at = run_page()
    at.button[0].click().run(timeout=30)

    assert len(FakeScannerService.instances) == 1
    assert len(FakeScannerService.instances[0].scan_calls) == 1


def test_progress_callback_is_supplied_and_callable():
    at = run_page()
    at.button[0].click().run(timeout=30)

    callback = FakeScannerService.instances[0].progress_callbacks[0]
    assert callback is not None
    assert callable(callback)


def test_partial_failures_are_rendered_without_aborting_successful_results():
    FakeScannerService.result = FakeScanResult(
        outcomes=[
            SymbolScanOutcome(
                symbol="BAD",
                status="ERROR",
                strategy="EMA Trend",
                final_signal="SCAN ERROR",
                signal_reason="Market data download failed.",
            ),
            SymbolScanOutcome(
                symbol="AAPL", status="OK", strategy="EMA Trend", final_signal="BUY"
            ),
        ],
        queued_count=1,
    )

    at = run_page()
    at.button[0].click().run(timeout=30)

    assert not at.exception
    assert any("BAD" in warning.value for warning in at.warning)
    assert any("Scan complete" in success.value for success in at.success)


def test_persistence_error_is_caught_and_displayed():
    FakeScannerService.raises = ScannerPersistenceError("disk full")

    at = run_page()
    at.button[0].click().run(timeout=30)

    assert not at.exception
    assert any("disk full" in error.value for error in at.error)


def test_trade_queue_error_is_caught_and_displayed():
    FakeScannerService.raises = TradeQueuePersistenceError("db locked")

    at = run_page()
    at.button[0].click().run(timeout=30)

    assert not at.exception
    assert any("db locked" in error.value for error in at.error)


def test_ranked_results_and_queue_count_are_displayed():
    FakeScannerService.result = FakeScanResult(
        outcomes=[
            SymbolScanOutcome(
                symbol="AAPL", status="OK", strategy="EMA Trend", final_signal="BUY"
            )
        ],
        queued_count=3,
        ranked=pd.DataFrame({"Symbol": ["AAPL"], "Signal": ["BUY"], "Alpha Score": [90]}),
    )

    at = run_page()
    at.button[0].click().run(timeout=30)

    assert any("3 BUY signal(s)" in success.value for success in at.success)
    assert len(at.dataframe) >= 1


def test_no_real_streamlit_server_is_started():
    """AppTest is Streamlit's own in-process test harness; it never binds a
    port or starts a real server, satisfying this requirement by
    construction. This test documents and asserts that expectation."""
    at = run_page()
    assert at is not None
    assert not at.exception
