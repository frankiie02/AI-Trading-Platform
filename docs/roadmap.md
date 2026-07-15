# Roadmap

## Completed

- Market data service
- Technical indicators
- Strategy framework
- Strategy registry
- EMA Trend strategy
- RSI Pullback strategy
- Breakout strategy
- MACD Momentum strategy
- Trend Momentum strategy
- Alpha scoring engine
- Market regime engine
- Live scanner
- Backtesting
- SQLite database
- Paper trading
- Trade queue
- Execution router
- Portfolio monitoring
- Order management
- Strategy voting engine
- Runtime bootstrap and application architecture (`TradingApplication`, `RuntimeRouter`, `RuntimeMode`)
- Reusable `ScannerService` (single-strategy and strategy-voting modes), wired into both the Live Scanner Streamlit page and the standalone `scanner` runtime mode
- Shared `TradingPipeline` (`core/pipeline/`): extracted the reusable market data → indicators → strategy/voting → regime → alpha → risk → decision workflow out of `ScannerService` into one tested, injectable pipeline; `ScannerService` now delegates per-symbol decisions to it
- Reusable `BacktestService` (single-strategy and strategy-voting modes), wired into both the Backtesting Streamlit page and the standalone `backtest` runtime mode; reuses `TradingPipeline.evaluate()` per historical bar with anti-lookahead slicing, discrete trade simulation (next-bar-open entry, ATR stop-loss/take-profit from the existing risk engine, commissions/slippage), and its own equity-curve/performance metrics

## Next

- Bollinger Reversal strategy
- ADX Trend Strength strategy
- SuperTrend strategy
- Configuration cleanup
- IBKR paper trading integration
- IBKR live trading integration
- Standalone `research`/`paper` runtime services (currently placeholder "not implemented" results)
- Voting metadata persistence (would require a `scanner_results` schema change; currently in-memory/display-only)
- Persistent backtest result storage
- Walk-forward analysis, parameter optimisation, Monte Carlo simulation (explicitly out of scope for the current backtesting milestone)
- `PaperTradingService` and a future `LiveTradingService`, both consuming the now-shared `TradingPipeline` instead of reimplementing the decision workflow