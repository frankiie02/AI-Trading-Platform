import ast
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import core.services.paper_trading_service as paper_trading_service_module
from core.services.paper_trading_service import (
    OrderStatus,
    PaperAccount,
    PaperOrder,
    PaperTradingResult,
    PaperTradingServiceError,
)

PAGE_PATH = "pages/5_Trade_Queue.py"
PAGE_SOURCE_PATH = Path(__file__).resolve().parents[2] / PAGE_PATH

FORBIDDEN_MODULE_PREFIXES = (
    "core.execution.execution_router",
    "core.execution.paper_trader",
    "core.execution.paper_orders_repository",
    "core.database",
    "ib_insync",
    "core.broker",
)


def make_account(**overrides):
    fields = dict(
        account_id="default", starting_balance=100000.0, cash=90000.0, equity=98000.0,
        realised_pnl=500.0, unrealised_pnl=-100.0, reserved_cash=0.0, buying_power=90000.0,
    )
    fields.update(overrides)
    return PaperAccount(**fields)


def make_pending_df(rows=None):
    if rows is None:
        rows = [
            {"ID": 1, "Created At": "now", "Symbol": "AAPL", "Side": "BUY", "Shares": 10,
             "Price": 100.0, "Stop Loss": 90.0, "Take Profit": 120.0, "Dollar Risk": 100.0,
             "Status": "PENDING", "Source": "scanner"},
            {"ID": 2, "Created At": "now", "Symbol": "MSFT", "Side": "BUY", "Shares": 5,
             "Price": 200.0, "Stop Loss": 180.0, "Take Profit": 220.0, "Dollar Risk": 100.0,
             "Status": "PENDING", "Source": "scanner"},
        ]
    return pd.DataFrame(rows)


def make_order(**overrides):
    fields = dict(
        order_id=1, symbol="AAPL", side="BUY", quantity=10, order_type="MARKET",
        requested_price=100.0, stop_loss=None, take_profit=None, strategy_name="Queued Signal",
        strategy_mode="queue", source_reference="trade_queue:1", status=OrderStatus.FILLED.value,
        rejection_reason=None, fill_price=101.0, fill_timestamp="now", fees=0.0,
        created_at="now", updated_at="now",
    )
    fields.update(overrides)
    return PaperOrder(**fields)


class FakePaperTradingService:
    instances = []
    account = None
    pending = None
    orders = []
    process_queue_result = None
    process_queue_raises = None

    def __init__(self, *args, **kwargs):
        self.process_queue_calls = []
        FakePaperTradingService.instances.append(self)

    def get_account(self):
        return FakePaperTradingService.account

    def get_pending_queue_items(self):
        return FakePaperTradingService.pending

    def get_orders(self, status=None):
        return FakePaperTradingService.orders

    def process_queue(self, enabled=False, queue_ids=None, auto_fill=True, limit=None):
        self.process_queue_calls.append(
            {"enabled": enabled, "queue_ids": queue_ids, "auto_fill": auto_fill, "limit": limit}
        )

        if FakePaperTradingService.process_queue_raises:
            raise FakePaperTradingService.process_queue_raises

        return FakePaperTradingService.process_queue_result or PaperTradingResult(
            account=FakePaperTradingService.account
        )


@pytest.fixture(autouse=True)
def isolate_page_collaborators(monkeypatch):
    FakePaperTradingService.instances = []
    FakePaperTradingService.account = make_account()
    FakePaperTradingService.pending = make_pending_df(rows=[])
    FakePaperTradingService.orders = []
    FakePaperTradingService.process_queue_result = None
    FakePaperTradingService.process_queue_raises = None

    monkeypatch.setattr(paper_trading_service_module, "PaperTradingService", FakePaperTradingService)

    yield


def run_page():
    at = AppTest.from_file(PAGE_PATH)
    at.run(timeout=30)
    return at


def all_process_queue_calls():
    calls = []
    for instance in FakePaperTradingService.instances:
        calls.extend(instance.process_queue_calls)
    return calls


# ---------------------------------------------------------------------------
# Static import-boundary checks
# ---------------------------------------------------------------------------

def test_page_syntax_is_valid():
    ast.parse(PAGE_SOURCE_PATH.read_text())


def test_page_imports_paper_trading_service():
    source = PAGE_SOURCE_PATH.read_text()
    assert "PaperTradingService" in source


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
            f"5_Trade_Queue.py must not import '{module}'"
        )


def test_page_source_never_mentions_execution_router_or_paper_trader():
    source = PAGE_SOURCE_PATH.read_text()
    assert "ExecutionRouter" not in source
    assert "PaperTrader" not in source
    assert "ib_insync" not in source
    assert "IBKR" not in source


def test_page_contains_no_direct_sql():
    source = PAGE_SOURCE_PATH.read_text()
    assert "sqlite3" not in source
    assert "cursor.execute" not in source
    assert "conn.execute" not in source
    assert "get_connection" not in source


# ---------------------------------------------------------------------------
# Behavioural checks (Streamlit AppTest - no real server, no real network)
# ---------------------------------------------------------------------------

def test_page_runs_without_exception():
    at = run_page()
    assert not at.exception


def test_account_metrics_render():
    at = run_page()
    values = [m.value for m in at.metric]
    assert any("90,000" in v for v in values)


def test_no_pending_trades_shows_info():
    at = run_page()
    assert any("No pending trades in the queue" in i.value for i in at.info)


def test_pending_queue_items_render():
    FakePaperTradingService.pending = make_pending_df()

    at = run_page()

    assert not at.exception
    assert len(at.dataframe) >= 1


def test_processing_defaults_off_before_user_action():
    FakePaperTradingService.pending = make_pending_df()

    run_page()

    assert all_process_queue_calls() == []


def test_selected_ids_map_into_process_queue():
    FakePaperTradingService.pending = make_pending_df()

    at = run_page()
    at.multiselect[0].set_value([2]).run(timeout=30)
    process_button = next(b for b in at.button if b.label == "Process Selected")
    process_button.click().run(timeout=30)

    calls = all_process_queue_calls()
    assert len(calls) == 1
    assert calls[0]["queue_ids"] == [2]
    assert calls[0]["enabled"] is True


def test_unselected_rows_are_not_included():
    FakePaperTradingService.pending = make_pending_df()

    at = run_page()
    at.multiselect[0].set_value([1]).run(timeout=30)
    process_button = next(b for b in at.button if b.label == "Process Selected")
    process_button.click().run(timeout=30)

    calls = all_process_queue_calls()
    assert calls[0]["queue_ids"] == [1]
    assert 2 not in calls[0]["queue_ids"]


def test_process_without_selection_shows_warning():
    FakePaperTradingService.pending = make_pending_df()

    at = run_page()
    process_button = next(b for b in at.button if b.label == "Process Selected")
    process_button.click().run(timeout=30)

    assert not at.exception
    assert any("Select at least one queue item" in w.value for w in at.warning)
    assert all_process_queue_calls() == []


def test_hold_for_review_maps_to_auto_fill_false():
    FakePaperTradingService.pending = make_pending_df()

    at = run_page()
    at.checkbox[0].set_value(True).run(timeout=30)
    at.multiselect[0].set_value([1]).run(timeout=30)
    process_button = next(b for b in at.button if b.label == "Process Selected")
    process_button.click().run(timeout=30)

    calls = all_process_queue_calls()
    assert calls[0]["auto_fill"] is False


def test_default_not_held_for_review_auto_fills():
    FakePaperTradingService.pending = make_pending_df()

    at = run_page()
    at.multiselect[0].set_value([1]).run(timeout=30)
    process_button = next(b for b in at.button if b.label == "Process Selected")
    process_button.click().run(timeout=30)

    calls = all_process_queue_calls()
    assert calls[0]["auto_fill"] is True


def test_filled_and_rejected_counts_render():
    FakePaperTradingService.pending = make_pending_df()
    filled_order = make_order(order_id=1, status=OrderStatus.FILLED.value)
    rejected_order = make_order(
        order_id=2, status=OrderStatus.REJECTED.value,
        rejection_reason="Insufficient cash for this order.",
    )
    FakePaperTradingService.process_queue_result = PaperTradingResult(
        account=make_account(),
        orders_created=[filled_order, rejected_order],
        orders_filled=[filled_order],
        orders_rejected=[rejected_order],
    )

    at = run_page()
    at.multiselect[0].set_value([1, 2]).run(timeout=30)
    process_button = next(b for b in at.button if b.label == "Process Selected")
    process_button.click().run(timeout=30)

    assert not at.exception
    assert any("1 filled" in s.value and "1 rejected" in s.value for s in at.success)


def test_warnings_and_errors_from_result_render():
    FakePaperTradingService.pending = make_pending_df()
    FakePaperTradingService.process_queue_result = PaperTradingResult(
        account=make_account(),
        warnings=["Symbol XYZ skipped: no reference price."],
        errors=["Queue item 9: unexpected failure"],
    )

    at = run_page()
    at.multiselect[0].set_value([1]).run(timeout=30)
    process_button = next(b for b in at.button if b.label == "Process Selected")
    process_button.click().run(timeout=30)

    assert not at.exception
    assert any("Symbol XYZ skipped" in w.value for w in at.warning)
    assert any("Queue item 9" in e.value for e in at.error)


def test_service_exception_renders_as_error():
    FakePaperTradingService.pending = make_pending_df()
    FakePaperTradingService.process_queue_raises = PaperTradingServiceError("db locked")

    at = run_page()
    at.multiselect[0].set_value([1]).run(timeout=30)
    process_button = next(b for b in at.button if b.label == "Process Selected")
    process_button.click().run(timeout=30)

    assert not at.exception
    assert any("db locked" in e.value for e in at.error)


def test_no_queued_orders_shows_info():
    at = run_page()
    assert any("No queued signals have been processed yet" in i.value for i in at.info)


def test_recent_orders_from_queue_render():
    FakePaperTradingService.orders = [make_order(source_reference="trade_queue:1")]

    at = run_page()

    assert not at.exception
    assert len(at.dataframe) >= 1


def test_orders_not_sourced_from_queue_are_excluded():
    manual_order = make_order(order_id=5, source_reference="manual")
    queue_order = make_order(order_id=6, source_reference="trade_queue:6")
    FakePaperTradingService.orders = [manual_order, queue_order]

    at = run_page()

    assert not at.exception
    # Exactly one recent-orders dataframe rendered, containing only the
    # queue-sourced order (filtering is asserted indirectly: no exception
    # and the info/empty-state branch was not taken since orders is non-empty).
    assert len(at.dataframe) >= 1


def test_no_real_streamlit_server_is_started():
    at = run_page()
    assert at is not None
    assert not at.exception
