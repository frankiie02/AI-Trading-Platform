import ast
from pathlib import Path

import pandas as pd
import pytest

from core.pipeline.models import ScanStrategyMode, TradingPipelineRequest
from core.pipeline.trading_pipeline import (
    InsufficientDataError,
    PipelineEvaluationError,
    TradingPipeline,
)
from core.regime.market_state import MarketState

FORBIDDEN_IMPORT_PREFIXES = (
    "streamlit",
    "pages",
    "dashboard",
    "core.broker",
    "core.runtime",
    "core.database",
    "core.scanner.scanner_repository",
    "core.execution.trade_queue",
    "core.market_data",
    "ib_insync",
)


def make_price_frame(
    close=100.0,
    atr=2.0,
    rsi=60.0,
    signal=1,
    confidence=80,
    reason="Trend confirmed",
    trend=True,
    momentum=True,
    volume=True,
    with_nan=False,
):
    row = {
        "Close": [close],
        "ATR": [atr],
        "RSI": [rsi],
        "Signal": [signal],
        "Signal Confidence": [confidence],
        "Signal Reason": [reason],
        "Trend Filter": [trend],
        "Momentum Filter": [momentum],
        "Volume Filter": [volume],
    }

    if with_nan:
        row["ATR"] = [None]

    return pd.DataFrame(row)


def make_voting_price_frame(
    close=100.0,
    atr=2.0,
    rsi=60.0,
    short_ema=25.0,
    long_ema=20.0,
    volume=2_000_000,
    volume_average=1_000_000,
):
    return pd.DataFrame({
        "Close": [close],
        "ATR": [atr],
        "RSI": [rsi],
        "Short EMA": [short_ema],
        "Long EMA": [long_ema],
        "Volume": [volume],
        "Volume Average": [volume_average],
    })


def identity_strategy_fn(df, strategy_name, short_ema, long_ema, rsi_threshold, use_volume_filter):
    return df


def fixed_regime_detector(regime=MarketState.BULL):
    def _detector(df):
        return regime

    return _detector


def fixed_regime_allowance_fn(allowed=True):
    def _allowance(strategy_name, regime):
        return allowed

    return _allowance


def fixed_alpha_score_fn(score=80, reasons="Strong alpha"):
    def _score(row):
        return score, reasons

    return _score


def fixed_alpha_grade_fn(grade="A"):
    def _grade(score):
        return grade

    return _grade


def simple_queue_eligibility_fn(signal, alpha_score, minimum_score):
    return signal == "BUY" and alpha_score >= minimum_score


def fixed_stop_loss_fn(offset=5.0):
    def _stop_loss(entry_price, atr, atr_multiplier):
        return entry_price - offset

    return _stop_loss


def fixed_take_profit_fn(offset=10.0):
    def _take_profit(entry_price, stop_loss_price, reward_risk_ratio):
        return entry_price + offset

    return _take_profit


def fixed_position_size_fn(shares=10, risk_amount=100.0):
    def _position_size(account_balance, entry_price, stop_loss_price, risk_percent):
        return shares, risk_amount

    return _position_size


def default_vote_result():
    return {
        "final_signal": "BUY",
        "vote_score": 75.0,
        "buy_votes": 3,
        "total_votes": 4,
        "confidence": 78.5,
        "reasons": "EMA Trend: Trend confirmed | MACD Momentum: Momentum confirmed",
        "strategy_votes": [
            {"Strategy": "EMA Trend", "Signal": "BUY", "Confidence": 80, "Reason": "Trend confirmed"},
            {"Strategy": "MACD Momentum", "Signal": "BUY", "Confidence": 82, "Reason": "Momentum confirmed"},
            {"Strategy": "Breakout", "Signal": "BUY", "Confidence": 85, "Reason": "Breakout confirmed"},
            {"Strategy": "RSI Pullback", "Signal": "NO TRADE", "Confidence": 0, "Reason": "No trade"},
        ],
    }


def named_regime_allowance_fn(allowed_names):
    def _allowance(strategy_name, regime):
        return strategy_name in allowed_names

    return _allowance


def build_pipeline(
    strategy_fn=identity_strategy_fn,
    voting_fn=None,
    indicator_pipeline_fn=None,
    regime_detector=None,
    regime_allowance_fn=None,
    alpha_score_fn=None,
    alpha_grade_fn=None,
    queue_eligibility_fn=simple_queue_eligibility_fn,
    stop_loss_fn=None,
    take_profit_fn=None,
    position_size_fn=None,
):
    default_indicator_pipeline_fn = (
        lambda df, short_ema, long_ema: make_voting_price_frame()
    )
    default_voting_fn = (
        lambda df, short_ema, long_ema, rsi_threshold, use_volume_filter: default_vote_result()
    )

    return TradingPipeline(
        strategy_fn=strategy_fn,
        voting_fn=voting_fn or default_voting_fn,
        indicator_pipeline_fn=indicator_pipeline_fn or default_indicator_pipeline_fn,
        regime_detector=regime_detector or fixed_regime_detector(),
        regime_allowance_fn=regime_allowance_fn or fixed_regime_allowance_fn(),
        alpha_score_fn=alpha_score_fn or fixed_alpha_score_fn(),
        alpha_grade_fn=alpha_grade_fn or fixed_alpha_grade_fn(),
        queue_eligibility_fn=queue_eligibility_fn,
        stop_loss_fn=stop_loss_fn or fixed_stop_loss_fn(),
        take_profit_fn=take_profit_fn or fixed_take_profit_fn(),
        position_size_fn=position_size_fn or fixed_position_size_fn(),
    )


def build_request(
    symbol="AAPL",
    data=None,
    strategy_mode=ScanStrategyMode.SINGLE,
    strategy_name="EMA Trend",
    use_regime_filter=True,
    minimum_alpha_score=70,
    account_balance=100000,
):
    return TradingPipelineRequest(
        symbol=symbol,
        data=data if data is not None else make_price_frame(),
        strategy_mode=strategy_mode,
        strategy_name=strategy_name,
        use_regime_filter=use_regime_filter,
        minimum_alpha_score=minimum_alpha_score,
        account_balance=account_balance,
    )


# ---------------------------------------------------------------------------
# Successful evaluation - single strategy
# ---------------------------------------------------------------------------

def test_successful_single_strategy_evaluation():
    pipeline = build_pipeline()
    request = build_request()

    decision = pipeline.evaluate(request)

    assert decision.status == "OK"
    assert decision.symbol == "AAPL"
    assert decision.strategy_mode == ScanStrategyMode.SINGLE
    assert decision.strategy_name == "EMA Trend"
    assert decision.raw_signal == "BUY"
    assert decision.final_signal == "BUY"


def test_single_mode_is_backward_compatible_default():
    request = TradingPipelineRequest(symbol="AAPL", data=make_price_frame())

    assert request.strategy_mode == ScanStrategyMode.SINGLE


def test_single_strategy_invokes_strategy_fn_with_expected_arguments():
    received = {}

    def strategy_fn(df, strategy_name, short_ema, long_ema, rsi_threshold, use_volume_filter):
        received["strategy_name"] = strategy_name
        received["short_ema"] = short_ema
        received["long_ema"] = long_ema
        received["rsi_threshold"] = rsi_threshold
        received["use_volume_filter"] = use_volume_filter
        return df

    pipeline = build_pipeline(strategy_fn=strategy_fn)
    request = TradingPipelineRequest(
        symbol="AAPL",
        data=make_price_frame(),
        strategy_name="RSI Pullback",
        short_ema=10,
        long_ema=30,
        rsi_threshold=40,
        use_volume_filter=False,
    )

    pipeline.evaluate(request)

    assert received == {
        "strategy_name": "RSI Pullback",
        "short_ema": 10,
        "long_ema": 30,
        "rsi_threshold": 40,
        "use_volume_filter": False,
    }


def test_single_strategy_does_not_call_voting_fn():
    calls = {"voting": 0}

    def voting_fn(df, short_ema, long_ema, rsi_threshold, use_volume_filter):
        calls["voting"] += 1
        return default_vote_result()

    pipeline = build_pipeline(voting_fn=voting_fn)
    request = build_request(strategy_mode=ScanStrategyMode.SINGLE)

    pipeline.evaluate(request)

    assert calls["voting"] == 0


# ---------------------------------------------------------------------------
# Successful evaluation - voting
# ---------------------------------------------------------------------------

def test_successful_voting_evaluation():
    pipeline = build_pipeline()
    request = build_request(strategy_mode=ScanStrategyMode.VOTING)

    decision = pipeline.evaluate(request)

    assert decision.status == "OK"
    assert decision.strategy_mode == ScanStrategyMode.VOTING
    assert decision.vote_score == 75.0
    assert decision.buy_votes == 3
    assert decision.total_votes == 4
    assert len(decision.strategy_votes) == 4


def test_voting_invokes_voting_fn_with_expected_arguments():
    received = {}

    def voting_fn(df, short_ema, long_ema, rsi_threshold, use_volume_filter):
        received["short_ema"] = short_ema
        received["long_ema"] = long_ema
        received["rsi_threshold"] = rsi_threshold
        received["use_volume_filter"] = use_volume_filter
        return default_vote_result()

    pipeline = build_pipeline(voting_fn=voting_fn)
    request = TradingPipelineRequest(
        symbol="AAPL",
        data=make_price_frame(),
        strategy_mode=ScanStrategyMode.VOTING,
        short_ema=12,
        long_ema=26,
        rsi_threshold=50,
        use_volume_filter=True,
    )

    pipeline.evaluate(request)

    assert received == {
        "short_ema": 12,
        "long_ema": 26,
        "rsi_threshold": 50,
        "use_volume_filter": True,
    }


def test_voting_does_not_call_single_strategy_fn():
    calls = {"single": 0}

    def strategy_fn(df, strategy_name, short_ema, long_ema, rsi_threshold, use_volume_filter):
        calls["single"] += 1
        return df

    pipeline = build_pipeline(strategy_fn=strategy_fn)
    request = build_request(strategy_mode=ScanStrategyMode.VOTING)

    pipeline.evaluate(request)

    assert calls["single"] == 0


def test_indicator_pipeline_called_exactly_once_in_voting_mode():
    calls = {"n": 0}

    def indicator_pipeline_fn(df, short_ema, long_ema):
        calls["n"] += 1
        return make_voting_price_frame()

    pipeline = build_pipeline(indicator_pipeline_fn=indicator_pipeline_fn)
    request = build_request(strategy_mode=ScanStrategyMode.VOTING)

    pipeline.evaluate(request)

    assert calls["n"] == 1


def test_indicator_pipeline_collaborator_not_called_directly_in_single_mode():
    """In single mode, indicator enrichment happens inside strategy_fn
    (generate_strategy_signals) - the pipeline itself never calls the
    injected indicator_pipeline_fn directly."""
    calls = {"n": 0}

    def indicator_pipeline_fn(df, short_ema, long_ema):
        calls["n"] += 1
        return make_voting_price_frame()

    pipeline = build_pipeline(indicator_pipeline_fn=indicator_pipeline_fn)
    request = build_request(strategy_mode=ScanStrategyMode.SINGLE)

    pipeline.evaluate(request)

    assert calls["n"] == 0


# ---------------------------------------------------------------------------
# Insufficient / missing data
# ---------------------------------------------------------------------------

def test_insufficient_data_raises_insufficient_data_error_single_mode():
    pipeline = build_pipeline()
    request = build_request(data=make_price_frame(with_nan=True))

    with pytest.raises(InsufficientDataError, match="Not enough indicator history"):
        pipeline.evaluate(request)


def test_insufficient_data_raises_insufficient_data_error_voting_mode():
    def indicator_pipeline_fn(df, short_ema, long_ema):
        return pd.DataFrame({"Close": [None]})

    pipeline = build_pipeline(indicator_pipeline_fn=indicator_pipeline_fn)
    request = build_request(strategy_mode=ScanStrategyMode.VOTING)

    with pytest.raises(InsufficientDataError):
        pipeline.evaluate(request)


def test_missing_required_columns_raises_pipeline_evaluation_error():
    pipeline = build_pipeline()
    request = build_request(data=pd.DataFrame({"Close": [100.0]}))

    with pytest.raises(PipelineEvaluationError):
        pipeline.evaluate(request)


# ---------------------------------------------------------------------------
# Strategy / voting exceptions
# ---------------------------------------------------------------------------

def test_strategy_exception_raises_pipeline_evaluation_error():
    def failing_strategy_fn(df, strategy_name, short_ema, long_ema, rsi_threshold, use_volume_filter):
        raise ValueError("bad indicator params")

    pipeline = build_pipeline(strategy_fn=failing_strategy_fn)
    request = build_request()

    with pytest.raises(PipelineEvaluationError, match="Strategy signal generation failed."):
        pipeline.evaluate(request)


def test_voting_exception_raises_pipeline_evaluation_error():
    def failing_voting_fn(df, short_ema, long_ema, rsi_threshold, use_volume_filter):
        raise ValueError("voting blew up")

    pipeline = build_pipeline(voting_fn=failing_voting_fn)
    request = build_request(strategy_mode=ScanStrategyMode.VOTING)

    with pytest.raises(PipelineEvaluationError, match="Strategy voting failed."):
        pipeline.evaluate(request)


def test_indicator_enrichment_exception_raises_pipeline_evaluation_error():
    def failing_indicator_pipeline_fn(df, short_ema, long_ema):
        raise ValueError("enrichment blew up")

    pipeline = build_pipeline(indicator_pipeline_fn=failing_indicator_pipeline_fn)
    request = build_request(strategy_mode=ScanStrategyMode.VOTING)

    with pytest.raises(PipelineEvaluationError, match="Indicator enrichment failed."):
        pipeline.evaluate(request)


# ---------------------------------------------------------------------------
# Regime filter enabled / disabled, single-strategy approval / rejection
# ---------------------------------------------------------------------------

def test_single_strategy_regime_approval_allows_buy():
    pipeline = build_pipeline(
        regime_allowance_fn=fixed_regime_allowance_fn(allowed=True),
        alpha_score_fn=fixed_alpha_score_fn(score=90),
    )
    request = build_request(use_regime_filter=True, minimum_alpha_score=70)

    decision = pipeline.evaluate(request)

    assert decision.strategy_allowed is True
    assert decision.final_signal == "BUY"


def test_single_strategy_regime_rejection_blocks_buy():
    pipeline = build_pipeline(
        regime_allowance_fn=fixed_regime_allowance_fn(allowed=False),
        alpha_score_fn=fixed_alpha_score_fn(score=90),
    )
    request = build_request(use_regime_filter=True, minimum_alpha_score=70)

    decision = pipeline.evaluate(request)

    assert decision.strategy_allowed is False
    assert decision.final_signal == "NO TRADE"


def test_regime_filter_disabled_ignores_regime_rejection():
    pipeline = build_pipeline(
        regime_allowance_fn=fixed_regime_allowance_fn(allowed=False),
        alpha_score_fn=fixed_alpha_score_fn(score=90),
    )
    request = build_request(use_regime_filter=False, minimum_alpha_score=70)

    decision = pipeline.evaluate(request)

    assert decision.final_signal == "BUY"


# ---------------------------------------------------------------------------
# Voting regime permission - zero / half / majority
# ---------------------------------------------------------------------------

def test_voting_zero_buy_votes_fails_regime_gate():
    def voting_fn(df, short_ema, long_ema, rsi_threshold, use_volume_filter):
        return {
            "final_signal": "NO TRADE",
            "vote_score": 0,
            "buy_votes": 0,
            "total_votes": 4,
            "confidence": 0,
            "reasons": "No consensus",
            "strategy_votes": [
                {"Strategy": "EMA Trend", "Signal": "NO TRADE", "Confidence": 0, "Reason": "flat"},
            ],
        }

    pipeline = build_pipeline(voting_fn=voting_fn, alpha_score_fn=fixed_alpha_score_fn(score=90))
    request = build_request(strategy_mode=ScanStrategyMode.VOTING, minimum_alpha_score=70)

    decision = pipeline.evaluate(request)

    assert decision.strategy_allowed is False


def test_voting_exactly_half_allowed_fails_strict_majority():
    def voting_fn(df, short_ema, long_ema, rsi_threshold, use_volume_filter):
        return {
            "final_signal": "BUY",
            "vote_score": 50.0,
            "buy_votes": 2,
            "total_votes": 4,
            "confidence": 70.0,
            "reasons": "EMA Trend: bullish | Breakout: confirmed",
            "strategy_votes": [
                {"Strategy": "EMA Trend", "Signal": "BUY", "Confidence": 80, "Reason": "bullish"},
                {"Strategy": "Breakout", "Signal": "BUY", "Confidence": 85, "Reason": "confirmed"},
            ],
        }

    pipeline = build_pipeline(
        voting_fn=voting_fn,
        regime_allowance_fn=named_regime_allowance_fn({"EMA Trend"}),
        alpha_score_fn=fixed_alpha_score_fn(score=90),
    )
    request = build_request(
        strategy_mode=ScanStrategyMode.VOTING, use_regime_filter=True, minimum_alpha_score=70
    )

    decision = pipeline.evaluate(request)

    assert decision.strategy_allowed is False
    assert decision.final_signal == "NO TRADE"


def test_voting_strict_majority_allowed_passes_regime_gate():
    pipeline = build_pipeline(
        regime_allowance_fn=named_regime_allowance_fn({"EMA Trend", "MACD Momentum"}),
        alpha_score_fn=fixed_alpha_score_fn(score=90),
    )
    request = build_request(
        strategy_mode=ScanStrategyMode.VOTING, use_regime_filter=True, minimum_alpha_score=70
    )

    decision = pipeline.evaluate(request)

    assert decision.strategy_allowed is True
    assert decision.final_signal == "BUY"


# ---------------------------------------------------------------------------
# Alpha threshold boundary
# ---------------------------------------------------------------------------

def test_alpha_score_exactly_at_minimum_is_eligible():
    pipeline = build_pipeline(alpha_score_fn=fixed_alpha_score_fn(score=70))
    request = build_request(minimum_alpha_score=70)

    decision = pipeline.evaluate(request)

    assert decision.final_signal == "BUY"


def test_alpha_score_just_below_minimum_is_not_eligible():
    pipeline = build_pipeline(alpha_score_fn=fixed_alpha_score_fn(score=69))
    request = build_request(minimum_alpha_score=70)

    decision = pipeline.evaluate(request)

    assert decision.final_signal == "NO TRADE"


# ---------------------------------------------------------------------------
# Risk values
# ---------------------------------------------------------------------------

def test_risk_values_reach_the_decision_correctly():
    pipeline = build_pipeline(
        stop_loss_fn=fixed_stop_loss_fn(offset=5.0),
        take_profit_fn=fixed_take_profit_fn(offset=10.0),
        position_size_fn=fixed_position_size_fn(shares=42, risk_amount=123.456),
    )
    request = build_request()

    decision = pipeline.evaluate(request)

    assert decision.stop_loss == 95.0
    assert decision.take_profit == 110.0
    assert decision.suggested_shares == 42
    assert decision.dollar_risk == 123.46


def test_zero_share_risk_rejection_behaviour():
    def zero_share_position_size_fn(account_balance, entry_price, stop_loss_price, risk_percent):
        return 0, 100.0

    pipeline = build_pipeline(
        position_size_fn=zero_share_position_size_fn,
        alpha_score_fn=fixed_alpha_score_fn(score=90),
    )
    request = build_request(minimum_alpha_score=70)

    decision = pipeline.evaluate(request)

    assert decision.suggested_shares == 0
    # Zero suggested shares does not itself block the BUY decision - the
    # existing risk formula only surfaces zero shares as informational; it
    # never vetoes the alpha/regime-derived final_signal.
    assert decision.final_signal == "BUY"


# ---------------------------------------------------------------------------
# Queue eligibility
# ---------------------------------------------------------------------------

def test_queue_eligible_true_when_final_signal_is_buy():
    pipeline = build_pipeline(alpha_score_fn=fixed_alpha_score_fn(score=90))
    request = build_request(minimum_alpha_score=70)

    decision = pipeline.evaluate(request)

    assert decision.final_signal == "BUY"
    assert decision.queue_eligible is True


def test_queue_eligible_false_when_final_signal_is_no_trade():
    pipeline = build_pipeline(alpha_score_fn=fixed_alpha_score_fn(score=10))
    request = build_request(minimum_alpha_score=70)

    decision = pipeline.evaluate(request)

    assert decision.final_signal == "NO TRADE"
    assert decision.queue_eligible is False


# ---------------------------------------------------------------------------
# Optional voting metadata
# ---------------------------------------------------------------------------

def test_single_strategy_decision_has_no_voting_metadata():
    pipeline = build_pipeline()
    request = build_request(strategy_mode=ScanStrategyMode.SINGLE)

    decision = pipeline.evaluate(request)

    assert decision.vote_score is None
    assert decision.buy_votes is None
    assert decision.total_votes is None
    assert decision.strategy_votes is None


def test_voting_decision_has_voting_metadata():
    pipeline = build_pipeline()
    request = build_request(strategy_mode=ScanStrategyMode.VOTING)

    decision = pipeline.evaluate(request)

    assert decision.vote_score == 75.0
    assert decision.buy_votes == 3
    assert decision.total_votes == 4
    assert decision.strategy_votes is not None


# ---------------------------------------------------------------------------
# Import-boundary / isolation guarantees
# ---------------------------------------------------------------------------

def _pipeline_module_imports(filename):
    module_path = (
        Path(__file__).resolve().parents[2] / "core" / "pipeline" / filename
    )
    tree = ast.parse(module_path.read_text())

    imported_modules = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    return imported_modules


@pytest.mark.parametrize("filename", ["models.py", "trading_pipeline.py"])
def test_pipeline_modules_have_no_forbidden_imports(filename):
    imported_modules = _pipeline_module_imports(filename)

    for module_name in imported_modules:
        assert not module_name.startswith(FORBIDDEN_IMPORT_PREFIXES), (
            f"{filename} must not import '{module_name}'"
        )


def test_no_real_external_or_database_calls_occur(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("real external/database call was made")

    monkeypatch.setattr("yfinance.download", fail_if_called)
    monkeypatch.setattr("sqlite3.connect", fail_if_called)

    pipeline = build_pipeline()
    request = build_request()

    decision = pipeline.evaluate(request)

    assert decision.status == "OK"
