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
- `pages/5_Trade_Queue.py` migrated off the legacy `ExecutionRouter`/`PaperTrader` path onto `PaperTradingService` (new read-only `get_pending_queue_items()` method plus the existing `process_queue(enabled, queue_ids, auto_fill)`). `PaperTradingService` is now the **single** Streamlit-page writer of paper account/order/position/trade state; no active page imports `ExecutionRouter` or `PaperTrader` any longer.
- Reusable `PortfolioService` (`core/services/portfolio_service.py`): the authoritative read-only analytics layer for portfolio state - valuation, exposure, allocation, performance (equity curve, drawdown, volatility, Sharpe, Sortino), completed-trade statistics, portfolio snapshots (new `portfolio_snapshots` table), and reconciliation reporting (surfaced from `PaperTradingService.reconcile()`, not duplicated). Wired into `pages/2_Portfolio.py` (now a thin read-only adapter, no page-level statistics calculation) and `core/runtime/paper_runtime.py`'s terminal summary. `pages/4_Paper_Trading.py`'s queued-signal reads now also go through `PaperTradingService.get_pending_queue_items()` instead of importing `core.execution.trade_queue` directly, so every active paper-trading page shares the same service boundary.
- **Broker interface + `PaperBroker` adapter** (`core/broker/`): a stable, broker-neutral `BrokerInterface` (`ABC`) contract - account/position/order/fill operations, typed models, a controlled error hierarchy - implemented by `PaperBroker`, which adapts the existing `PaperTradingService`/`PortfolioService` without duplicating any order-lifecycle, fill, or analytics logic. Establishes the abstraction a future `IBKRBroker`/`AlpacaBroker`/`OANDABroker` will implement identically. Two small additions to `PaperTradingService` (`get_order()`, `get_open_orders()`); no other existing service, page, or runtime changed. Not wired into any Streamlit page or runtime mode yet - that is deliberately deferred.

## Next

- Bollinger Reversal strategy
- ADX Trend Strength strategy
- SuperTrend strategy
- Configuration cleanup
- IBKR paper trading integration (would implement `IBKRBroker` against the now-stable `BrokerInterface`)
- IBKR live trading integration
- Alpaca / OANDA broker adapters, behind the same `BrokerInterface`
- Wiring `BrokerInterface`/`PaperBroker` into a Streamlit page or the paper runtime, once a concrete second adapter exists to validate the abstraction was worth generalising
- Standalone `research` runtime service (currently a placeholder "not implemented" result)
- Voting metadata persistence (would require a `scanner_results` schema change; currently in-memory/display-only)
- Persistent backtest result storage
- Walk-forward analysis, parameter optimisation, Monte Carlo simulation (explicitly out of scope for the current backtesting milestone)
- A future `LiveTradingService`, consuming the same shared `TradingPipeline`/order-lifecycle conventions `PaperTradingService` established, behind a real `BrokerInterface` adapter
- `core/execution/execution_router.py` (`ExecutionRouter`) and `core/execution/paper_trader.py` (`PaperTrader`) are no longer used by any page or by `PaperBroker` but remain in the repository unmodified - candidates for deletion or archival in a future cleanup milestone
- Trailing-stop support was not carried over from the legacy `PaperTrader` page into `PaperTradingService`/`PaperPosition` (the `paper_positions.trailing_stop` column still exists for the legacy path only)
- Partial order fills (a paper order either fills in full, at a cash/position-limit-capped quantity, or is rejected before submission - there is no working `PARTIALLY_FILLED` status; the broker model reserves the enum value for a future adapter that needs it)
- `BrokerOrderRequest.time_in_force` is accepted but not enforced (no order expiry timer exists yet); `BrokerOrderType.LIMIT`/`STOP` are modelled but not supported by `PaperBroker`
- No sector/asset-class metadata, benchmark attribution, or scheduled/automatic portfolio snapshots yet - `PortfolioService`'s historical metrics are only as rich as the snapshot history a user (or a future scheduler) has explicitly created
- Portfolio optimisation remains a future milestone (explicitly out of scope now)