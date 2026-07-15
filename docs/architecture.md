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

- `research`, `backtest`, `paper`: recognised, but their standalone runtime services are not yet implemented — the router returns a controlled `RuntimeResult` describing this.
- `scanner`: dispatches to the standalone scanner runtime (`core/runtime/scanner_runtime.py`, see below), imported lazily inside `route()` so the router's own module-level imports stay free of scanner/market-data/database dependencies.
- `optimisation`: raises `UnsupportedRuntimeModeError` (not implemented yet).
- `live`: always raises `LiveModeDisabledError`. Live trading is hard-disabled and is not activated by this bootstrap.

The existing Streamlit dashboard (`streamlit run dashboard.py` and `pages/`) remains a separate, independent entry point and is unaffected by this bootstrap. It is not launched by `main.py`, and `main.py` does not import Streamlit, broker, execution, or strategy modules.

## Scanner Service

`ScannerService` (`core/services/scanner_service.py`) is the single reusable, testable implementation of the Live Scanner business workflow. It is used by both `pages/1_Live_Scanner.py` (Streamlit) and the standalone `scanner` runtime mode:

```text
market data → strategy signals (single-strategy or voting) → regime detection → regime filter → risk (stop-loss / take-profit / position size) → alpha score → alpha grade → queue eligibility → BUY / NO TRADE decision
```

Key points:

- `pages/1_Live_Scanner.py` is a thin UI adapter: it builds a `ScanRequest` from widget values, calls `ScannerService.scan()`, and renders the `ScanResult`. It no longer imports market data, strategy generation, regime, alpha, risk, or persistence collaborators directly — only historical reads (`get_recent_scanner_results`, `get_recent_buy_signals`) remain in the page for the history panels.
- `ScanRequest.strategy_mode` (`ScanStrategyMode` enum: `SINGLE` / `VOTING`) selects between the two supported paths. It defaults to `SINGLE`, so existing callers that never set it are unaffected.
- **Single-strategy path**: unchanged from the original extraction — calls `generate_strategy_signals` (`core/strategy/strategy_engine.py`) via the existing strategy registry.
- **Voting path**: calls the existing voting engine (`run_strategy_voting`, `core/voting/engine.py`) for the BUY/NO TRADE consensus decision, and separately calls `build_indicator_pipeline` (`core/indicators/pipeline.py`) — the same enrichment function the voting engine already uses internally — to obtain the enriched price row that regime detection, alpha scoring, and risk calculations need but the voting engine's dict result does not expose. Both are pure functions of the same input, so this does not duplicate or alter any algorithm; it only assembles the additional input the shared downstream steps require.
  - Voting-mode regime allowance: since `strategy_allowed()` (`core/regime/filters.py`) only evaluates a single named strategy, a voting BUY is regime-permitted only when a **strict majority** of the strategies that voted BUY would individually be allowed to trade in the detected regime. This reuses the existing per-strategy regime rule unchanged; it does not introduce a new regime formula.
  - Voting-mode alpha scoring input: `Trend Filter` and `Volume Filter` are derived from the same primitives every registered strategy already uses (`Short EMA > Long EMA`, `Volume > Volume Average`); `Momentum Filter` is approximated by the voting engine's own consensus gate (`buy_votes >= 2`), since there is no single shared momentum formula across strategies. The alpha-scoring formula itself is untouched.
  - Voting cannot bypass regime, alpha, or risk controls — the same `use_regime_filter` / `minimum_alpha_score` / risk-calculation gates apply to both paths.
- Every external collaborator (market data, strategy generation, voting, indicator pipeline, regime detection/filter, alpha scoring/grading, risk calculations, scanner-result persistence, trade-queue persistence, ranking) is injected via constructor defaults, so the service contains no Streamlit, database, or broker code directly and can be tested with fakes.
- Each symbol is processed with its own exception handling; one symbol's failure (missing data, insufficient indicator history, strategy/voting failure, or an unexpected error) produces a controlled error outcome (`SymbolScanOutcome`, `status="ERROR"`) without stopping the rest of the scan. Error labels (`NO DATA`, `NOT ENOUGH DATA`, `SCAN ERROR`) are distinct sentinel values, never `BUY`/`SELL`/`NO TRADE`.
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