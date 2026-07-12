# Changelog

## Unreleased

### Added
- Minimal application bootstrap (`core/runtime/application.py`, `TradingApplication`)
- Typed runtime-mode enum: research, scanner, backtest, optimisation, paper, live (`core/runtime/modes.py`)
- Runtime router with controlled, trading-logic-free responses per mode (`core/runtime/router.py`)
- `RUNTIME_MODE` configuration default (`config/defaults.py`, default `research`)
- Replaced broken legacy `main.py` with a minimal entry point that constructs and runs `TradingApplication`
- Unit tests for runtime modes, router, application bootstrap, and the new `main.py`

### Notes
- Live mode is hard-disabled: `RuntimeRouter` always raises `LiveModeDisabledError` for `live`.
- Standalone `research`/`scanner`/`backtest`/`paper` runtime services are not yet implemented; the router returns a controlled "not implemented" result for them.
- The Streamlit dashboard (`streamlit run dashboard.py`) remains a separate, unaffected entry point.

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