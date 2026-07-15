import ast
import logging
from pathlib import Path

import pytest

from core.runtime.context import RuntimeContext
from core.runtime.exceptions import LiveModeDisabledError, UnsupportedRuntimeModeError
from core.runtime.modes import RuntimeMode
from core.runtime.router import RuntimeResult, RuntimeRouter

FORBIDDEN_IMPORT_PREFIXES = (
    "core.broker",
    "core.execution",
    "core.risk",
    "core.scanner",
    "core.alpha",
    "core.regime",
    "core.indicators",
    "core.portfolio",
    "core.strategy",
    "core.database",
    "core.market_data",
    "pages",
    "dashboard",
    "ib_insync",
)


def make_context(mode):
    return RuntimeContext(
        settings={"RUNTIME_MODE": mode.value},
        mode=mode,
        logger=logging.getLogger("test.runtime_router"),
    )


@pytest.mark.parametrize(
    "mode",
    [RuntimeMode.RESEARCH, RuntimeMode.PAPER],
)
def test_route_returns_not_implemented_result_for_placeholder_modes(mode):
    router = RuntimeRouter()

    result = router.route(make_context(mode))

    assert result.mode is mode
    assert result.status == "not_implemented"
    assert mode.value in result.message


def test_route_raises_unsupported_for_optimisation():
    router = RuntimeRouter()

    with pytest.raises(UnsupportedRuntimeModeError):
        router.route(make_context(RuntimeMode.OPTIMISATION))


def test_route_always_refuses_live_mode():
    router = RuntimeRouter()

    with pytest.raises(LiveModeDisabledError):
        router.route(make_context(RuntimeMode.LIVE))


def test_route_scanner_mode_delegates_to_scanner_runtime(monkeypatch):
    """SCANNER must no longer be a placeholder: routing it should call the
    dedicated scanner-runtime coordinator rather than RuntimeRouter itself
    implementing scanner logic."""
    import core.runtime.scanner_runtime as scanner_runtime

    calls = []

    def fake_run_scanner(context):
        calls.append(context)
        return RuntimeResult(mode=RuntimeMode.SCANNER, status="completed", message="ok")

    monkeypatch.setattr(scanner_runtime, "run_scanner", fake_run_scanner)

    router = RuntimeRouter()
    context = make_context(RuntimeMode.SCANNER)

    result = router.route(context)

    assert len(calls) == 1
    assert calls[0] is context
    assert result.status == "completed"


def test_route_backtest_mode_delegates_to_backtest_runtime(monkeypatch):
    """BACKTEST must no longer be a placeholder: routing it should call the
    dedicated backtest-runtime coordinator rather than RuntimeRouter itself
    implementing backtest logic."""
    import core.runtime.backtest_runtime as backtest_runtime

    calls = []

    def fake_run_backtest(context):
        calls.append(context)
        return RuntimeResult(mode=RuntimeMode.BACKTEST, status="completed", message="ok")

    monkeypatch.setattr(backtest_runtime, "run_backtest", fake_run_backtest)

    router = RuntimeRouter()
    context = make_context(RuntimeMode.BACKTEST)

    result = router.route(context)

    assert len(calls) == 1
    assert calls[0] is context
    assert result.status == "completed"


def test_router_module_imports_no_broker_or_execution_path():
    """Statically proves the router cannot reach broker/execution code.

    Live-mode refusal (and every other route) must be a pure configuration
    check. This inspects the router's own import statements rather than
    relying on runtime behaviour, so it also catches future modes that would
    accidentally introduce a trading dependency into the router.
    """
    router_source_path = Path(__file__).resolve().parents[2] / "core" / "runtime" / "router.py"
    tree = ast.parse(router_source_path.read_text())

    imported_modules = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    for module_name in imported_modules:
        assert not module_name.startswith(FORBIDDEN_IMPORT_PREFIXES), (
            f"router.py must not import '{module_name}'"
        )
