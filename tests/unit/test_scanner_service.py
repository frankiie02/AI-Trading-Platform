import ast
from pathlib import Path

import pandas as pd
import pytest

from core.pipeline.models import ScanStrategyMode as PipelineScanStrategyMode
from core.pipeline.models import TradingDecision
from core.pipeline.trading_pipeline import PipelineEvaluationError, TradingPipeline
from core.regime.market_state import MarketState
from core.services.scanner_service import (
    ScanRequest,
    ScannerPersistenceError,
    ScannerService,
    ScanStrategyMode,
    SymbolScanOutcome,
    TradeQueuePersistenceError,
)

# scanner_service.py must no longer import Streamlit/dashboard/broker/runtime
# code, NOR the individual decision-workflow collaborators (strategy engine,
# voting engine, regime detector/filter, alpha scoring/filters, risk engine,
# indicator pipeline) directly - those now live exclusively behind
# TradingPipeline (core/pipeline/trading_pipeline.py).
FORBIDDEN_IMPORT_PREFIXES = (
    "streamlit",
    "pages",
    "dashboard",
    "core.broker",
    "core.runtime",
    "ib_insync",
)

FORBIDDEN_DIRECT_COLLABORATOR_MODULES = (
    "core.strategy.strategy_engine",
    "core.voting.engine",
    "core.regime.detector",
    "core.regime.filters",
    "core.alpha.scoring",
    "core.alpha.filters",
    "core.risk.risk_engine",
    "core.indicators.pipeline",
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


class RecordingSaveResults:
    def __init__(self, raises=None):
        self.calls = []
        self.raises = raises

    def __call__(self, results):
        self.calls.append(results)

        if self.raises:
            raise self.raises


class RecordingSaveQueue:
    def __init__(self, return_value=0, raises=None):
        self.calls = []
        self.return_value = return_value
        self.raises = raises

    def __call__(self, results):
        self.calls.append(results)

        if self.raises:
            raise self.raises

        return self.return_value


class RecordingRanking:
    def __init__(self):
        self.calls = []

    def __call__(self, results):
        self.calls.append(results)
        return pd.DataFrame(results)


def make_voting_price_frame(
    close=100.0,
    atr=2.0,
    rsi=60.0,
    short_ema=25.0,
    long_ema=20.0,
    volume=2_000_000,
    volume_average=1_000_000,
):
    """Mimics the output of build_indicator_pipeline for voting-mode tests."""
    return pd.DataFrame({
        "Close": [close],
        "ATR": [atr],
        "RSI": [rsi],
        "Short EMA": [short_ema],
        "Long EMA": [long_ema],
        "Volume": [volume],
        "Volume Average": [volume_average],
    })


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


def build_service(
    market_data_fn=None,
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
    save_results_fn=None,
    save_queue_fn=None,
    ranking_fn=None,
    pipeline=None,
):
    default_market_data_fn = (
        lambda symbol, period, interval, auto_adjust: make_price_frame()
    )

    pipeline = pipeline or build_pipeline(
        strategy_fn=strategy_fn,
        voting_fn=voting_fn,
        indicator_pipeline_fn=indicator_pipeline_fn,
        regime_detector=regime_detector,
        regime_allowance_fn=regime_allowance_fn,
        alpha_score_fn=alpha_score_fn,
        alpha_grade_fn=alpha_grade_fn,
        queue_eligibility_fn=queue_eligibility_fn,
        stop_loss_fn=stop_loss_fn,
        take_profit_fn=take_profit_fn,
        position_size_fn=position_size_fn,
    )

    return ScannerService(
        market_data_fn=market_data_fn or default_market_data_fn,
        pipeline=pipeline,
        save_results_fn=save_results_fn or RecordingSaveResults(),
        save_queue_fn=save_queue_fn or RecordingSaveQueue(),
        ranking_fn=ranking_fn or RecordingRanking(),
        account_balance=100000,
    )


def make_decision(symbol="AAPL", **overrides):
    defaults = dict(
        symbol=symbol,
        status="OK",
        strategy_mode=PipelineScanStrategyMode.SINGLE,
        strategy_name="EMA Trend",
        raw_signal="BUY",
        final_signal="BUY",
        confidence=80,
        signal_reason="Trend confirmed",
        regime="Bull",
        strategy_allowed=True,
        regime_reason="EMA Trend is allowed in Bull market.",
        alpha_score=80,
        alpha_grade="A",
        alpha_reasons="Strong alpha",
        current_price=100.0,
        rsi=60.0,
        atr=2.0,
        trend=True,
        momentum=True,
        volume=True,
        stop_loss=95.0,
        take_profit=110.0,
        suggested_shares=10,
        dollar_risk=100.0,
        queue_eligible=True,
    )
    defaults.update(overrides)
    return TradingDecision(**defaults)


class FakePipeline:
    """Test double standing in for TradingPipeline, used by the delegation
    and per-symbol-isolation regression tests below."""

    def __init__(self, per_call=None, decision=None, raises=None):
        self.received_requests = []
        self._per_call = per_call
        self._decision = decision
        self._raises = raises

    def evaluate(self, request):
        self.received_requests.append(request)

        if self._per_call is not None:
            return self._per_call(request)

        if self._raises is not None:
            raise self._raises

        return self._decision or make_decision(symbol=request.symbol)


# ---------------------------------------------------------------------------
# ScanRequest normalisation
# ---------------------------------------------------------------------------

def test_symbol_normalisation_trims_upcases_dedupes_and_preserves_order():
    request = ScanRequest(symbols=[" aapl ", "AAPL", "", "  ", "msft", " MSFT ", "tsla"])

    assert request.symbols == ["AAPL", "MSFT", "TSLA"]


# ---------------------------------------------------------------------------
# Successful scans
# ---------------------------------------------------------------------------

def test_successful_single_symbol_scan():
    save_results = RecordingSaveResults()
    service = build_service(save_results_fn=save_results)
    request = ScanRequest(symbols=["AAPL"])

    result = service.scan(request)

    assert len(result.outcomes) == 1
    outcome = result.outcomes[0]
    assert isinstance(outcome, SymbolScanOutcome)
    assert outcome.symbol == "AAPL"
    assert outcome.status == "OK"
    assert outcome.final_signal == "BUY"
    assert save_results.calls == [result.legacy_results]


def test_successful_multi_symbol_scan_processes_all_symbols():
    service = build_service()
    request = ScanRequest(symbols=["AAPL", "MSFT", "TSLA"])

    result = service.scan(request)

    assert [o.symbol for o in result.outcomes] == ["AAPL", "MSFT", "TSLA"]
    assert all(o.status == "OK" for o in result.outcomes)


def test_outcome_order_is_deterministic_and_matches_request_order():
    service = build_service()
    request = ScanRequest(symbols=["TSLA", "AAPL", "MSFT"])

    result = service.scan(request)

    assert [o.symbol for o in result.outcomes] == ["TSLA", "AAPL", "MSFT"]


# ---------------------------------------------------------------------------
# Controlled error outcomes
# ---------------------------------------------------------------------------

def test_empty_market_data_produces_controlled_error_outcome():
    service = build_service(
        market_data_fn=lambda symbol, period, interval, auto_adjust: pd.DataFrame()
    )
    request = ScanRequest(symbols=["AAPL"])

    result = service.scan(request)

    outcome = result.outcomes[0]
    assert outcome.status == "ERROR"
    assert outcome.final_signal == "NO DATA"
    legacy = outcome.to_legacy_dict()
    assert legacy["Signal"] == "NO DATA"
    assert legacy["Reason"] == "No data returned"
    assert legacy["Regime Reason"] == "No data available"


def test_market_data_exception_isolated_other_symbols_still_succeed():
    def flaky_market_data_fn(symbol, period, interval, auto_adjust):
        if symbol == "BAD":
            raise ConnectionError("network down")
        return make_price_frame()

    service = build_service(market_data_fn=flaky_market_data_fn)
    request = ScanRequest(symbols=["BAD", "AAPL"])

    result = service.scan(request)

    bad_outcome, good_outcome = result.outcomes
    assert bad_outcome.status == "ERROR"
    assert bad_outcome.final_signal == "SCAN ERROR"
    assert good_outcome.status == "OK"


def test_insufficient_usable_data_produces_controlled_error_outcome():
    service = build_service(
        market_data_fn=lambda symbol, period, interval, auto_adjust: make_price_frame(with_nan=True)
    )
    request = ScanRequest(symbols=["AAPL"])

    result = service.scan(request)

    outcome = result.outcomes[0]
    assert outcome.status == "ERROR"
    assert outcome.final_signal == "NOT ENOUGH DATA"
    assert outcome.to_legacy_dict()["Reason"] == "Not enough indicator history"


def test_strategy_generation_exception_produces_controlled_error_outcome():
    def failing_strategy_fn(
        df, strategy_name, short_ema, long_ema, rsi_threshold, use_volume_filter
    ):
        raise ValueError("bad indicator params")

    service = build_service(strategy_fn=failing_strategy_fn)
    request = ScanRequest(symbols=["AAPL"])

    result = service.scan(request)

    outcome = result.outcomes[0]
    assert outcome.status == "ERROR"
    assert outcome.final_signal == "SCAN ERROR"


# ---------------------------------------------------------------------------
# Pipeline delegation and per-symbol isolation
# ---------------------------------------------------------------------------

def test_scan_symbol_delegates_to_trading_pipeline_with_expected_request_fields():
    pipeline = FakePipeline(per_call=lambda request: make_decision(symbol=request.symbol))
    service = ScannerService(
        market_data_fn=lambda symbol, period, interval, auto_adjust: make_price_frame(),
        pipeline=pipeline,
        save_results_fn=RecordingSaveResults(),
        save_queue_fn=RecordingSaveQueue(),
        ranking_fn=RecordingRanking(),
        account_balance=55000,
    )
    request = ScanRequest(
        symbols=["AAPL"],
        strategy_name="RSI Pullback",
        strategy_mode=ScanStrategyMode.VOTING,
        short_ema=10,
        long_ema=30,
        rsi_threshold=40,
        use_volume_filter=False,
        use_regime_filter=False,
        risk_percent=2.0,
        atr_multiplier=3.0,
        reward_risk_ratio=1.5,
        minimum_alpha_score=60,
    )

    service.scan(request)

    assert len(pipeline.received_requests) == 1
    pipeline_request = pipeline.received_requests[0]
    assert pipeline_request.symbol == "AAPL"
    assert pipeline_request.strategy_mode == PipelineScanStrategyMode.VOTING
    assert pipeline_request.strategy_name == "RSI Pullback"
    assert pipeline_request.short_ema == 10
    assert pipeline_request.long_ema == 30
    assert pipeline_request.rsi_threshold == 40
    assert pipeline_request.use_volume_filter is False
    assert pipeline_request.use_regime_filter is False
    assert pipeline_request.account_balance == 55000
    assert pipeline_request.risk_percent == 2.0
    assert pipeline_request.atr_multiplier == 3.0
    assert pipeline_request.reward_risk_ratio == 1.5
    assert pipeline_request.minimum_alpha_score == 60


def test_pipeline_result_is_mapped_into_symbol_scan_outcome():
    decision = make_decision(
        symbol="AAPL",
        final_signal="BUY",
        confidence=77,
        alpha_score=91,
        alpha_grade="A+",
        stop_loss=88.0,
        take_profit=120.0,
        suggested_shares=12,
        dollar_risk=250.0,
    )
    pipeline = FakePipeline(decision=decision)
    service = ScannerService(
        market_data_fn=lambda symbol, period, interval, auto_adjust: make_price_frame(),
        pipeline=pipeline,
        save_results_fn=RecordingSaveResults(),
        save_queue_fn=RecordingSaveQueue(),
        ranking_fn=RecordingRanking(),
    )
    request = ScanRequest(symbols=["AAPL"])

    result = service.scan(request)

    outcome = result.outcomes[0]
    assert outcome.confidence == 77
    assert outcome.alpha_score == 91
    assert outcome.alpha_grade == "A+"
    assert outcome.stop_loss == 88.0
    assert outcome.take_profit == 120.0
    assert outcome.suggested_shares == 12
    assert outcome.dollar_risk == 250.0


def test_pipeline_failure_for_one_symbol_does_not_stop_other_symbols():
    def flaky_evaluate(request):
        if request.symbol == "BAD":
            raise PipelineEvaluationError("boom")
        return make_decision(symbol=request.symbol)

    pipeline = FakePipeline(per_call=flaky_evaluate)
    service = ScannerService(
        market_data_fn=lambda symbol, period, interval, auto_adjust: make_price_frame(),
        pipeline=pipeline,
        save_results_fn=RecordingSaveResults(),
        save_queue_fn=RecordingSaveQueue(),
        ranking_fn=RecordingRanking(),
    )
    request = ScanRequest(symbols=["BAD", "AAPL"])

    result = service.scan(request)

    bad_outcome, good_outcome = result.outcomes
    assert bad_outcome.status == "ERROR"
    assert bad_outcome.final_signal == "SCAN ERROR"
    assert bad_outcome.signal_reason == "boom"
    assert good_outcome.status == "OK"


# ---------------------------------------------------------------------------
# Regime filter behaviour
# ---------------------------------------------------------------------------

def test_regime_filter_blocks_buy_when_strategy_not_allowed():
    service = build_service(
        regime_allowance_fn=fixed_regime_allowance_fn(allowed=False),
        alpha_score_fn=fixed_alpha_score_fn(score=90),
    )
    request = ScanRequest(symbols=["AAPL"], use_regime_filter=True, minimum_alpha_score=70)

    result = service.scan(request)

    assert result.outcomes[0].final_signal == "NO TRADE"


def test_regime_filter_disabled_allows_buy_despite_regime_block():
    service = build_service(
        regime_allowance_fn=fixed_regime_allowance_fn(allowed=False),
        alpha_score_fn=fixed_alpha_score_fn(score=90),
    )
    request = ScanRequest(symbols=["AAPL"], use_regime_filter=False, minimum_alpha_score=70)

    result = service.scan(request)

    assert result.outcomes[0].final_signal == "BUY"


# ---------------------------------------------------------------------------
# Alpha score threshold boundary
# ---------------------------------------------------------------------------

def test_alpha_score_exactly_at_minimum_is_eligible():
    service = build_service(alpha_score_fn=fixed_alpha_score_fn(score=70))
    request = ScanRequest(symbols=["AAPL"], minimum_alpha_score=70)

    result = service.scan(request)

    assert result.outcomes[0].final_signal == "BUY"


def test_alpha_score_just_below_minimum_is_not_eligible():
    service = build_service(alpha_score_fn=fixed_alpha_score_fn(score=69))
    request = ScanRequest(symbols=["AAPL"], minimum_alpha_score=70)

    result = service.scan(request)

    assert result.outcomes[0].final_signal == "NO TRADE"


# ---------------------------------------------------------------------------
# Risk values
# ---------------------------------------------------------------------------

def test_risk_values_reach_the_output_correctly():
    service = build_service(
        stop_loss_fn=fixed_stop_loss_fn(offset=5.0),
        take_profit_fn=fixed_take_profit_fn(offset=10.0),
        position_size_fn=fixed_position_size_fn(shares=42, risk_amount=123.456),
    )
    request = ScanRequest(symbols=["AAPL"])

    result = service.scan(request)

    outcome = result.outcomes[0]
    assert outcome.stop_loss == 95.0
    assert outcome.take_profit == 110.0
    assert outcome.suggested_shares == 42
    assert outcome.dollar_risk == 123.46


# ---------------------------------------------------------------------------
# Persistence and queue collaborators
# ---------------------------------------------------------------------------

def test_repository_called_once_with_exact_expected_legacy_payload():
    save_results = RecordingSaveResults()
    service = build_service(save_results_fn=save_results)
    request = ScanRequest(symbols=["AAPL", "MSFT"])

    result = service.scan(request)

    assert len(save_results.calls) == 1
    assert save_results.calls[0] == result.legacy_results
    assert save_results.calls[0][0]["Symbol"] == "AAPL"
    assert save_results.calls[0][1]["Symbol"] == "MSFT"


def test_queue_collaborator_called_only_when_requested():
    save_queue = RecordingSaveQueue(return_value=1)
    service = build_service(save_queue_fn=save_queue)

    service.scan(ScanRequest(symbols=["AAPL"], queue_trades=True))
    assert len(save_queue.calls) == 1

    service.scan(ScanRequest(symbols=["AAPL"], queue_trades=False))
    assert len(save_queue.calls) == 1


def test_queued_count_reflected_in_statistics():
    save_queue = RecordingSaveQueue(return_value=3)
    service = build_service(save_queue_fn=save_queue)
    request = ScanRequest(symbols=["AAPL"], queue_trades=True)

    result = service.scan(request)

    assert result.queued_count == 3
    assert result.statistics.queued_trades == 3


def test_partial_success_statistics():
    def flaky_market_data_fn(symbol, period, interval, auto_adjust):
        if symbol == "BAD":
            return pd.DataFrame()
        return make_price_frame()

    service = build_service(market_data_fn=flaky_market_data_fn)
    request = ScanRequest(symbols=["AAPL", "BAD", "MSFT"])

    result = service.scan(request)

    stats = result.statistics
    assert stats.symbols_requested == 3
    assert stats.symbols_processed == 3
    assert stats.successful_symbols == 2
    assert stats.failed_symbols == 1
    assert stats.buy_signals == 2
    assert stats.no_trade_signals == 0


def test_ranking_collaborator_receives_compatible_legacy_payload():
    ranking = RecordingRanking()
    service = build_service(ranking_fn=ranking)
    request = ScanRequest(symbols=["AAPL"])

    result = service.scan(request)

    assert len(ranking.calls) == 1
    assert ranking.calls[0] == result.legacy_results
    assert isinstance(result.ranked, pd.DataFrame)


# ---------------------------------------------------------------------------
# Progress callback
# ---------------------------------------------------------------------------

def test_progress_callback_called_for_every_symbol():
    calls = []

    def progress_callback(completed, total, symbol):
        calls.append((completed, total, symbol))

    service = build_service()
    request = ScanRequest(symbols=["AAPL", "MSFT", "TSLA"])

    service.scan(request, progress_callback=progress_callback)

    assert calls == [(1, 3, "AAPL"), (2, 3, "MSFT"), (3, 3, "TSLA")]


def test_progress_callback_exception_does_not_stop_the_scan():
    def failing_callback(completed, total, symbol):
        raise RuntimeError("dashboard widget gone")

    save_results = RecordingSaveResults()
    service = build_service(save_results_fn=save_results)
    request = ScanRequest(symbols=["AAPL", "MSFT"])

    result = service.scan(request, progress_callback=failing_callback)

    assert len(result.outcomes) == 2
    assert len(save_results.calls) == 1


# ---------------------------------------------------------------------------
# Whole-scan persistence failures
# ---------------------------------------------------------------------------

def test_repository_failure_raises_controlled_service_exception():
    save_results = RecordingSaveResults(raises=RuntimeError("disk full"))
    service = build_service(save_results_fn=save_results)
    request = ScanRequest(symbols=["AAPL"])

    with pytest.raises(ScannerPersistenceError):
        service.scan(request)


def test_trade_queue_failure_raises_controlled_service_exception_after_persistence_succeeds():
    save_results = RecordingSaveResults()
    save_queue = RecordingSaveQueue(raises=RuntimeError("db locked"))
    service = build_service(save_results_fn=save_results, save_queue_fn=save_queue)
    request = ScanRequest(symbols=["AAPL"], queue_trades=True)

    with pytest.raises(TradeQueuePersistenceError):
        service.scan(request)

    assert len(save_results.calls) == 1


# ---------------------------------------------------------------------------
# Voting mode
# ---------------------------------------------------------------------------

def test_scan_request_defaults_to_single_strategy_mode():
    request = ScanRequest(symbols=["AAPL"])

    assert request.strategy_mode == ScanStrategyMode.SINGLE


def test_scan_request_accepts_raw_string_strategy_mode():
    request = ScanRequest(symbols=["AAPL"], strategy_mode="voting")

    assert request.strategy_mode == ScanStrategyMode.VOTING


def test_voting_mode_calls_voting_collaborator_and_not_single_strategy_fn():
    calls = {"voting": 0, "single": 0}

    def voting_fn(df, short_ema, long_ema, rsi_threshold, use_volume_filter):
        calls["voting"] += 1
        return {
            "final_signal": "NO TRADE",
            "vote_score": 0,
            "buy_votes": 0,
            "total_votes": 4,
            "confidence": 0,
            "reasons": "No consensus",
            "strategy_votes": [],
        }

    def single_strategy_fn(df, strategy_name, short_ema, long_ema, rsi_threshold, use_volume_filter):
        calls["single"] += 1
        return df

    service = build_service(strategy_fn=single_strategy_fn, voting_fn=voting_fn)
    request = ScanRequest(symbols=["AAPL"], strategy_mode=ScanStrategyMode.VOTING)

    service.scan(request)

    assert calls["voting"] == 1
    assert calls["single"] == 0


def test_voting_outcome_uses_voting_display_label():
    service = build_service()
    request = ScanRequest(symbols=["AAPL"], strategy_mode=ScanStrategyMode.VOTING)

    result = service.scan(request)

    assert result.outcomes[0].strategy == "Strategy Voting"


def test_voting_confidence_and_reasons_preserved():
    def voting_fn(df, short_ema, long_ema, rsi_threshold, use_volume_filter):
        return {
            "final_signal": "BUY",
            "vote_score": 66.67,
            "buy_votes": 2,
            "total_votes": 3,
            "confidence": 71.4,
            "reasons": "EMA Trend: bullish | Breakout: confirmed",
            "strategy_votes": [
                {"Strategy": "EMA Trend", "Signal": "BUY", "Confidence": 80, "Reason": "bullish"},
                {"Strategy": "Breakout", "Signal": "BUY", "Confidence": 85, "Reason": "confirmed"},
                {"Strategy": "RSI Pullback", "Signal": "NO TRADE", "Confidence": 0, "Reason": "No trade"},
            ],
        }

    service = build_service(voting_fn=voting_fn, alpha_score_fn=fixed_alpha_score_fn(score=90))
    request = ScanRequest(
        symbols=["AAPL"], strategy_mode=ScanStrategyMode.VOTING, minimum_alpha_score=70
    )

    result = service.scan(request)

    outcome = result.outcomes[0]
    assert outcome.confidence == 71
    assert outcome.signal_reason == "EMA Trend: bullish | Breakout: confirmed"


def test_voting_metadata_present_in_outcome_and_legacy_dict():
    service = build_service()
    request = ScanRequest(symbols=["AAPL"], strategy_mode=ScanStrategyMode.VOTING)

    result = service.scan(request)

    outcome = result.outcomes[0]
    assert outcome.vote_score == 75.0
    assert outcome.buy_votes == 3
    assert outcome.total_votes == 4
    assert outcome.strategy_votes is not None
    assert len(outcome.strategy_votes) == 4

    legacy = outcome.to_legacy_dict()
    assert legacy["Vote Score"] == 75.0
    assert legacy["BUY Votes"] == 3
    assert legacy["Total Votes"] == 4


def test_single_strategy_outcome_has_no_voting_fields_forced():
    service = build_service()
    request = ScanRequest(symbols=["AAPL"])

    result = service.scan(request)

    outcome = result.outcomes[0]
    assert outcome.vote_score is None
    assert outcome.buy_votes is None
    assert outcome.total_votes is None
    assert outcome.strategy_votes is None

    legacy = outcome.to_legacy_dict()
    assert "Vote Score" not in legacy
    assert "BUY Votes" not in legacy
    assert "Total Votes" not in legacy


def test_voting_regime_filter_blocks_when_minority_of_buy_voters_allowed():
    service = build_service(
        regime_allowance_fn=named_regime_allowance_fn({"EMA Trend"}),
        alpha_score_fn=fixed_alpha_score_fn(score=90),
    )
    request = ScanRequest(
        symbols=["AAPL"],
        strategy_mode=ScanStrategyMode.VOTING,
        use_regime_filter=True,
        minimum_alpha_score=70,
    )

    result = service.scan(request)

    outcome = result.outcomes[0]
    assert outcome.regime_allows_strategy is False
    assert outcome.final_signal == "NO TRADE"


def test_voting_regime_filter_allows_when_majority_of_buy_voters_allowed():
    service = build_service(
        regime_allowance_fn=named_regime_allowance_fn({"EMA Trend", "MACD Momentum"}),
        alpha_score_fn=fixed_alpha_score_fn(score=90),
    )
    request = ScanRequest(
        symbols=["AAPL"],
        strategy_mode=ScanStrategyMode.VOTING,
        use_regime_filter=True,
        minimum_alpha_score=70,
    )

    result = service.scan(request)

    outcome = result.outcomes[0]
    assert outcome.regime_allows_strategy is True
    assert outcome.final_signal == "BUY"


def test_voting_regime_filter_disabled_allows_buy_despite_regime_block():
    service = build_service(
        regime_allowance_fn=named_regime_allowance_fn(set()),
        alpha_score_fn=fixed_alpha_score_fn(score=90),
    )
    request = ScanRequest(
        symbols=["AAPL"],
        strategy_mode=ScanStrategyMode.VOTING,
        use_regime_filter=False,
        minimum_alpha_score=70,
    )

    result = service.scan(request)

    assert result.outcomes[0].final_signal == "BUY"


def test_voting_alpha_gating_blocks_low_score():
    service = build_service(alpha_score_fn=fixed_alpha_score_fn(score=50))
    request = ScanRequest(
        symbols=["AAPL"], strategy_mode=ScanStrategyMode.VOTING, minimum_alpha_score=70
    )

    result = service.scan(request)

    assert result.outcomes[0].final_signal == "NO TRADE"


def test_voting_risk_values_reach_the_output_correctly():
    service = build_service(
        stop_loss_fn=fixed_stop_loss_fn(offset=5.0),
        take_profit_fn=fixed_take_profit_fn(offset=10.0),
        position_size_fn=fixed_position_size_fn(shares=17, risk_amount=250.0),
    )
    request = ScanRequest(symbols=["AAPL"], strategy_mode=ScanStrategyMode.VOTING)

    result = service.scan(request)

    outcome = result.outcomes[0]
    assert outcome.stop_loss == 95.0
    assert outcome.take_profit == 110.0
    assert outcome.suggested_shares == 17
    assert outcome.dollar_risk == 250.0


def test_voting_queue_eligibility_still_applies():
    save_queue = RecordingSaveQueue(return_value=1)
    service = build_service(
        save_queue_fn=save_queue, alpha_score_fn=fixed_alpha_score_fn(score=90)
    )
    request = ScanRequest(
        symbols=["AAPL"],
        strategy_mode=ScanStrategyMode.VOTING,
        queue_trades=True,
        minimum_alpha_score=70,
    )

    result = service.scan(request)

    assert result.outcomes[0].queue_eligible is True
    assert len(save_queue.calls) == 1


def test_voting_cannot_bypass_alpha_controls():
    service = build_service(alpha_score_fn=fixed_alpha_score_fn(score=10))
    request = ScanRequest(
        symbols=["AAPL"], strategy_mode=ScanStrategyMode.VOTING, minimum_alpha_score=70
    )

    result = service.scan(request)

    outcome = result.outcomes[0]
    assert outcome.raw_signal == "BUY"
    assert outcome.final_signal == "NO TRADE"


def test_voting_cannot_bypass_regime_controls():
    service = build_service(
        regime_allowance_fn=named_regime_allowance_fn(set()),
        alpha_score_fn=fixed_alpha_score_fn(score=95),
    )
    request = ScanRequest(
        symbols=["AAPL"],
        strategy_mode=ScanStrategyMode.VOTING,
        use_regime_filter=True,
        minimum_alpha_score=70,
    )

    result = service.scan(request)

    outcome = result.outcomes[0]
    assert outcome.raw_signal == "BUY"
    assert outcome.final_signal == "NO TRADE"


def test_voting_one_symbol_failure_does_not_stop_other_symbols():
    call_count = {"n": 0}

    def sometimes_failing_voting_fn(df, short_ema, long_ema, rsi_threshold, use_volume_filter):
        call_count["n"] += 1

        if call_count["n"] == 1:
            raise ValueError("voting blew up")

        return default_vote_result()

    service = build_service(voting_fn=sometimes_failing_voting_fn)
    request = ScanRequest(symbols=["BAD", "AAPL"], strategy_mode=ScanStrategyMode.VOTING)

    result = service.scan(request)

    bad_outcome, good_outcome = result.outcomes
    assert bad_outcome.status == "ERROR"
    assert bad_outcome.final_signal == "SCAN ERROR"
    assert good_outcome.status == "OK"


def test_voting_empty_market_data_produces_controlled_error_outcome():
    service = build_service(
        market_data_fn=lambda symbol, period, interval, auto_adjust: pd.DataFrame()
    )
    request = ScanRequest(symbols=["AAPL"], strategy_mode=ScanStrategyMode.VOTING)

    result = service.scan(request)

    outcome = result.outcomes[0]
    assert outcome.status == "ERROR"
    assert outcome.strategy == "Strategy Voting"
    assert outcome.final_signal == "NO DATA"


def test_no_real_external_or_database_calls_occur_in_voting_mode(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("real external/database call was made")

    monkeypatch.setattr("yfinance.download", fail_if_called)
    monkeypatch.setattr("sqlite3.connect", fail_if_called)

    service = build_service()
    request = ScanRequest(
        symbols=["AAPL"], strategy_mode=ScanStrategyMode.VOTING, queue_trades=True
    )

    result = service.scan(request)

    assert result.outcomes[0].status == "OK"


# ---------------------------------------------------------------------------
# Static and isolation guarantees
# ---------------------------------------------------------------------------

def _scanner_service_imported_modules():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "core" / "services" / "scanner_service.py"
    )
    tree = ast.parse(module_path.read_text())

    imported_modules = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    return imported_modules


def test_scanner_service_module_has_no_forbidden_imports():
    imported_modules = _scanner_service_imported_modules()

    for module_name in imported_modules:
        assert not module_name.startswith(FORBIDDEN_IMPORT_PREFIXES), (
            f"scanner_service.py must not import '{module_name}'"
        )


def test_scanner_service_no_longer_imports_pipeline_collaborators_directly():
    """ScannerService must delegate decision-workflow collaborators to
    TradingPipeline instead of importing/invoking them itself."""
    imported_modules = _scanner_service_imported_modules()

    for module_name in FORBIDDEN_DIRECT_COLLABORATOR_MODULES:
        assert module_name not in imported_modules, (
            f"scanner_service.py must not import '{module_name}' directly; "
            "it must delegate to TradingPipeline instead"
        )


def test_scanner_service_imports_trading_pipeline():
    imported_modules = _scanner_service_imported_modules()

    assert "core.pipeline.trading_pipeline" in imported_modules


def test_no_real_external_or_database_calls_occur(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("real external/database call was made")

    monkeypatch.setattr("yfinance.download", fail_if_called)
    monkeypatch.setattr("sqlite3.connect", fail_if_called)

    service = build_service()
    request = ScanRequest(symbols=["AAPL"], queue_trades=True)

    result = service.scan(request)

    assert result.outcomes[0].status == "OK"
