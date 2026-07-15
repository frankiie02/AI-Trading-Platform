import ast
from pathlib import Path

import pandas as pd
import pytest

from core.pipeline.models import ScanStrategyMode, TradingDecision
from core.pipeline.trading_pipeline import (
    InsufficientDataError,
    PipelineEvaluationError,
)
from core.services.backtest_service import (
    BacktestDataError,
    BacktestRequest,
    BacktestService,
    InvalidBacktestRequestError,
)

FORBIDDEN_IMPORT_PREFIXES = (
    "streamlit",
    "pages",
    "dashboard",
    "core.broker",
    "core.runtime",
    "core.database",
    "core.execution",
    "ib_insync",
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def make_frame(rows, start="2024-01-01"):
    """rows: list of (open, high, low, close) or (open, high, low, close, volume)."""
    dates = pd.date_range(start=start, periods=len(rows), freq="D")

    records = []
    for row in rows:
        if len(row) == 4:
            o, h, l, c = row
            v = 1_000_000
        else:
            o, h, l, c, v = row

        records.append({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v})

    return pd.DataFrame(records, index=dates)


def flat_frame(n, price=100.0, start="2024-01-01"):
    return make_frame([(price, price + 1, price - 1, price)] * n, start=start)


def make_decision(
    final_signal="NO TRADE",
    stop_loss=95.0,
    take_profit=110.0,
    suggested_shares=10,
    confidence=80,
    alpha_score=80,
    symbol="TEST",
    strategy_mode=ScanStrategyMode.SINGLE,
    strategy_name="EMA Trend",
):
    return TradingDecision(
        symbol=symbol,
        strategy_mode=strategy_mode,
        strategy_name=strategy_name,
        raw_signal=final_signal,
        final_signal=final_signal,
        confidence=confidence,
        alpha_score=alpha_score,
        stop_loss=stop_loss,
        take_profit=take_profit,
        suggested_shares=suggested_shares,
        queue_eligible=(final_signal == "BUY"),
    )


class FakePipeline:
    """Test double standing in for TradingPipeline. decision_fn receives the
    TradingPipelineRequest and returns either a TradingDecision or raises."""

    def __init__(self, decision_fn):
        self._decision_fn = decision_fn
        self.received_requests = []

    def evaluate(self, request):
        self.received_requests.append(request)
        result = self._decision_fn(request)

        if isinstance(result, Exception):
            raise result

        return result


def buy_once_at_length(length, **decision_kwargs):
    """Returns BUY exactly when the historical slice reaches `length` rows,
    NO TRADE otherwise - lets tests pin exactly one decision point."""

    def _decision_fn(request):
        if len(request.data) == length:
            return make_decision(final_signal="BUY", **decision_kwargs)
        return make_decision(final_signal="NO TRADE")

    return _decision_fn


def always_no_trade(request):
    return make_decision(final_signal="NO TRADE")


def build_service(decision_fn, market_data_fn=None):
    pipeline = FakePipeline(decision_fn)
    service = BacktestService(
        market_data_fn=market_data_fn or (lambda **kwargs: flat_frame(6)),
        pipeline=pipeline,
    )
    return service, pipeline


def build_request(**overrides):
    defaults = dict(symbol="AAPL", initial_capital=10000.0)
    defaults.update(overrides)
    return BacktestRequest(**defaults)


# ---------------------------------------------------------------------------
# 1. Valid request / smoke test
# ---------------------------------------------------------------------------

def test_valid_request_with_no_trades_preserves_capital():
    service, _ = build_service(always_no_trade)
    request = build_request()

    result = service.run(request)

    assert result.metrics["Total Trades"] == 0
    assert result.metrics["Final Equity"] == 10000.0
    assert result.metrics["Total Return %"] == 0.0
    assert result.trades == []
    assert not result.equity_curve.empty


# ---------------------------------------------------------------------------
# 2. Invalid request
# ---------------------------------------------------------------------------

def test_invalid_initial_capital_raises():
    service, _ = build_service(always_no_trade)

    with pytest.raises(InvalidBacktestRequestError):
        service.run(build_request(initial_capital=0))


def test_negative_initial_capital_raises():
    service, _ = build_service(always_no_trade)

    with pytest.raises(InvalidBacktestRequestError):
        service.run(build_request(initial_capital=-500))


def test_empty_symbol_raises():
    service, _ = build_service(always_no_trade)

    with pytest.raises(InvalidBacktestRequestError):
        service.run(build_request(symbol="  "))


# ---------------------------------------------------------------------------
# 3 / 4. Market data failures
# ---------------------------------------------------------------------------

def test_empty_market_data_raises_backtest_data_error():
    service, _ = build_service(always_no_trade, market_data_fn=lambda **kwargs: pd.DataFrame())

    with pytest.raises(BacktestDataError):
        service.run(build_request())


def test_insufficient_historical_data_raises_backtest_data_error():
    service, _ = build_service(always_no_trade, market_data_fn=lambda **kwargs: flat_frame(2))

    with pytest.raises(BacktestDataError):
        service.run(build_request())


def test_market_data_exception_raises_backtest_data_error():
    def failing_market_data(**kwargs):
        raise ConnectionError("network down")

    service, _ = build_service(always_no_trade, market_data_fn=failing_market_data)

    with pytest.raises(BacktestDataError):
        service.run(build_request())


# ---------------------------------------------------------------------------
# 5 / 6. Single-strategy vs voting decisions flow through unchanged
# ---------------------------------------------------------------------------

def test_single_strategy_mode_is_passed_to_pipeline():
    service, pipeline = build_service(always_no_trade)

    service.run(build_request(strategy_mode=ScanStrategyMode.SINGLE, strategy_name="RSI Pullback"))

    assert pipeline.received_requests
    first = pipeline.received_requests[0]
    assert first.strategy_mode == ScanStrategyMode.SINGLE
    assert first.strategy_name == "RSI Pullback"


def test_voting_mode_is_passed_to_pipeline():
    service, pipeline = build_service(always_no_trade)

    service.run(build_request(strategy_mode=ScanStrategyMode.VOTING))

    assert pipeline.received_requests
    assert pipeline.received_requests[0].strategy_mode == ScanStrategyMode.VOTING


def test_decision_parameters_flow_through_to_pipeline_request():
    service, pipeline = build_service(always_no_trade)

    service.run(build_request(
        short_ema=12,
        long_ema=30,
        rsi_threshold=40,
        use_volume_filter=False,
        use_regime_filter=False,
        risk_percent=2.0,
        atr_multiplier=3.0,
        reward_risk_ratio=1.5,
        minimum_alpha_score=60,
    ))

    req = pipeline.received_requests[0]
    assert req.short_ema == 12
    assert req.long_ema == 30
    assert req.rsi_threshold == 40
    assert req.use_volume_filter is False
    assert req.use_regime_filter is False
    assert req.risk_percent == 2.0
    assert req.atr_multiplier == 3.0
    assert req.reward_risk_ratio == 1.5
    assert req.minimum_alpha_score == 60


# ---------------------------------------------------------------------------
# 8. Anti-lookahead slicing
# ---------------------------------------------------------------------------

def test_pipeline_never_receives_future_bars():
    data = flat_frame(6)
    # Inject an extreme spike far in the future to prove it can't leak backward.
    data.iloc[-1, data.columns.get_loc("Close")] = 999999.0

    service, pipeline = build_service(always_no_trade, market_data_fn=lambda **kwargs: data)
    service.run(build_request())

    for i, request in enumerate(pipeline.received_requests, start=1):
        expected_slice = data.iloc[: i + 1]
        assert len(request.data) == len(expected_slice)
        assert request.data.index[-1] == data.index[i]
        assert request.data.index.max() <= data.index[i]


def test_historical_slice_matches_data_through_current_bar_exactly():
    data = flat_frame(6)
    service, pipeline = build_service(always_no_trade, market_data_fn=lambda **kwargs: data)

    service.run(build_request())

    for i, request in enumerate(pipeline.received_requests, start=1):
        pd.testing.assert_frame_equal(request.data, data.iloc[: i + 1])


# ---------------------------------------------------------------------------
# 9 / 20. Entry timing and trade recording
# ---------------------------------------------------------------------------

def test_entry_executes_at_next_bar_open():
    # Decision made once history has 2 bars (i=1) -> entry at bar index 2's open.
    rows = [
        (100, 101, 99, 100),
        (100, 101, 99, 100),
        (105, 106, 104, 105),  # entry bar
        (105, 106, 104, 105),
        (105, 106, 104, 105),
        (105, 106, 104, 105),
    ]
    data = make_frame(rows)
    decision_fn = buy_once_at_length(2, stop_loss=95.0, take_profit=115.0, suggested_shares=10)

    service, _ = build_service(decision_fn, market_data_fn=lambda **kwargs: data)
    result = service.run(build_request())

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_timestamp == data.index[2]
    assert trade.entry_price == 105.0


# ---------------------------------------------------------------------------
# 11 / 12 / 13. Stop-loss / take-profit / adverse-first collision
# ---------------------------------------------------------------------------

def test_stop_loss_exit_uses_stop_price_and_reason():
    rows = [
        (100, 101, 99, 100),
        (100, 101, 99, 100),   # decision bar (len=2)
        (100, 102, 99, 101),   # entry bar: open=100
        (98, 99, 94, 95),      # stop hit: Low=94 <= 95
        (95, 96, 94, 95),
        (95, 96, 94, 95),
    ]
    data = make_frame(rows)
    decision_fn = buy_once_at_length(2, stop_loss=95.0, take_profit=110.0, suggested_shares=10)

    service, _ = build_service(decision_fn, market_data_fn=lambda **kwargs: data)
    result = service.run(build_request())

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "STOP_LOSS"
    assert trade.exit_price == 95.0
    assert trade.exit_timestamp == data.index[3]
    assert trade.net_pnl == pytest.approx((95.0 - 100.0) * 10)


def test_take_profit_exit_uses_target_price_and_reason():
    rows = [
        (100, 101, 99, 100),
        (100, 101, 99, 100),   # decision bar
        (100, 102, 99, 101),   # entry bar: open=100
        (105, 111, 104, 110),  # target hit: High=111 >= 110
        (110, 111, 109, 110),
        (110, 111, 109, 110),
    ]
    data = make_frame(rows)
    decision_fn = buy_once_at_length(2, stop_loss=95.0, take_profit=110.0, suggested_shares=10)

    service, _ = build_service(decision_fn, market_data_fn=lambda **kwargs: data)
    result = service.run(build_request())

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "TAKE_PROFIT"
    assert trade.exit_price == 110.0


def test_same_bar_stop_and_target_collision_assumes_stop_first():
    rows = [
        (100, 101, 99, 100),
        (100, 101, 99, 100),   # decision bar
        (100, 102, 99, 101),   # entry bar: open=100
        (100, 112, 90, 100),   # both stop (Low=90<=95) and target (High=112>=110) touched
        (100, 101, 99, 100),
        (100, 101, 99, 100),
    ]
    data = make_frame(rows)
    decision_fn = buy_once_at_length(2, stop_loss=95.0, take_profit=110.0, suggested_shares=10)

    service, _ = build_service(decision_fn, market_data_fn=lambda **kwargs: data)
    result = service.run(build_request())

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "STOP_LOSS"
    assert result.trades[0].exit_price == 95.0


# ---------------------------------------------------------------------------
# 14. Final-bar forced close
# ---------------------------------------------------------------------------

def test_open_position_force_closed_at_final_bar():
    rows = [
        (100, 101, 99, 100),
        (100, 101, 99, 100),   # decision bar
        (100, 102, 99, 101),   # entry bar: open=100, never hits stop/target after
        (100, 102, 99, 101),
        (100, 102, 99, 101),
        (100, 102, 99, 108),   # final bar close = 108
    ]
    data = make_frame(rows)
    decision_fn = buy_once_at_length(2, stop_loss=50.0, take_profit=500.0, suggested_shares=10)

    service, _ = build_service(decision_fn, market_data_fn=lambda **kwargs: data)
    result = service.run(build_request())

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "End of backtest period"
    assert trade.exit_timestamp == data.index[-1]
    assert trade.exit_price == 108.0


# ---------------------------------------------------------------------------
# 15. One position at a time
# ---------------------------------------------------------------------------

def test_only_one_position_open_at_a_time():
    def always_buy(request):
        return make_decision(final_signal="BUY", stop_loss=1.0, take_profit=500.0, suggested_shares=1)

    data = flat_frame(8)
    service, pipeline = build_service(always_buy, market_data_fn=lambda **kwargs: data)

    result = service.run(build_request())

    # Pipeline must not be consulted again while a position is already open.
    assert len(result.trades) == 1


# ---------------------------------------------------------------------------
# 16. Position sizing capped by available cash
# ---------------------------------------------------------------------------

def test_position_size_capped_by_available_cash():
    rows = [
        (100, 101, 99, 100),
        (100, 101, 99, 100),
        (100, 102, 99, 101),   # entry bar: open=100
        (100, 102, 99, 101),
        (100, 102, 99, 101),
        (100, 102, 99, 101),
    ]
    data = make_frame(rows)
    # suggested_shares far exceeds what $1000 of capital can buy at $100/share.
    decision_fn = buy_once_at_length(2, stop_loss=1.0, take_profit=500.0, suggested_shares=1000)

    service, _ = build_service(decision_fn, market_data_fn=lambda **kwargs: data)
    result = service.run(build_request(initial_capital=1000.0))

    assert len(result.trades) == 1
    assert result.trades[0].quantity == 10  # floor(1000 / 100)


# ---------------------------------------------------------------------------
# 17 / 18. Commission and slippage
# ---------------------------------------------------------------------------

def test_commission_applied_on_entry_and_exit():
    rows = [
        (100, 101, 99, 100),
        (100, 101, 99, 100),
        (100, 102, 99, 101),   # entry bar: open=100
        (98, 99, 94, 95),      # stop hit at 95
        (95, 96, 94, 95),
        (95, 96, 94, 95),
    ]
    data = make_frame(rows)
    decision_fn = buy_once_at_length(2, stop_loss=95.0, take_profit=110.0, suggested_shares=10)

    service, _ = build_service(decision_fn, market_data_fn=lambda **kwargs: data)
    result = service.run(build_request(commission=2.0))

    trade = result.trades[0]
    assert trade.fees == pytest.approx(4.0)
    assert trade.net_pnl == pytest.approx(trade.gross_pnl - 4.0)


def test_slippage_applied_adversely_on_entry_and_exit():
    rows = [
        (100, 101, 99, 100),
        (100, 101, 99, 100),
        (100, 102, 99, 101),   # entry bar: open=100
        (98, 99, 94, 95),      # stop hit at 95
        (95, 96, 94, 95),
        (95, 96, 94, 95),
    ]
    data = make_frame(rows)
    decision_fn = buy_once_at_length(2, stop_loss=95.0, take_profit=110.0, suggested_shares=10)

    service, _ = build_service(decision_fn, market_data_fn=lambda **kwargs: data)
    result = service.run(build_request(slippage=1.0))

    trade = result.trades[0]
    assert trade.entry_price == pytest.approx(100.0 * 1.01)
    assert trade.exit_price == pytest.approx(95.0 * 0.99)


# ---------------------------------------------------------------------------
# 19 / 21 / 22 / 23 / 24. Cash/equity, total return, drawdown, win rate, profit factor
# ---------------------------------------------------------------------------

def test_full_scenario_metrics_are_computed_correctly():
    rows = [
        (100, 101, 99, 100),
        (100, 101, 99, 100),   # decision bar (len=2)
        (100, 102, 99, 101),   # entry: open=100, qty=10, cash 10000-1000=9000
        (98, 99, 94, 95),      # stop hit @95: proceeds=950, cash=9950
        (95, 96, 94, 95),
        (95, 96, 94, 95),
    ]
    data = make_frame(rows)
    decision_fn = buy_once_at_length(2, stop_loss=95.0, take_profit=110.0, suggested_shares=10)

    service, _ = build_service(decision_fn, market_data_fn=lambda **kwargs: data)
    result = service.run(build_request(initial_capital=10000.0))

    assert result.metrics["Final Equity"] == pytest.approx(9950.0)
    assert result.metrics["Total Return %"] == pytest.approx(-0.5)
    assert result.metrics["Total Trades"] == 1
    assert result.metrics["Win Rate %"] == 0.0
    assert result.metrics["Profit Factor"] == 0.0
    assert result.metrics["Max Drawdown %"] == pytest.approx(-0.5994, abs=0.01)


# ---------------------------------------------------------------------------
# 25. Partial decision failure handling
# ---------------------------------------------------------------------------

def test_insufficient_data_error_is_skipped_without_crashing():
    def decision_fn(request):
        if len(request.data) < 4:
            return InsufficientDataError("warming up")
        return make_decision(final_signal="NO TRADE")

    data = flat_frame(6)
    service, _ = build_service(decision_fn, market_data_fn=lambda **kwargs: data)

    result = service.run(build_request())

    assert result.trades == []
    assert any("Skipped" in warning for warning in result.warnings)


def test_pipeline_evaluation_error_is_isolated_per_bar():
    def decision_fn(request):
        if len(request.data) == 3:
            return PipelineEvaluationError("boom")
        return make_decision(final_signal="NO TRADE")

    data = flat_frame(6)
    service, _ = build_service(decision_fn, market_data_fn=lambda **kwargs: data)

    result = service.run(build_request())

    assert result.trades == []
    assert any("boom" in warning for warning in result.warnings)


# ---------------------------------------------------------------------------
# 26 / 27. No real network or database calls
# ---------------------------------------------------------------------------

def test_no_real_external_or_database_calls_occur(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("real external/database call was made")

    monkeypatch.setattr("yfinance.download", fail_if_called)
    monkeypatch.setattr("sqlite3.connect", fail_if_called)

    service, _ = build_service(always_no_trade)
    result = service.run(build_request())

    assert result.metrics["Total Trades"] == 0


# ---------------------------------------------------------------------------
# 28 / 29. No broker/live/Streamlit import
# ---------------------------------------------------------------------------

def test_backtest_service_has_no_forbidden_imports():
    module_path = (
        Path(__file__).resolve().parents[2] / "core" / "services" / "backtest_service.py"
    )
    tree = ast.parse(module_path.read_text())

    imported_modules = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    for module_name in imported_modules:
        assert not module_name.startswith(FORBIDDEN_IMPORT_PREFIXES), (
            f"backtest_service.py must not import '{module_name}'"
        )


def test_backtest_service_makes_no_streamlit_import():
    module_path = (
        Path(__file__).resolve().parents[2] / "core" / "services" / "backtest_service.py"
    )
    tree = ast.parse(module_path.read_text())

    imported_modules = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    assert not any(name.startswith("streamlit") for name in imported_modules)
