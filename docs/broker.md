# Broker Integration

**There is still no external broker integration in this codebase.** `core/broker/` now defines a stable, broker-neutral contract (`BrokerInterface`) and one concrete adapter, `PaperBroker`, but `PaperBroker` is 100% local and simulated against SQLite via the existing `PaperTradingService`/`PortfolioService` - it never opens a network connection, never uses real credentials, and never submits a real order. See `docs/architecture.md`'s "Broker Interface" section for the full design.

## Current state

- **`core/broker/`** (`base.py`, `models.py`, `errors.py`, `paper_broker.py`, `factory.py`) is implemented. `BrokerInterface` (an `ABC`) defines the contract; `PaperBroker` is the only concrete adapter. No IBKR/Alpaca/OANDA adapter exists.
- `core/execution/execution_router.py`'s `ExecutionRouter` recognises three mode strings - `"PAPER"` (implemented, delegates to the legacy `PaperTrader`), `"IBKR_PAPER"` and `"IBKR_LIVE"` (both stubs that immediately return a failure message: `"IBKR Paper execution is not active yet."` / `"Live trading is disabled for safety."`). Neither stub imports `ib_insync` or any broker SDK. `PaperBroker` has **zero dependency** on `ExecutionRouter` or `PaperTrader` - statically verified by an AST-based test that parses every file in `core/broker/` and asserts neither name appears.
- `config/defaults.py` carries dormant IBKR connection settings (`IBKR_HOST`, `IBKR_PAPER_PORT`, `IBKR_LIVE_PORT`, `IBKR_CLIENT_ID`) and `LIVE_TRADING_ENABLED: False`. Nothing in `core/broker/`, `core/execution/`, `core/portfolio/`, `core/services/paper_trading_service.py`, or `core/services/portfolio_service.py` reads them.
- The only `ib_insync` import anywhere in the repository is in `archive/legacy_v0_4/broker/ibkr_client.py`, which is archived, dead code, not imported by anything under `core/`, `pages/`, or `main.py`.
- `RuntimeMode.LIVE` always raises `LiveModeDisabledError` in `RuntimeRouter.route()` (`core/runtime/router.py`), regardless of configuration. Live mode is hard-disabled and cannot be enabled by settings alone. Nothing in `core/broker/` changes this.
- `core/broker/models.py`'s `BrokerEnvironment` enum has `PAPER`, `LIVE`, and `SIMULATION` values for future use, but `core/broker/factory.py`'s `create_broker()` raises `BrokerUnsupportedOperationError` for anything other than `BrokerEnvironment.PAPER` - there is no code path that can construct a live or simulation broker today.

## PaperBroker

`PaperBroker` adapts the existing `PaperTradingService` (state mutation) and `PortfolioService` (analytics) to `BrokerInterface` - it is an adapter, not a second execution engine, and duplicates none of their validation, fill, or cash/position logic:

| BrokerInterface method | Delegates to |
|---|---|
| `submit_order` | `PaperTradingService.create_order_from_decision()` (builds a minimal `TradingDecision` from the request) |
| `cancel_order` | `PaperTradingService.cancel_order()`, unmodified |
| `get_account` | `PortfolioService.get_summary()` |
| `get_positions` | `PortfolioService.get_positions()` |
| `get_open_orders` | `PaperTradingService.get_open_orders()` (new, thin) |
| `get_order` | `PaperTradingService.get_order()` (new, thin) |
| `get_fills` | `core.execution.paper_orders_repository.get_trade_rows()` (existing repository read, unfiltered) |

Only `MARKET` orders and the `BUY` side are supported (long-only, no short selling, no leverage - unchanged platform-wide rules). A `MARKET` order's `limit_price` field doubles as the required explicit fill-reference price, since there is no real market-data feed to fill against. Business-rule rejections (insufficient cash, etc.) come back as `BrokerOrder(status=REJECTED, ...)`, never an exception; malformed requests raise `BrokerValidationError`/`BrokerUnsupportedOperationError` before `PaperTradingService` is ever called. See `docs/architecture.md` for the full mapping, connection semantics, and cancellation rules.

`PaperBroker`'s connection state (`connect()`/`disconnect()`) is a pure in-memory simulation for interface parity with brokers that manage a genuine connection - no socket, thread, process, or network call is ever created anywhere in `core/broker/`, and connection state is never persisted to the database.

## PaperTradingService and broker-readiness

`PaperTradingService` (`core/services/paper_trading_service.py`) was deliberately built with a validated order lifecycle (`CREATED -> VALIDATED -> SUBMITTED -> FILLED`/`REJECTED`/`CANCELLED`/`EXPIRED`), typed `PaperOrder`/`PaperPosition`/`PaperTrade` models, and deterministic fill/slippage/commission conventions so that `PaperBroker` - and a future `IBKRBroker`/`AlpacaBroker`/`OANDABroker` behind the same `BrokerInterface` - could reuse the same shape without reimplementing order validation, cash/position-limit sizing, or `TradingDecision` consumption. `PaperTradingService` never imports `core.broker` (enforced by an AST-based import-boundary test in `tests/unit/test_paper_trading_service.py`); the dependency only runs one way, `core.broker` → `core.services`.

## Out of scope (this milestone and currently)

- Interactive Brokers, Alpaca, OANDA, or any other concrete broker adapter.
- Real market orders, real credentials, network calls, or live execution of any kind.
- Enabling `RuntimeMode.LIVE`.
- Wiring `BrokerInterface`/`PaperBroker` into any Streamlit page or runtime mode - this milestone establishes and tests the abstraction only.
- Order replace/amend, short selling, leverage, margin, options, futures, multi-currency accounting.
