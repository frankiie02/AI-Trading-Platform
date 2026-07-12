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

### Notes
- Live mode is hard-disabled: `RuntimeRouter` always raises `LiveModeDisabledError` for `live`.
- Standalone `research`/`scanner`/`backtest`/`paper` runtime services are not yet implemented; the router returns a controlled "not implemented" result for them.
- The Streamlit dashboard (`streamlit run dashboard.py`) remains a separate, unaffected entry point.
- `ScannerService` is not yet wired into `pages/1_Live_Scanner.py`; the page is unchanged and still runs its own inline workflow.
- `ScannerService` preserves the existing single-strategy path only; strategy voting (`core/voting/`) remains deferred and is not invoked.
- Scanner-result persistence and trade-queue writes remain delegated to the existing `save_scanner_results` and `save_buy_signals_to_queue` functions; `ScannerService` does not duplicate or alter their database logic.

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