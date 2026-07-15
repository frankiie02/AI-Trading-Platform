# Changelog

## Unreleased

### Added
- Minimal application bootstrap (`core/runtime/application.py`, `TradingApplication`)
- Typed runtime-mode enum: research, scanner, backtest, optimisation, paper, live (`core/runtime/modes.py`)
- Runtime router with controlled, trading-logic-free responses per mode (`core/runtime/router.py`)
- `RUNTIME_MODE` configuration default (`config/defaults.py`, default `research`)
- Replaced broken legacy `main.py` with a minimal entry point that constructs and runs `TradingApplication`
- Unit tests for runtime modes, router, application bootstrap, and the new `main.py`
- `ScannerService` (`core/services/scanner_service.py`): reusable, Streamlit-free orchestration of the Live Scanner business workflow (market data → single-strategy signals → regime filter → risk → alpha score/grade → queue eligibility → BUY/NO TRADE), with per-symbol failure isolation and injected collaborators for testability
- Unit tests for `ScannerService` covering symbol normalisation, per-symbol error isolation, regime/alpha/risk behaviour, persistence and trade-queue orchestration, progress-callback handling, and import-boundary checks
- **Strategy-voting support in `ScannerService`**: `ScanRequest.strategy_mode` (`ScanStrategyMode.SINGLE` / `VOTING`, defaults to `SINGLE` for backward compatibility) selects between the existing single-strategy path (unchanged) and a new voting path that invokes the existing voting engine (`run_strategy_voting`) and normalises its result into the same `SymbolScanOutcome` shape, so regime, alpha, risk, persistence, and ranking all remain shared. Voting-only fields (`vote_score`, `buy_votes`, `total_votes`, `strategy_votes`) are added to `SymbolScanOutcome`/`to_legacy_dict()` only for voting outcomes.
- Voting-mode regime allowance: a voting BUY is regime-permitted only when a strict majority of the strategies that voted BUY are individually allowed to trade in the detected regime (reuses the existing `strategy_allowed()` rule; no new regime formula).
- `Trend Momentum` strategy adapted to the registry contract (dropped redundant self-enrichment, added `Signal Confidence`/`Signal Reason`/`Strategy Name`, trading calculation unchanged) and registered in `core/strategy/registry.py`; included in strategy voting.
- Standalone scanner runtime (`core/runtime/scanner_runtime.py`, `run_scanner`): `RuntimeRouter` now dispatches `RuntimeMode.SCANNER` to it instead of returning a placeholder "not implemented" result. Builds a `ScanRequest` from the new `SCANNER_*` settings (`config/defaults.py`) and runs it through `ScannerService`, returning a concise `RuntimeResult` summary. Never queues trades by default (`SCANNER_QUEUE_TRADES=False`); whole-scan persistence failures propagate as controlled `ScannerPersistenceError`/`TradeQueuePersistenceError` rather than being swallowed.
- `pages/1_Live_Scanner.py` rewritten as a thin UI adapter: builds a `ScanRequest` from widget values (including a new Single Strategy / Strategy Voting mode control), calls `ScannerService.scan()` with a progress callback, and renders `ScanResult`. No longer imports market data, strategy generation, regime, alpha, risk, or persistence collaborators directly; only the historical-read functions (`get_recent_scanner_results`, `get_recent_buy_signals`) remain.
- Unit tests: `tests/unit/test_scanner_runtime.py`, `tests/unit/test_strategy_registry.py`, `tests/unit/test_live_scanner_page.py` (Streamlit `AppTest` in-process harness — no real server), plus voting-mode coverage added to `tests/unit/test_scanner_service.py` and a scanner-routing test added to `tests/unit/test_runtime_router.py`.
- **Shared `TradingPipeline`** (`core/pipeline/`): extracted the reusable market data → indicators → strategy/voting → regime → alpha → risk → decision workflow that previously lived inside `ScannerService` into a standalone, injectable `TradingPipeline.evaluate()` (`core/pipeline/trading_pipeline.py`), operating on a typed `TradingPipelineRequest` and returning a typed `TradingDecision` (`core/pipeline/models.py`). `ScanStrategyMode` now lives in `core/pipeline/models.py` and is re-exported from `core.services.scanner_service` for backward compatibility. `TradingPipeline` performs no market-data downloading, persistence, database access, broker submission, or Streamlit rendering; operational failures are raised as typed exceptions (`InsufficientDataError`, `InvalidStrategyConfigurationError`, `PipelineEvaluationError`, all subclasses of `TradingPipelineError`) instead of being encoded as trading signals. Behaviour (single-strategy and voting paths, regime rules, alpha/risk formulas, final BUY/NO TRADE rules) is unchanged — verified against the pre-extraction implementation with an identical-fake-collaborator before/after comparison.
- `tests/unit/test_trading_pipeline.py`: new focused `TradingPipeline` test suite (successful single/voting evaluation, collaborator invocation, insufficient/missing data, strategy/voting/indicator exceptions, regime filter enabled/disabled, single and voting regime approval/rejection including the zero-BUY-vote and exactly-half-allowed voting cases, alpha threshold boundary, risk values, queue eligibility, optional voting metadata, and import/isolation guards).

- **`BacktestService`** (`core/services/backtest_service.py`): reusable, Streamlit-free historical-backtesting workflow, reusing `TradingPipeline.evaluate()` per historical bar exactly as `ScannerService` reuses it per symbol. For every bar `t`, evaluates the pipeline on `data.iloc[:t+1]` only (anti-lookahead), and on a BUY decision opens a discrete long position at the next bar's Open, sized/stopped/targeted using `TradingPipeline`'s existing ATR-based risk-engine output. Stop-loss/take-profit are checked every bar from entry onward using that bar's High/Low (adverse-first same-bar collision assumption); any position still open at the final bar is force-closed at the final close. Supports both `ScanStrategyMode.SINGLE` and `ScanStrategyMode.VOTING`, inheriting the strict-majority voting-regime rule, alpha filtering, and risk controls with no new formula. New typed models: `BacktestRequest`, `BacktestTrade`, `BacktestResult`. Computes its own equity curve and metrics (final equity, total/annualised return, volatility, Sharpe, Sortino, max drawdown, win rate, profit factor, expectancy, total trades, average win/loss, exposure, fees, and a buy-and-hold benchmark) directly from the simulated trades, since the pre-existing `core/analytics/performance.py` return-multiplier model never supported stops/targets/sizing/voting and could not satisfy the new trade contract. Performs no persistence, no broker/live calls, and no market-data downloading beyond the injected collaborator.
- Standalone backtest runtime (`core/runtime/backtest_runtime.py`, `run_backtest`): `RuntimeRouter` now dispatches `RuntimeMode.BACKTEST` to it instead of returning a placeholder "not implemented" result, mirroring the scanner runtime's shape exactly. Builds a `BacktestRequest` from the new `BACKTEST_*` settings (`config/defaults.py`) and runs it through `BacktestService`, returning a concise `RuntimeResult` summary (symbol, trade count, total return, max drawdown, final equity).
- `pages/3_Backtesting.py` rewritten as a thin UI adapter: builds a `BacktestRequest` from widget values (including a new Single Strategy / Strategy Voting mode control, regime-filter/risk/ATR/reward-risk/minimum-alpha-score/commission/slippage inputs, mirroring the Live Scanner page's UX), calls `BacktestService.run()`, and renders the returned `BacktestResult` (metrics, equity curve, trade log, warnings/controlled errors). No longer imports market data, `TradingPipeline`, strategy/voting engines, regime/alpha/risk internals, or `core/analytics/performance.py` directly.
- Unit tests: `tests/unit/test_backtest_service.py` (valid/invalid requests, market-data failures, single/voting decisions, anti-lookahead slicing, entry timing, stop-loss/take-profit/adverse-first-collision exits, final-bar forced close, one-position-at-a-time, position sizing/commission/slippage, cash/equity/trade recording, return/drawdown/win-rate/profit-factor metrics, partial per-bar decision-failure isolation, no real network/database calls, import-boundary guards), `tests/unit/test_backtest_runtime.py` (request building, service delegation, summary formatting, controlled error propagation, import-boundary guards), plus a backtest-dispatch test added to `tests/unit/test_runtime_router.py` and a Streamlit `AppTest` in-process page suite (`tests/unit/test_backtesting_page.py`).

### Changed
- `RuntimeRouter._NOT_YET_IMPLEMENTED_MODES` no longer includes `backtest` (it now has a real standalone runtime, dispatched lazily inside `route()` exactly like `scanner`); `research` and `paper` remain placeholders.
- `ScannerService` (`core/services/scanner_service.py`) no longer imports or directly invokes the strategy engine, voting engine, indicator pipeline, regime detector/filter, alpha scorer/grader, or risk calculators. It now downloads market data, builds a `TradingPipelineRequest` per symbol, and delegates the decision to an injected `TradingPipeline` (constructor parameter `pipeline`, defaulting to `TradingPipeline()`), mapping the returned `TradingDecision` into the existing `SymbolScanOutcome`. Symbol iteration, per-symbol exception isolation, progress callbacks, persistence, trade-queue writes, ranking, and scan statistics all remain in `ScannerService`, unchanged. The public `ScannerService`/`ScanRequest`/`ScanResult`/`ScanStrategyMode` API used by `pages/1_Live_Scanner.py` and `core/runtime/scanner_runtime.py` is unaffected; only `ScannerService.__init__`'s fine-grained collaborator parameters (`strategy_fn`, `voting_fn`, `indicator_pipeline_fn`, `regime_detector`, `regime_allowance_fn`, `alpha_score_fn`, `alpha_grade_fn`, `queue_eligibility_fn`, `stop_loss_fn`, `take_profit_fn`, `position_size_fn`) were replaced by the single `pipeline` parameter — tests inject fakes into `TradingPipeline` instead.
- `tests/unit/test_scanner_service.py` rewritten to build a `TradingPipeline` with fake collaborators (via a `build_pipeline`/`build_service` helper) instead of injecting collaborators directly into `ScannerService`; added regression tests confirming `ScannerService` delegates to `TradingPipeline`, no longer imports the decision-workflow collaborator modules directly, and isolates per-symbol pipeline failures.
- `RuntimeRouter._NOT_YET_IMPLEMENTED_MODES` no longer includes `scanner` (it now has a real standalone runtime); `research`, `backtest`, `paper` remain placeholders.
- `tests/unit/test_scanner_service.py`'s forbidden-import guard no longer forbids `core.voting`: `ScannerService` is now required to invoke the voting engine directly (this restriction only applied while voting was explicitly deferred).

### Notes
- Live mode is hard-disabled: `RuntimeRouter` always raises `LiveModeDisabledError` for `live`. Nothing added in this change submits broker orders.
- `BacktestService` performs no persistence: backtest results are returned in-memory only, and the SQLite schema is unchanged (no new tables).
- Standalone `research`/`paper` runtime services remain not yet implemented; the router still returns a controlled "not implemented" result for them.
- The Streamlit dashboard (`streamlit run dashboard.py`) remains a separate entry point; `ScannerService` has no Streamlit dependency.
- Scanner-result persistence and trade-queue writes remain delegated to the existing `save_scanner_results` and `save_buy_signals_to_queue` functions; `ScannerService` does not duplicate or alter their database logic. **The `scanner_results` database schema is unchanged** — voting metadata (vote score, buy/total votes, per-strategy votes) is therefore available in memory and in the ranked table only, and is not persisted.

## v0.5.0 (In Progress)

### Added
- Core trading engine architecture
- Market data service
- Strategy engine
- Risk engine
- Analytics engine
- SQLite database initialization
- Paper trading engine
- Git + GitHub integration
- Develop branch

### Changed
- Backtesting migrated to core modules
- Project structure consolidated

### Next
- Database-backed paper trader
- Portfolio database service
- Scanner database service
- Live Scanner migration to core