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
- Reusable `PaperTradingService` (`core/services/paper_trading_service.py`): a validated CREATED -> VALIDATED -> SUBMITTED -> FILLED (or REJECTED/CANCELLED/EXPIRED) paper-order lifecycle consuming `TradingDecision` from the shared `TradingPipeline`, with deterministic slippage/commission fills, cash/position/order sizing limits, stop-loss/take-profit exits, manual closes, realised P&L, and account reconciliation - wired into `pages/2_Portfolio.py`, `pages/4_Paper_Trading.py`, `pages/6_Order_Management.py`, the new `pages/3_Trade_History.py`, and the standalone `paper` runtime mode (`core/runtime/paper_runtime.py`)
- Standalone `paper` runtime service (`RuntimeMode.PAPER` no longer a placeholder); `research` remains not yet implemented

## Next

- Bollinger Reversal strategy
- ADX Trend Strength strategy
- SuperTrend strategy
- Configuration cleanup
- IBKR paper trading integration
- IBKR live trading integration
- Standalone `research` runtime service (currently a placeholder "not implemented" result)
- Voting metadata persistence (would require a `scanner_results` schema change; currently in-memory/display-only)
- Persistent backtest result storage
- Walk-forward analysis, parameter optimisation, Monte Carlo simulation (explicitly out of scope for the current backtesting milestone)
- A future `LiveTradingService`, consuming the same shared `TradingPipeline`/order-lifecycle conventions `PaperTradingService` established, behind the broker abstraction milestone
- `pages/5_Trade_Queue.py` still executes trades through the legacy `ExecutionRouter`/`PaperTrader` path rather than `PaperTradingService` - a deliberately deferred follow-up so both paths can mutate `paper_positions`/`account_state`; migrating it to `PaperTradingService` would give the platform a single order-execution writer
- Trailing-stop support was not carried over from the legacy `PaperTrader` page into `PaperTradingService`/`PaperPosition` (the `paper_positions.trailing_stop` column still exists for the legacy path only)
- Partial order fills (a paper order either fills in full, at a cash/position-limit-capped quantity, or is rejected before submission - there is no `PARTIALLY_FILLED` status)