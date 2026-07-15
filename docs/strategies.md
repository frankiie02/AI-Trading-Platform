# Strategies

## Current Strategies

### EMA Trend

Trend-following strategy using EMA alignment, RSI momentum, and volume confirmation.

### RSI Pullback

Pullback strategy that looks for RSI recovery inside an existing bullish trend.

### Breakout

Momentum strategy that looks for price breaking above the previous 20-day high.

### MACD Momentum

Momentum confirmation strategy using MACD, MACD signal line, and histogram expansion.

### Trend Momentum

Trend-following strategy using EMA alignment and RSI momentum (its buy condition intentionally mirrors EMA Trend's: `Short EMA > Long EMA` and `RSI > threshold`, both volume-confirmed).

**Registration note:** the original implementation re-ran the full indicator pipeline (`add_all_indicators`) on a frame the registry already enriches, and never populated `Signal Confidence` / `Signal Reason` / `Strategy Name` — every other registered strategy relies on the caller's enrichment and sets those three columns. It was adapted in place (`core/strategy/trend_momentum_strategy.py`) to drop the redundant self-enrichment and add the missing metadata columns, without changing its trading calculation, so it now satisfies the same callable contract as every other registered strategy and is included in strategy voting.

## Strategy Registry

Strategies are registered inside:

```text
core/strategy/registry.py
```

Every registered strategy must accept `run_strategy(df, short_ema, long_ema, rsi_threshold, use_volume_filter)` on a pre-enriched frame (produced by `build_indicator_pipeline`) and return it with `Trend Filter`, `Momentum Filter`, `Volume Filter`, `Signal`, `Signal Confidence`, `Signal Reason`, `Strategy Name`, and `Position` columns added.

## Strategy Voting

`core/voting/engine.py` (`run_strategy_voting`) runs every registered strategy against the same enriched data and combines their signals into one consensus decision (`final_signal`, `vote_score`, `buy_votes`, `total_votes`, `confidence`, `reasons`, `strategy_votes`). A BUY requires at least 2 strategies voting BUY and a combined confidence of at least 60.

`ScannerService` (see `docs/architecture.md`) supports voting as a second scanner mode alongside single-strategy scanning, selectable from the Live Scanner page ("Strategy Voting") or via the `SCANNER_STRATEGY_MODE` runtime setting. Voting still passes through the same regime, alpha, and risk controls as single-strategy scans — it cannot bypass them.

Both the single-strategy and voting evaluation logic (indicators → strategy/voting → regime → alpha → risk → decision) now live in the shared `TradingPipeline` (`core/pipeline/trading_pipeline.py`), not in `ScannerService` itself — see "Trading Pipeline" in `docs/architecture.md`. `ScannerService` only downloads market data and delegates the per-symbol decision to `TradingPipeline.evaluate()`.