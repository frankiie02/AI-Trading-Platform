import ast
import logging
from pathlib import Path

import pytest

from config.defaults import DEFAULT_SETTINGS
from core.runtime.context import RuntimeContext
from core.runtime.modes import RuntimeMode
from core.runtime.paper_runtime import build_paper_settings, run_paper_trading
from core.services.paper_trading_service import (
    PaperAccount,
    PaperTradingResult,
    PaperTradingServiceError,
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
        mode=RuntimeMode.PAPER,
        logger=logging.getLogger("test.paper_runtime"),
    )


def make_account(**overrides):
    fields = dict(
        account_id="default",
        starting_balance=100000.0,
        cash=95000.0,
        equity=99000.0,
        realised_pnl=250.0,
        unrealised_pnl=-100.0,
        reserved_cash=0.0,
        buying_power=95000.0,
    )
    fields.update(overrides)
    return PaperAccount(**fields)


class FakePaperTradingService:
    def __init__(self, account=None, positions=None, process_queue_result=None, raises=None):
        self.received_process_queue_kwargs = []
        self.update_positions_calls = []
        self.check_exits_calls = []
        self._account = account or make_account()
        self._positions = positions or []
        self._process_queue_result = process_queue_result or PaperTradingResult(account=self._account)
        self._raises = raises

    def get_account(self):
        return self._account

    def get_positions(self):
        return self._positions

    def update_positions(self, price_map):
        self.update_positions_calls.append(price_map)

    def check_exits(self, price_map):
        self.check_exits_calls.append(price_map)
        return []

    def process_queue(self, **kwargs):
        self.received_process_queue_kwargs.append(kwargs)

        if self._raises:
            raise self._raises

        return self._process_queue_result


# ---------------------------------------------------------------------------
# build_paper_settings
# ---------------------------------------------------------------------------

def test_build_paper_settings_uses_paper_defaults_when_settings_empty():
    built = build_paper_settings({})

    assert built["starting_balance"] == DEFAULT_SETTINGS["PAPER_STARTING_BALANCE"]
    assert built["commission"] == DEFAULT_SETTINGS["PAPER_COMMISSION"]
    assert built["process_queue"] == DEFAULT_SETTINGS["PAPER_PROCESS_QUEUE"]
    assert built["process_queue"] is False


def test_build_paper_settings_honours_injected_settings():
    settings = {
        "PAPER_STARTING_BALANCE": 25000,
        "PAPER_COMMISSION": 2.0,
        "PAPER_PROCESS_QUEUE": True,
        "PAPER_MAX_OPEN_POSITIONS": 4,
    }

    built = build_paper_settings(settings)

    assert built["starting_balance"] == 25000
    assert built["commission"] == 2.0
    assert built["process_queue"] is True
    assert built["max_open_positions"] == 4


# ---------------------------------------------------------------------------
# run_paper_trading
# ---------------------------------------------------------------------------

def test_run_paper_trading_routes_to_service():
    fake_service = FakePaperTradingService()

    result = run_paper_trading(make_context(), service=fake_service)

    assert result.mode is RuntimeMode.PAPER
    assert result.status == "completed"
    assert len(fake_service.received_process_queue_kwargs) == 1


def test_run_paper_trading_defaults_queue_processing_to_false():
    fake_service = FakePaperTradingService()

    run_paper_trading(make_context(), service=fake_service)

    assert fake_service.received_process_queue_kwargs[0]["enabled"] is False


def test_run_paper_trading_honours_explicit_queue_processing_setting():
    fake_service = FakePaperTradingService()
    settings = {"PAPER_PROCESS_QUEUE": True}

    run_paper_trading(make_context(settings), service=fake_service)

    assert fake_service.received_process_queue_kwargs[0]["enabled"] is True


def test_run_paper_trading_returns_concise_summary():
    account = make_account(cash=8000.0, equity=8500.0, realised_pnl=50.0, unrealised_pnl=25.0)
    fake_service = FakePaperTradingService(account=account)

    result = run_paper_trading(make_context(), service=fake_service)

    assert "$8,000.00" in result.message
    assert "$8,500.00" in result.message
    assert "$50.00" in result.message
    assert "$25.00" in result.message


def test_run_paper_trading_skips_price_updates_without_price_fetch_fn():
    fake_service = FakePaperTradingService(positions=[])

    run_paper_trading(make_context(), service=fake_service)

    assert fake_service.update_positions_calls == []
    assert fake_service.check_exits_calls == []


def test_run_paper_trading_uses_injected_price_fetch_fn():
    from core.services.paper_trading_service import PaperPosition

    position = PaperPosition(
        symbol="AAPL", quantity=10, average_entry_price=100.0, current_price=100.0,
        market_value=1000.0, stop_loss=None, take_profit=None, unrealised_pnl=0.0,
        realised_pnl=0.0, opened_at=None, updated_at="now",
    )
    fake_service = FakePaperTradingService(positions=[position])

    result = run_paper_trading(
        make_context(), service=fake_service, price_fetch_fn=lambda symbol: 123.45
    )

    assert fake_service.update_positions_calls == [{"AAPL": 123.45}]
    assert fake_service.check_exits_calls == [{"AAPL": 123.45}]
    assert result.status == "completed"


def test_run_paper_trading_propagates_controlled_service_errors():
    fake_service = FakePaperTradingService(raises=PaperTradingServiceError("db locked"))

    with pytest.raises(PaperTradingServiceError):
        run_paper_trading(make_context(), service=fake_service)


# ---------------------------------------------------------------------------
# Import-boundary / no-broker guards
# ---------------------------------------------------------------------------

def _imported_modules(module_path):
    tree = ast.parse(module_path.read_text())
    imported = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    return imported


def test_run_paper_trading_never_touches_broker_or_streamlit_modules():
    module_path = Path(__file__).resolve().parents[2] / "core" / "runtime" / "paper_runtime.py"

    for module_name in _imported_modules(module_path):
        assert not module_name.startswith(FORBIDDEN_IMPORT_PREFIXES), (
            f"paper_runtime.py must not import '{module_name}'"
        )


def test_run_paper_trading_makes_no_streamlit_import():
    module_path = Path(__file__).resolve().parents[2] / "core" / "runtime" / "paper_runtime.py"

    assert not any(
        name.startswith("streamlit") for name in _imported_modules(module_path)
    )
