# Broker Integration

**There is no broker integration in this codebase.** All trading in this repository - the Streamlit Paper Trading / Order Management / Portfolio / Trade History pages, `PaperTradingService`, the legacy `PaperTrader`, and the standalone `paper` runtime mode - is 100% local and simulated against SQLite. Nothing submits a real order, connects to a broker API, or uses real credentials.

## Current state

- `core/broker/` exists only as an empty package (`__init__.py`, no other files) - a placeholder for a future broker-abstraction milestone, not yet implemented.
- `core/execution/execution_router.py`'s `ExecutionRouter` recognises three mode strings - `"PAPER"` (implemented, delegates to `PaperTrader`), `"IBKR_PAPER"` and `"IBKR_LIVE"` (both stubs that immediately return a failure message: `"IBKR Paper execution is not active yet."` / `"Live trading is disabled for safety."`). Neither stub imports `ib_insync` or any broker SDK.
- `config/defaults.py` carries dormant IBKR connection settings (`IBKR_HOST`, `IBKR_PAPER_PORT`, `IBKR_LIVE_PORT`, `IBKR_CLIENT_ID`) and `LIVE_TRADING_ENABLED: False`. Nothing in `core/execution/`, `core/portfolio/`, or `core/services/paper_trading_service.py` reads them.
- The only `ib_insync` import anywhere in the repository is in `archive/legacy_v0_4/broker/ibkr_client.py`, which is archived, dead code, not imported by anything under `core/`, `pages/`, or `main.py`.
- `RuntimeMode.LIVE` always raises `LiveModeDisabledError` in `RuntimeRouter.route()` (`core/runtime/router.py`), regardless of configuration. Live mode is hard-disabled and cannot be enabled by settings alone.

## PaperTradingService and broker-readiness

`PaperTradingService` (`core/services/paper_trading_service.py`) was deliberately built with a validated order lifecycle (`CREATED -> VALIDATED -> SUBMITTED -> FILLED`/`REJECTED`/`CANCELLED`/`EXPIRED`), typed `PaperOrder`/`PaperPosition`/`PaperTrade` models, and deterministic fill/slippage/commission conventions so that a future `LiveTradingService` could reuse the same shape (order validation, cash/position-limit sizing, `TradingDecision` consumption) behind a real broker adapter - but this milestone explicitly does **not** implement that adapter, broker credentials, or any live order path. `PaperTradingService` never imports `core.broker` or `ib_insync` (enforced by an AST-based import-boundary test, `tests/unit/test_paper_trading_service.py`).

## Out of scope (this milestone and currently)

- Interactive Brokers, Alpaca, OANDA, or any other broker adapter.
- Real market orders, real credentials, or live execution of any kind.
- Enabling `RuntimeMode.LIVE`.
