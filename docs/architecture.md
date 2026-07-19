# Architecture

## Overview

The AI Trading Platform is built as a modular trading system.

The Streamlit dashboard is the user interface. The trading logic lives inside the `core/` package.

## Core Flow

Market Data → Indicators → Strategy Engine → Regime Engine → Alpha Engine → Scanner → Trade Queue → Execution Router → Portfolio

## Main Modules

- `core/market_data`: downloads and prepares market data.
- `core/indicators`: calculates technical indicators.
- `core/strategy`: contains trading strategies and the strategy registry.
- `core/regime`: detects market condition.
- `core/alpha`: scores and ranks trading opportunities.
- `core/risk`: calculates stop-loss, take-profit, and position sizing.
- `core/scanner`: saves scanner results.
- `core/execution`: handles paper trading, trade queue, and execution routing.
- `core/portfolio`: monitors positions and portfolio values.
- `core/database`: SQLite database layer.
- `core/runtime`: minimal application bootstrap and runtime-mode routing (see below).
- `core/services`: reusable, Streamlit-free orchestration services for dashboard workflows (see below).
- `core/pipeline`: the shared `TradingPipeline` decision workflow used by `ScannerService`, `BacktestService`, and `PaperTradingService` (and, in a future milestone, `LiveTradingService`) (see below).

## Runtime Bootstrap

`main.py` constructs a `TradingApplication` (`core/runtime/application.py`) and calls `run()`. The bootstrap lifecycle is:

```text
load configuration → resolve runtime mode → obtain logger → create RuntimeContext → route runtime mode → return result
```

Runtime mode is selected via the `RUNTIME_MODE` configuration key (`config/defaults.py`, default `"research"`) and validated against the `RuntimeMode` enum (`core/runtime/modes.py`):

- `research`
- `scanner`
- `backtest`
- `optimisation`
- `paper`
- `live`

`RuntimeRouter` (`core/runtime/router.py`) dispatches the resolved mode. It contains no trading logic itself:

- `research`: recognised, but its standalone runtime service is not yet implemented — the router returns a controlled `RuntimeResult` describing this.
- `scanner`: dispatches to the standalone scanner runtime (`core/runtime/scanner_runtime.py`, see below), imported lazily inside `route()` so the router's own module-level imports stay free of scanner/market-data/database dependencies.
- `backtest`: dispatches to the standalone backtest runtime (`core/runtime/backtest_runtime.py`, see below), imported lazily for the same reason.
- `paper`: dispatches to the standalone paper runtime (`core/runtime/paper_runtime.py`, see below), imported lazily for the same reason.
- `optimisation`: raises `UnsupportedRuntimeModeError` (not implemented yet).
- `live`: always raises `LiveModeDisabledError`. Live trading is hard-disabled and is not activated by this bootstrap.

The existing Streamlit dashboard (`streamlit run dashboard.py` and `pages/`) remains a separate, independent entry point and is unaffected by this bootstrap. It is not launched by `main.py`, and `main.py` does not import Streamlit, broker, execution, or strategy modules.

## Trading Pipeline

`TradingPipeline` (`core/pipeline/trading_pipeline.py`) is the single reusable, testable implementation of the market-data-independent trading-decision workflow:

```text
indicators → single strategy or strategy voting → regime detection → regime permission → alpha scoring/grading → ATR stop-loss / take-profit / position sizing → queue eligibility → BUY / NO TRADE decision
```

It is a pure decision workflow with **no** market-data downloading, Streamlit rendering, scanner-result or trade-queue persistence, database access, runtime routing, broker submission, portfolio mutation, or live execution. It takes one `TradingPipelineRequest` (one symbol's already-downloaded raw price frame plus decision parameters — strategy mode/name, EMA/RSI settings, regime-filter flag, account balance, risk percent, ATR multiplier, reward/risk ratio, minimum alpha score) and returns one `TradingDecision` (`core/pipeline/models.py`), or raises a typed `TradingPipelineError` subclass (`InsufficientDataError`, `InvalidStrategyConfigurationError`, `PipelineEvaluationError`) on an operational failure. It never encodes operational failures as a trading signal.

- **Single-strategy path**: calls `generate_strategy_signals` (`core/strategy/strategy_engine.py`) via the existing strategy registry — unchanged from the original `ScannerService` extraction.
- **Voting path**: calls the existing voting engine (`run_strategy_voting`, `core/voting/engine.py`) for the BUY/NO TRADE consensus decision, and separately calls `build_indicator_pipeline` (`core/indicators/pipeline.py`) — the same enrichment function the voting engine already uses internally — to obtain the enriched price row that regime detection, alpha scoring, and risk calculations need but the voting engine's dict result does not expose. Both are pure functions of the same input, so this does not duplicate or alter any algorithm; it only assembles the additional input the shared downstream steps require. (Indicator enrichment therefore still runs twice in voting mode — once explicitly, once inside the voting engine — exactly as before extraction.)
  - Voting-mode regime allowance: since `strategy_allowed()` (`core/regime/filters.py`) only evaluates a single named strategy, a voting BUY is regime-permitted only when a **strict majority** of the strategies that voted BUY would individually be allowed to trade in the detected regime. Zero BUY votes, or exactly half allowed, both fail the gate. This reuses the existing per-strategy regime rule unchanged; it does not introduce a new regime formula.
  - Voting-mode alpha scoring input: `Trend Filter` and `Volume Filter` are derived from the same primitives every registered strategy already uses (`Short EMA > Long EMA`, `Volume > Volume Average`); `Momentum Filter` is approximated by the voting engine's own consensus gate (`buy_votes >= 2`), since there is no single shared momentum formula across strategies. The alpha-scoring formula itself is untouched.
  - Voting cannot bypass regime, alpha, or risk controls — the same `use_regime_filter` / `minimum_alpha_score` / risk-calculation gates apply to both paths.
- Every collaborator (strategy generation, voting, indicator pipeline, regime detection/filter, alpha scoring/grading, queue-eligibility, stop-loss/take-profit/position-size) is injected via constructor defaults (no DI framework), so `TradingPipeline` contains no Streamlit, database, or broker code and can be tested with fakes.
- `TradingPipeline` performs no persistence and no broker side effects. Live trading remains disabled regardless of pipeline output — nothing in `TradingPipeline` submits orders.
- Reuse plan: `BacktestService` builds a `TradingPipelineRequest` per historical bar and calls `TradingPipeline.evaluate()`, exactly as `ScannerService` does per symbol. `PaperTradingService` (see "Paper Trading Service" below) consumes the `TradingDecision` those two produce (or a queued/manual signal) rather than calling `TradingPipeline.evaluate()` itself, so the indicator → strategy/voting → regime → alpha → risk decision logic remains implemented exactly once, upstream of every execution path. A future `LiveTradingService` is expected to consume `TradingDecision` the same way.

## Backtest Service

`BacktestService` (`core/services/backtest_service.py`) is the reusable, testable historical-backtesting workflow, used by both `pages/3_Backtesting.py` (Streamlit) and the standalone `backtest` runtime mode:

```text
market data → chronological bar-by-bar iteration → TradingPipeline.evaluate() per bar → simulated entry/exit → BacktestTrade → equity curve → performance metrics
```

Key points:

- **Anti-lookahead**: for each bar `t`, `BacktestService` evaluates `TradingPipeline.evaluate()` on `data.iloc[: t + 1]` (i.e. `data.loc[:t]`) only — the pipeline never receives any row beyond the current bar. This is enforced structurally (the historical slice is constructed before every call) and covered by a dedicated regression test that injects an extreme future price spike and asserts it cannot influence any earlier decision.
- **Execution convention** (adopted because the pre-existing Backtesting page never defined a stop-loss/take-profit/position-sizing rule at all — see "Known limitations" below): a BUY decision made using data through bar `t` is entered at bar `t+1`'s Open. Stop-loss/take-profit — taken as-is from `TradingPipeline`'s existing ATR-based risk-engine output — are checked every bar from the entry bar onward using that bar's High/Low; if both are touched in the same bar, the stop-loss is assumed to trigger first (adverse-first). Only one long position per symbol is held at a time; there is no short selling or leverage. Any position still open at the final bar is force-closed at the final available close. Position sizing uses currently available cash (no leverage) and the share count `TradingPipeline` already computed via the existing risk engine (`core/risk/risk_engine.py`), capped by what available cash can afford.
- **No new algorithms**: `BacktestService` does not reimplement indicators, strategy signals, voting, regime detection, alpha scoring, or risk/position-sizing formulas — all of that is delegated to the unchanged `TradingPipeline`. `BacktestService` owns only backtest-specific orchestration: market-data retrieval, the anti-lookahead loop, simulated fills, cash/equity bookkeeping, commission/slippage application, trade recording, and performance-metric calculation.
- **Error isolation**: a bar where `TradingPipeline` raises `InsufficientDataError` (indicator warm-up, e.g. the first ~50 bars for a 50-period EMA) is silently skipped and summarised as a single warning at the end (`"Skipped N bar(s)..."`); any other `TradingPipelineError` on a given bar is recorded as a warning and that bar is treated as "no decision", without aborting the rest of the backtest. Invalid requests (`InvalidBacktestRequestError`) and market-data failures (`BacktestDataError`) are raised immediately and are not swallowed.
- **Strategy modes**: both `ScanStrategyMode.SINGLE` and `ScanStrategyMode.VOTING` are supported, exactly mirroring `ScannerService`'s modes — voting mode therefore inherits the strict-majority voting-regime rule, alpha filtering, and risk controls with no new formula.
- `BacktestService` performs no persistence, no Streamlit rendering, no broker/live calls, and makes no real network or database calls in tests (verified by injected fakes and a `yfinance.download`/`sqlite3.connect` guard test, mirroring `TradingPipeline`'s and `ScannerService`'s own test conventions).

## Standalone Backtest Runtime

`core/runtime/backtest_runtime.py` provides `run_backtest(context, service=None)`, the standalone coordinator for `RuntimeMode.BACKTEST`, following the exact same shape as `run_scanner`:

1. `build_backtest_request(context.settings)` builds a `BacktestRequest` from the `BACKTEST_*` configuration keys (`config/defaults.py`), falling back to their defaults for any key absent from `context.settings`.
2. Calls `BacktestService.run()` (a real `BacktestService()` by default — paper/local only, no broker).
3. Returns a `RuntimeResult` with a concise terminal summary (symbol, trade count, total return, max drawdown, final equity).
4. Performs no persistence.

`backtest_runtime.py` imports no Streamlit, broker, or live-execution module. `RuntimeRouter` now dispatches `RuntimeMode.BACKTEST` to it (imported lazily inside `route()`, matching the scanner dispatch pattern) instead of returning a placeholder "not implemented" result; `research` and `paper` remain placeholders.

### Backtest runtime configuration keys (`config/defaults.py`)

| Key | Default |
|---|---|
| `BACKTEST_SYMBOL` | `"SPY"` |
| `BACKTEST_PERIOD` | `"2y"` |
| `BACKTEST_INTERVAL` | `"1d"` |
| `BACKTEST_STRATEGY_MODE` | `"single"` |
| `BACKTEST_STRATEGY` | `"EMA Trend"` |
| `BACKTEST_INITIAL_CAPITAL` | `100000` |
| `BACKTEST_SHORT_EMA` | `20` |
| `BACKTEST_LONG_EMA` | `50` |
| `BACKTEST_RSI_THRESHOLD` | `55` |
| `BACKTEST_USE_VOLUME_FILTER` | `True` |
| `BACKTEST_USE_REGIME_FILTER` | `True` |
| `BACKTEST_RISK_PERCENT` | `1.0` |
| `BACKTEST_ATR_MULTIPLIER` | `2.0` |
| `BACKTEST_REWARD_RISK_RATIO` | `2.0` |
| `BACKTEST_MINIMUM_ALPHA_SCORE` | `70` |
| `BACKTEST_COMMISSION` | `0.0` |
| `BACKTEST_SLIPPAGE` | `0.0` |

## Backtesting Page

`pages/3_Backtesting.py` is a thin UI adapter, mirroring `pages/1_Live_Scanner.py`'s structure: it builds a `BacktestRequest` from widget values (including a Single Strategy / Strategy Voting mode control, matching the Live Scanner UX), calls `BacktestService.run()`, and renders the returned `BacktestResult` (metrics, equity curve, trade log, warnings/controlled errors). It no longer downloads market data, evaluates `TradingPipeline`, or computes performance metrics directly — those all live in `BacktestService`.

### Known limitations / deferred work

- The old return-multiplier backtest model (`core/analytics/performance.py`, `calculate_performance`/`extract_trades`) is **not used by `BacktestService`** and remains untouched: it never supported stop-loss, take-profit, position sizing, commissions, or voting mode, so it could not satisfy the new `BacktestTrade` contract. `BacktestService` computes its own discrete-trade equity curve and metrics (using the same Sharpe/CAGR/drawdown formulas for consistency) directly from the simulated trades.
- `BacktestTrade.stop_loss`/`take_profit`/`suggested_shares` are taken as-is from `TradingPipeline`'s decision, which computes them relative to the **signal bar's close**, not the actual next-bar-open fill price. This is a deliberate simplification consistent with not duplicating the existing risk-engine formulas.
- No walk-forward analysis, parameter optimisation, Monte Carlo simulation, short selling, leverage, or persistent backtest storage — all explicitly out of scope for this milestone.
- No separate benchmark-symbol input: the benchmark is always a buy-and-hold of the backtested symbol itself, matching the old page's implicit "Market Equity" comparison.

## Scanner Service

`ScannerService` (`core/services/scanner_service.py`) remains the single reusable, testable implementation of the Live Scanner business workflow. It is used by both `pages/1_Live_Scanner.py` (Streamlit) and the standalone `scanner` runtime mode:

```text
market data → TradingPipeline.evaluate() → SymbolScanOutcome → persistence → trade queue → ranking → scan statistics
```

Key points:

- `pages/1_Live_Scanner.py` is a thin UI adapter: it builds a `ScanRequest` from widget values, calls `ScannerService.scan()`, and renders the `ScanResult`. It no longer imports market data, strategy generation, regime, alpha, risk, or persistence collaborators directly — only historical reads (`get_recent_scanner_results`, `get_recent_buy_signals`) remain in the page for the history panels.
- `ScanRequest.strategy_mode` (`ScanStrategyMode` enum: `SINGLE` / `VOTING`, defined in `core/pipeline/models.py` and re-exported from `core.services.scanner_service` for backward compatibility) selects between the two supported paths. It defaults to `SINGLE`, so existing callers that never set it are unaffected.
- **`ScannerService` no longer calls the strategy engine, voting engine, indicator pipeline, regime detector/filter, alpha scorer/grader, or risk calculators directly.** For each symbol it downloads market data, builds a `TradingPipelineRequest` (carrying the symbol's raw price frame plus the request's decision parameters and the service's configured `account_balance`), and calls `TradingPipeline.evaluate()`. The returned `TradingDecision` is mapped into the existing `SymbolScanOutcome` shape.
- `ScannerService` retains: symbol normalisation/iteration, market-data retrieval, per-symbol exception isolation (translating `InsufficientDataError` → `NOT ENOUGH DATA` and any other `TradingPipelineError` → `SCAN ERROR`, matching the exact error labels and reason strings used before extraction), progress callbacks, persistence, trade-queue writes, ranking, and scan statistics.
- Each symbol is processed with its own exception handling; one symbol's failure (missing data, a pipeline `TradingPipelineError`, or an unexpected error) produces a controlled error outcome (`SymbolScanOutcome`, `status="ERROR"`) without stopping the rest of the scan. Error labels (`NO DATA`, `NOT ENOUGH DATA`, `SCAN ERROR`) are distinct sentinel values, never `BUY`/`SELL`/`NO TRADE`.
- Persistence and trade-queue writes remain fully delegated to the existing `save_scanner_results` and `save_buy_signals_to_queue` collaborators — the service does not duplicate their database logic. A failure in either raises a dedicated `ScannerPersistenceError` / `TradeQueuePersistenceError` rather than being silently swallowed.
- `SymbolScanOutcome.to_legacy_dict()` reproduces the exact dictionary shape the existing repository, trade-queue, and ranking functions expect, so those consumers require no changes. Voting-only fields (`Vote Score`, `BUY Votes`, `Total Votes`) are added to the dict only for voting outcomes — single-strategy outcomes are never given meaningless voting defaults. `save_scanner_results`/`save_buy_signals_to_queue` read known keys via `dict.get(...)`, so these extra keys are ignored by persistence: **voting metadata (vote score, buy/total votes, and the full per-strategy `strategy_votes` list) lives in memory/the ranked table only and is not written to the (unchanged) `scanner_results` database schema.**

## Standalone Scanner Runtime

`core/runtime/scanner_runtime.py` provides `run_scanner(context, service=None)`, the standalone coordinator for `RuntimeMode.SCANNER`:

1. `build_scan_request(context.settings)` builds a `ScanRequest` from the `SCANNER_*` configuration keys (`config/defaults.py`), falling back to their defaults for any key absent from `context.settings`.
2. Calls `ScannerService.scan()` (a real `ScannerService()` by default — paper/local only, no broker) with a logging progress callback.
3. Returns a `RuntimeResult` with a concise terminal summary (symbols scanned/failed, BUY signals, trades queued).
4. Partial per-symbol failures are represented via the normal `ScanStatistics`/`SymbolScanOutcome` mechanism and included in the summary; they do not raise.
5. Whole-scan persistence failures (`ScannerPersistenceError` / `TradeQueuePersistenceError`) are **not** caught — they propagate to the caller as controlled, typed exceptions rather than a false "success" result.

`scanner_runtime.py` imports no Streamlit, broker, or live-execution module. It never queues trades by default (`SCANNER_QUEUE_TRADES` defaults to `False`) and only ever exercises the paper/local (Yahoo market data + SQLite) collaborators `ScannerService` already uses.

### Scanner runtime configuration keys (`config/defaults.py`)

| Key | Default |
|---|---|
| `SCANNER_SYMBOLS` | `["SPY", "QQQ", "AAPL"]` |
| `SCANNER_STRATEGY_MODE` | `"single"` |
| `SCANNER_STRATEGY_NAME` | `"EMA Trend"` |
| `SCANNER_PERIOD` | `"1y"` |
| `SCANNER_INTERVAL` | `"1d"` |
| `SCANNER_SHORT_EMA` | `20` |
| `SCANNER_LONG_EMA` | `50` |
| `SCANNER_RSI_THRESHOLD` | `55` |
| `SCANNER_USE_VOLUME_FILTER` | `True` |
| `SCANNER_USE_REGIME_FILTER` | `True` |
| `SCANNER_RISK_PERCENT` | `1.0` |
| `SCANNER_ATR_MULTIPLIER` | `2.0` |
| `SCANNER_REWARD_RISK_RATIO` | `2.0` |
| `SCANNER_MINIMUM_ALPHA_SCORE` | `70` |
| `SCANNER_QUEUE_TRADES` | `False` |

These are intentionally separate from the interactive-dashboard defaults (`DEFAULT_SYMBOLS`, `DEFAULT_STRATEGY`, etc.) so the unattended standalone runtime uses its own small, safe symbol set and never queues trades unless explicitly configured to, without changing the Streamlit page's widget defaults.

Live trading remains disabled: `RuntimeMode.LIVE` always raises `LiveModeDisabledError` regardless of scanner configuration, and nothing in the scanner runtime or `ScannerService` submits broker orders.

## Paper Trading Service

`PaperTradingService` (`core/services/paper_trading_service.py`) is the reusable, testable paper-trading workflow, used by `pages/2_Portfolio.py`, `pages/4_Paper_Trading.py`, `pages/6_Order_Management.py`, `pages/3_Trade_History.py`, and the standalone `paper` runtime mode:

```text
TradingDecision (from TradingPipeline, or a queued signal / manual page entry)
    → order validation (quantity, cash, position/open-position limits, stop/target requirements)
    → CREATED → VALIDATED → SUBMITTED → FILLED (or REJECTED/CANCELLED/EXPIRED)
    → atomic fill (cash debit, position upsert, fill/trade record, order status)
    → stop-loss / take-profit exits, manual closes → realised P&L, trade history
    → reconciliation
```

Key points:

- **Consumes `TradingDecision`, never generates one.** `PaperTradingService` does not call `TradingPipeline`, download market data, or evaluate strategies/regime/alpha/risk itself - it only acts on an already-produced `TradingDecision` (`final_signal == "BUY"`) or a queued `trade_queue` row, exactly the boundary `TradingPipeline`'s own docstring anticipated. This is enforced by an AST-based import-boundary test forbidding direct imports of `core.strategy`, `core.voting`, `core.regime`, `core.alpha`, `core.risk`, `core.indicators`, `core.market_data`, and `core.pipeline.trading_pipeline`.
- **Order lifecycle**: `CREATED → VALIDATED → SUBMITTED → FILLED`, with `REJECTED`/`CANCELLED`/`EXPIRED` as terminal alternatives. By default `create_order_from_decision()`/`process_queue()` walk an order straight through to `FILLED` in one call (`auto_fill=True`); passing `auto_fill=False` stops at `VALIDATED` so a user can review it on the Order Management page before an explicit `submit_order()`/`fill_order()` (or `cancel_order()`). Invalid transitions (e.g. `REJECTED → FILLED`, `FILLED → CREATED`, `CANCELLED → SUBMITTED`) raise `InvalidOrderStateTransitionError`. Partial fills are not supported: an order's quantity is capped (by available cash and `PAPER_MAX_POSITION_PERCENT`) once, at validation time, then either fills in full or is rejected before submission.
- **Fill convention** (mirrors `BacktestService`'s adverse-slippage/commission convention, adapted for interactive rather than bar-by-bar use): a BUY fills at `reference_price * (1 + PAPER_SLIPPAGE / 100)`; an exit fills at `reference_price * (1 - PAPER_SLIPPAGE / 100)`. `reference_price` is always caller-supplied (the `TradingDecision.current_price`, the queued signal's price, or a page/runtime-injected quote) - `PaperTradingService` never downloads market data itself. A flat `PAPER_COMMISSION` is charged per fill (once on entry, once on exit).
- **Position management**: one open position per symbol (adding to an existing position averages the entry price, matching the legacy `PaperTrader`'s convention); long-only, no leverage, no short selling. `update_positions()` marks positions to a caller-supplied price map; `check_exits()` evaluates stop-loss before take-profit (adverse-first) against that same price map - interactive paper trading only ever receives one current price per update (no OHLC bar), so this differs from `BacktestService`'s true same-bar intrabar collision detection, but preserves the same "adverse condition checked first" intent.
- **Persistence and atomicity**: reuses the existing `account_state`/`paper_positions`/`paper_trades`/`trade_queue` tables (extended with additive columns) plus two new tables, `paper_orders` (the order lifecycle) and `paper_audit_events` (an audit trail) - see `docs/database.md`. Every fill (cash debit/credit, position upsert/delete, trade-ledger row, order-status update) happens inside one transaction in `core/execution/paper_orders_repository.py`, with a rollback on any failure; this is an approved correctness fix relative to the legacy `PaperTrader.buy()`/`sell()`, which is left completely untouched and spans two separate connections/commits with no rollback path.
- **Reconciliation**: `reconcile()` checks `account_state.realised_pnl` against `SUM(paper_trades.net_pnl)`, flags negative cash, and flags non-positive position share counts, returning explicit differences rather than silently overwriting state.
- **Error hierarchy**: `PaperTradingServiceError` → `InvalidPaperOrderError`, `InvalidOrderStateTransitionError`, `InsufficientCashError`, `PositionNotFoundError`, `PaperTradingPersistenceError`, `ReconciliationError` - the same one-base-plus-specific-subclasses convention as `ScannerServiceError`/`BacktestServiceError`.
- **No broker path**: `PaperTradingService` never imports `core.broker` or `ib_insync`, never uses real credentials, and never submits a real order (see `docs/broker.md`).
- **Single UI writer**: `pages/2_Portfolio.py`, `pages/3_Trade_History.py`, `pages/4_Paper_Trading.py`, `pages/5_Trade_Queue.py`, and `pages/6_Order_Management.py` all delegate exclusively to `PaperTradingService` - it is now the only Streamlit-page writer of paper account, order, position, and trade state. `pages/5_Trade_Queue.py` was migrated off `ExecutionRouter`/`PaperTrader` in this milestone: it reads pending signals via the new read-only `PaperTradingService.get_pending_queue_items()` method (a one-line delegation to the same injected `get_pending_trades` collaborator `process_queue()` already used - no new query logic), lets the user select specific queue rows via a multiselect, and processes them through the existing `process_queue(enabled=True, queue_ids=[...], auto_fill=...)` - no service-side processing logic changed, since `process_queue()` already supported per-row selection, isolation, and status updates.

### Known limitations / deferred work

- **`core/execution/execution_router.py` (`ExecutionRouter`) and `core/execution/paper_trader.py` (`PaperTrader`) are no longer imported by any active Streamlit page**, but remain in the repository unmodified (not deleted) for compatibility/later cleanup; `ExecutionRouter` is now dead code from the page layer's perspective. Both still coexist with `PaperTradingService` against the same `paper_positions`/`account_state` tables as a temporary condition - documented, not corrected, in this milestone (no other code path calls them, so no further mutation risk remains from the page layer).
- Trailing-stop is not part of `PaperPosition`/`PaperTradingService` - `paper_positions.trailing_stop` remains a legacy-`PaperTrader`-only column.
- `reserved_cash` exists on `PaperAccount`/`account_state` for forward compatibility but is always `0` in this milestone; nothing yet holds cash aside for a not-yet-filled order.
- Partial order fills are explicitly deferred, not faked: an order either fills in full (at a cash/position-limit-capped quantity) or is rejected before submission.
- `pages/4_Paper_Trading.py`'s queued-signal "Process Selected Queue Item(s)" button now reads pending items through `PaperTradingService.get_pending_queue_items()` rather than importing `core.execution.trade_queue.get_pending_trades` directly (fixed in the PortfolioService milestone) - every active paper-trading page now shares the same read/write boundary through `PaperTradingService`.

## Standalone Paper Runtime

`core/runtime/paper_runtime.py` provides `run_paper_trading(context, service=None, price_fetch_fn=None, portfolio_service=None)`, the standalone coordinator for `RuntimeMode.PAPER`, following the same shape as `run_scanner`/`run_backtest`:

1. `build_paper_settings(context.settings)` builds `PaperTradingService` constructor kwargs (plus a `process_queue` flag) from the `PAPER_*` settings (`config/defaults.py`), falling back to their defaults for any key absent from `context.settings`.
2. Optionally refreshes open-position prices/exits through an injected `price_fetch_fn(symbol) -> float` - if none is supplied (the default), position marking/exit-checking is skipped and no market data is downloaded implicitly; only queue processing runs.
3. Calls `PaperTradingService.process_queue()` (a real `PaperTradingService()` by default - paper/local only, no broker), gated by `PAPER_PROCESS_QUEUE`, which **defaults to `False`**: nothing executes automatically unless explicitly enabled.
4. Returns a `RuntimeResult` with a concise terminal summary (cash, equity, open positions, orders filled/rejected, realised/unrealised P&L), sourced from `PortfolioService.get_summary()` (a real `PortfolioService()` built against the exact same `db_path` as the `PaperTradingService` instance, via its `db_path` property) rather than re-deriving those figures directly from `PaperTradingService` - the runtime never duplicates portfolio equations, matching the "PortfolioService is the single authoritative source" intent.
5. Performs no Streamlit rendering and imports no broker/live-execution module.

`RuntimeRouter` now dispatches `RuntimeMode.PAPER` to it (imported lazily inside `route()`, matching the scanner/backtest dispatch pattern) instead of returning a placeholder "not implemented" result; `research` remains a placeholder.

### Paper runtime configuration keys (`config/defaults.py`)

| Key | Default |
|---|---|
| `PAPER_ACCOUNT_ID` | `"default"` |
| `PAPER_STARTING_BALANCE` | `100000` |
| `PAPER_COMMISSION` | `0.0` |
| `PAPER_SLIPPAGE` | `0.0` |
| `PAPER_MAX_OPEN_POSITIONS` | `10` |
| `PAPER_MAX_POSITION_PERCENT` | `25.0` |
| `PAPER_PROCESS_QUEUE` | `False` |
| `PAPER_ALLOW_MANUAL_CLOSE` | `True` |
| `PAPER_PRICE_SOURCE` | `"queue"` |
| `PAPER_REQUIRE_STOP_LOSS` | `False` |
| `PAPER_REQUIRE_TAKE_PROFIT` | `False` |

Live trading remains disabled: `RuntimeMode.LIVE` always raises `LiveModeDisabledError` regardless of paper configuration, and nothing in the paper runtime or `PaperTradingService` submits broker orders.

## Portfolio Service

`PortfolioService` (`core/services/portfolio_service.py`) is the authoritative **read-only** analytics layer for portfolio state: valuation, exposure, allocation, performance, drawdown, completed-trade statistics, snapshots, and reconciliation reporting. It never creates, fills, or cancels an order, never mutates cash or position quantities, and never submits a broker order - every state-changing paper-trading action remains in `PaperTradingService`. `pages/2_Portfolio.py` is its only current consumer (plus `core/runtime/paper_runtime.py`'s terminal summary); it is designed to also serve a future broker adapter and API layer without change, per the milestone's target architecture:

```text
PaperTradingService ───────┐
BacktestService ───────────┤   (future integration)
Future Broker Adapter ─────┼──► PortfolioService
Dashboard / API ───────────┘
                                  │
                                  ├── valuation, exposure, allocation
                                  ├── performance, drawdown
                                  ├── portfolio snapshots
                                  └── reconciliation views
```

Key points:

- **Reads the same rows `PaperTradingService` reads, not `PaperTradingService`'s own objects.** `PortfolioService` is injected with the same repository-level functions (`get_account_row`, `get_all_position_rows`, `get_trade_rows` from `core/execution/paper_orders_repository.py`) rather than wrapping `PaperTradingService.get_account()`/`get_positions()`/`get_trades()`. This lets it expose richer analytics fields (cost basis, portfolio weight, exposure, performance) without `PaperTradingService`'s own models needing to grow them, and keeps the two services as peers rather than one wrapping the other. The one deliberate exception is reconciliation: `PortfolioService.get_reconciliation()` surfaces, rather than duplicates, an injected `PaperTradingService.reconcile()` (defaulting to constructing one against the same `db_path` if none is injected).
- **Portfolio equations** (all division-by-zero-guarded via a private `_safe_pct` helper, returning `None` rather than raising or fabricating a value):
  ```text
  cost_basis           = quantity × average_entry_price
  market_value         = quantity × current_price
  unrealised_pnl        = market_value - cost_basis
  equity                = cash + sum(market_value of open positions)
  total_pnl              = realised_pnl + unrealised_pnl
  total_return_pct       = total_pnl / starting_capital × 100
  gross_exposure_pct     = sum(abs(market_value)) / equity × 100
  net_exposure_pct       = sum(signed market_value) / equity × 100
  position_weight_pct    = position market_value / equity × 100
  ```
  `unrealised_pnl` is computed once and is never added into `equity` a second time - `equity` is `cash + market_value` only. Because the platform is long-only, `gross_exposure_pct` and `net_exposure_pct` are currently numerically identical; the two are kept as separate fields for when short positions exist.
- **Typed models** (`core/services/portfolio_service.py`): `PortfolioPosition`, `PortfolioSummary`, `PortfolioPerformance`, `PortfolioSnapshot`, and `PortfolioAnalysis` (the aggregate: summary + positions + performance + allocation + snapshots + warnings + reconciliation) - all distinct from `PaperTradingService`'s `PaperAccount`/`PaperPosition`/`PaperTrade`, since they carry different (richer, display-oriented) fields.
- **Portfolio snapshots** (`portfolio_snapshots` table, additive - see `docs/database.md`; persistence in `core/portfolio/portfolio_repository.py`, mirroring `paper_orders_repository.py`'s convention): snapshot creation is an **explicit** action (`PortfolioService.create_snapshot()`) - never written invisibly on a read. `get_snapshots(limit=None)` returns them in chronological order (oldest first, matching equity-curve plotting order).
- **Performance metrics from snapshots**: the equity curve, drawdown, volatility, Sharpe, and Sortino are built entirely from `portfolio_snapshots`, not fabricated. Because snapshots are explicit/user-triggered rather than fixed daily bars (unlike `BacktestService`'s bar-by-bar equity curve with its 252-trading-day annualisation), these statistics are deliberately **unannualised, per-snapshot-period** figures - forcing `BacktestService`'s daily-bar assumption onto arbitrary-cadence snapshots would misrepresent them. With zero snapshots, all of these fields are `None` and a warning is added; with exactly one snapshot, drawdown is trivially `0%` but volatility/Sharpe/Sortino still require a second snapshot and stay `None` with a warning. Completed-trade statistics (win rate, profit factor, expectancy, average win/loss, total fees) are computed directly from `paper_trades` rows with a non-null `exit_reason`, independent of snapshots.
- **Error hierarchy**: `PortfolioServiceError` → `PortfolioDataError`, `SnapshotPersistenceError` - the same one-base-plus-specific-subclasses convention as the other services.
- **No broker path, no Streamlit import, no direct SQL**: enforced by AST-based import-boundary tests (`tests/unit/test_portfolio_service.py`), matching `PaperTradingService`'s own guard tests.

### Portfolio Page

`pages/2_Portfolio.py` is a thin, read-only analytics adapter: it constructs both `PaperTradingService` (for the one state-changing action - "Refresh Position Prices", which calls `update_positions`/`check_exits`) and `PortfolioService` (for everything else), calls `PortfolioService.get_analysis()` once, and renders the result directly - it performs no allocation, average-position, largest-position, or any other statistic calculation itself. It shows controlled warnings for insufficient snapshot history, a reconciliation success/mismatch banner, and an explicit "Create Portfolio Snapshot" button.

### Known limitations / deferred work

- Long-only: `gross_exposure_pct`/`net_exposure_pct` are currently always equal; the formula already keeps them as separate fields for when short positions are introduced.
- No sector/asset-class metadata, so allocation is per-symbol only.
- No benchmark attribution (unlike `BacktestService`'s buy-and-hold comparison).
- Historical performance metrics (equity curve, drawdown, volatility, Sharpe, Sortino) are only as good as the snapshot history that exists - there is no scheduled/automatic snapshot creation in this milestone, only the explicit page button and (optionally) runtime-triggered reads via `get_summary()`, which does **not** create a snapshot.
- No live broker portfolio state - `PortfolioService` only ever reads the local paper account.