import logging

import pytest

from core.runtime.application import TradingApplication
from core.runtime.context import RuntimeContext
from core.runtime.exceptions import InvalidRuntimeModeError, LiveModeDisabledError
from core.runtime.modes import RuntimeMode
from core.runtime.router import RuntimeResult


class RecordingRouter:
    """Test double that records the context it was routed and returns a fixed result."""

    def __init__(self):
        self.received_context = None

    def route(self, context):
        self.received_context = context
        return RuntimeResult(mode=context.mode, status="not_implemented", message="ok")


@pytest.mark.parametrize(
    "mode_value",
    ["research", "scanner", "backtest", "paper"],
)
def test_run_delegates_to_router_and_returns_its_result(mode_value):
    router = RecordingRouter()
    app = TradingApplication(
        settings={"RUNTIME_MODE": mode_value},
        router=router,
        logger=logging.getLogger("test.trading_application"),
    )

    result = app.run()

    assert result.status == "not_implemented"
    assert result.mode is RuntimeMode(mode_value)
    assert router.received_context is not None


def test_missing_runtime_mode_falls_back_to_research():
    router = RecordingRouter()
    app = TradingApplication(settings={}, router=router)

    app.run()

    assert router.received_context.mode is RuntimeMode.RESEARCH


def test_invalid_runtime_mode_raises_before_routing():
    router = RecordingRouter()
    app = TradingApplication(settings={"RUNTIME_MODE": "not_a_real_mode"}, router=router)

    with pytest.raises(InvalidRuntimeModeError):
        app.run()

    assert router.received_context is None


def test_live_mode_is_refused_end_to_end():
    app = TradingApplication(settings={"RUNTIME_MODE": "live"})

    with pytest.raises(LiveModeDisabledError):
        app.run()


def test_run_creates_a_well_formed_runtime_context():
    router = RecordingRouter()
    settings = {"RUNTIME_MODE": "research", "STARTING_BALANCE": 100000}
    app = TradingApplication(settings=settings, router=router)

    app.run()

    context = router.received_context
    assert isinstance(context, RuntimeContext)
    assert context.settings is settings
    assert context.mode is RuntimeMode.RESEARCH
    assert isinstance(context.logger, logging.Logger)


def test_default_router_and_logger_are_created_when_not_injected():
    app = TradingApplication(settings={"RUNTIME_MODE": "research"})

    result = app.run()

    assert result.mode is RuntimeMode.RESEARCH
    assert result.status == "not_implemented"
