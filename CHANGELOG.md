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

### Changed
- `RuntimeRouter._NOT_YET_IMPLEMENTED_MODES` no longer includes `scanner` (it now has a real standalone runtime); `research`, `backtest`, `paper` remain placeholders.
- `tests/unit/test_scanner_service.py`'s forbidden-import guard no longer forbids `core.voting`: `ScannerService` is now required to invoke the voting engine directly (this restriction only applied while voting was explicitly deferred).

### Notes
- Live mode is hard-disabled: `RuntimeRouter` always raises `LiveModeDisabledError` for `live`. Nothing added in this change submits broker orders.
- Standalone `research`/`backtest`/`paper` runtime services remain not yet implemented; the router still returns a controlled "not implemented" result for them.
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