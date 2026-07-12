import ast
from pathlib import Path

import pandas as pd
import pytest

from core.regime.market_state import MarketState
from core.services.scanner_service import (
    ScanRequest,
    ScannerPersistenceError,
    ScannerService,
    SymbolScanOutcome,
    TradeQueuePersistenceError,
)

FORBIDDEN_IMPORT_PREFIXES = (
    "streamlit",
    "pages",
    "dashboard",
    "core.broker",
    "core.runtime",
    "core.voting",
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


def build_service(
    market_data_fn=None,
    strategy_fn=identity_strategy_fn,
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
):
    default_market_data_fn = (
        lambda symbol, period, interval, auto_adjust: make_price_frame()
    )

    return ScannerService(
        market_data_fn=market_data_fn or default_market_data_fn,
        strategy_fn=strategy_fn,
        regime_detector=regime_detector or fixed_regime_detector(),
        regime_allowance_fn=regime_allowance_fn or fixed_regime_allowance_fn(),
        alpha_score_fn=alpha_score_fn or fixed_alpha_score_fn(),
        alpha_grade_fn=alpha_grade_fn or fixed_alpha_grade_fn(),
        queue_eligibility_fn=queue_eligibility_fn,
        stop_loss_fn=stop_loss_fn or fixed_stop_loss_fn(),
        take_profit_fn=take_profit_fn or fixed_take_profit_fn(),
        position_size_fn=position_size_fn or fixed_position_size_fn(),
        save_results_fn=save_results_fn or RecordingSaveResults(),
        save_queue_fn=save_queue_fn or RecordingSaveQueue(),
        ranking_fn=ranking_fn or RecordingRanking(),
        account_balance=100000,
    )


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
# Static and isolation guarantees
# ---------------------------------------------------------------------------

def test_scanner_service_module_has_no_forbidden_imports():
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

    for module_name in imported_modules:
        assert not module_name.startswith(FORBIDDEN_IMPORT_PREFIXES), (
            f"scanner_service.py must not import '{module_name}'"
        )


def test_no_real_external_or_database_calls_occur(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("real external/database call was made")

    monkeypatch.setattr("yfinance.download", fail_if_called)
    monkeypatch.setattr("sqlite3.connect", fail_if_called)

    service = build_service()
    request = ScanRequest(symbols=["AAPL"], queue_trades=True)

    result = service.scan(request)

    assert result.outcomes[0].status == "OK"
