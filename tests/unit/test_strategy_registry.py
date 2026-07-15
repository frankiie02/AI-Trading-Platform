import inspect

import pandas as pd
import pytest

from core.indicators.pipeline import build_indicator_pipeline
from core.strategy.registry import (
    STRATEGY_REGISTRY,
    get_available_strategies,
    get_strategy,
)
from core.voting.engine import run_strategy_voting

REQUIRED_OUTPUT_COLUMNS = (
    "Trend Filter",
    "Momentum Filter",
    "Volume Filter",
    "Signal",
    "Signal Confidence",
    "Signal Reason",
    "Strategy Name",
    "Position",
)


def make_ohlcv_frame(rows=80):
    dates = pd.date_range("2023-01-01", periods=rows, freq="D")
    base = [i * 0.5 + 100 for i in range(rows)]

    return pd.DataFrame(
        {
            "Open": base,
            "High": [value + 1.5 for value in base],
            "Low": [value - 1.5 for value in base],
            "Close": [value + 0.5 for value in base],
            "Volume": [1_000_000 + (i * 1000) for i in range(rows)],
        },
        index=dates,
    )


def enriched_frame():
    return build_indicator_pipeline(make_ohlcv_frame(), short_ema=20, long_ema=50)


# ---------------------------------------------------------------------------
# Registry contents
# ---------------------------------------------------------------------------

def test_trend_momentum_is_registered():
    assert "Trend Momentum" in STRATEGY_REGISTRY


def test_registry_lookup_returns_trend_momentum_callable():
    strategy_fn = get_strategy("Trend Momentum")

    assert strategy_fn is not None
    assert callable(strategy_fn)


def test_no_duplicate_strategy_names():
    names = list(STRATEGY_REGISTRY.keys())

    assert len(names) == len(set(names))


def test_available_strategies_includes_trend_momentum():
    assert "Trend Momentum" in get_available_strategies()


def test_unknown_strategy_lookup_returns_none():
    assert get_strategy("Not A Real Strategy") is None


# ---------------------------------------------------------------------------
# Registry contract compliance (every registered strategy)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("strategy_name", list(STRATEGY_REGISTRY.keys()))
def test_registered_strategy_signature_matches_contract(strategy_name):
    strategy_fn = STRATEGY_REGISTRY[strategy_name]
    parameters = inspect.signature(strategy_fn).parameters

    for expected in ("df", "short_ema", "long_ema", "rsi_threshold", "use_volume_filter"):
        assert expected in parameters


@pytest.mark.parametrize("strategy_name", list(STRATEGY_REGISTRY.keys()))
def test_registered_strategy_output_satisfies_expected_columns(strategy_name):
    strategy_fn = STRATEGY_REGISTRY[strategy_name]

    result = strategy_fn(
        df=enriched_frame(),
        short_ema=20,
        long_ema=50,
        rsi_threshold=55,
        use_volume_filter=True,
    )

    for column in REQUIRED_OUTPUT_COLUMNS:
        assert column in result.columns, f"{strategy_name} missing '{column}' column"

    clean = result.dropna()
    assert not clean.empty, f"{strategy_name} produced no usable rows"


# ---------------------------------------------------------------------------
# Trend Momentum specifics
# ---------------------------------------------------------------------------

def test_trend_momentum_does_not_recompute_indicators_itself():
    """Regression guard: the adapter must rely on the caller's enrichment
    rather than re-running add_all_indicators, matching every sibling
    strategy's contract."""
    strategy_fn = get_strategy("Trend Momentum")

    with pytest.raises(KeyError):
        strategy_fn(df=make_ohlcv_frame(), short_ema=20, long_ema=50)


def test_trend_momentum_signal_matches_ema_trend_formula():
    """Trend Momentum's buy condition intentionally mirrors EMA Trend's
    (Short EMA > Long EMA, RSI > threshold, volume confirmed) - only the
    confidence/reason/label metadata differs."""
    from core.strategy import ema_trend, trend_momentum_strategy

    df = enriched_frame()

    trend_momentum_result = trend_momentum_strategy.run_strategy(
        df=df, short_ema=20, long_ema=50, rsi_threshold=55, use_volume_filter=True
    )
    ema_trend_result = ema_trend.run_strategy(
        df=df, short_ema=20, long_ema=50, rsi_threshold=55, use_volume_filter=True
    )

    pd.testing.assert_series_equal(
        trend_momentum_result["Signal"], ema_trend_result["Signal"]
    )


# ---------------------------------------------------------------------------
# Voting inclusion
# ---------------------------------------------------------------------------

def test_voting_includes_trend_momentum():
    result = run_strategy_voting(make_ohlcv_frame(), short_ema=20, long_ema=50)

    voted_strategies = {vote["Strategy"] for vote in result["strategy_votes"]}

    assert "Trend Momentum" in voted_strategies


def test_voting_total_votes_matches_registry_size():
    result = run_strategy_voting(make_ohlcv_frame(), short_ema=20, long_ema=50)

    assert result["total_votes"] == len(STRATEGY_REGISTRY)
