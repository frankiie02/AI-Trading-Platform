# Broker Integration

`core/broker/` defines a stable, broker-neutral contract (`BrokerInterface`) and two concrete adapters: `PaperBroker` (100% local, simulated against SQLite via `PaperTradingService`/`PortfolioService`) and `IBKRBroker` (a **read-only** Interactive Brokers adapter - account/position/order/fill inspection only). Neither adapter can submit, cancel, or modify a real order: `PaperBroker` only ever simulates fills locally, and `IBKRBroker.submit_order()`/`cancel_order()` always raise `BrokerUnsupportedOperationError` without any order-transmission code existing anywhere in the file. See `docs/architecture.md`'s "Broker Interface" section for the full design.

## Current state

- **`core/broker/`** (`base.py`, `models.py`, `errors.py`, `paper_broker.py`, `ibkr_broker.py`, `ibkr_client.py`, `factory.py`) is implemented. `BrokerInterface` (an `ABC`) defines the contract; `PaperBroker` and `IBKRBroker` are the two concrete adapters. No Alpaca/OANDA adapter exists.
- `core/execution/execution_router.py`'s `ExecutionRouter` recognises three mode strings - `"PAPER"` (implemented, delegates to the legacy `PaperTrader`), `"IBKR_PAPER"` and `"IBKR_LIVE"` (both stubs that immediately return a failure message: `"IBKR Paper execution is not active yet."` / `"Live trading is disabled for safety."`). `IBKRBroker` is **not** wired into `ExecutionRouter`, any Streamlit page, or any runtime mode - it exists only as a directly-constructible adapter for manual/scripted account inspection. `PaperBroker` and `IBKRBroker` both have **zero dependency** on `ExecutionRouter` or `PaperTrader` - statically verified by AST-based tests that parse every file in `core/broker/` and assert neither name appears.
- `config/defaults.py` carries dormant IBKR connection settings (`IBKR_HOST`, `IBKR_PAPER_PORT`, `IBKR_LIVE_PORT`, `IBKR_CLIENT_ID`) and `LIVE_TRADING_ENABLED: False`. Nothing in `core/broker/`, `core/execution/`, `core/portfolio/`, `core/services/paper_trading_service.py`, or `core/services/portfolio_service.py` reads them - `IBKRBroker` is configured directly via `IBKRConnectionConfig`, not through `config/defaults.py`.
- The optional `ib_insync` package (only used by `core/broker/ibkr_client.py`'s `IBInsyncClient`) is guarded: importing `core.broker` (or any module in it) never fails when `ib_insync` is not installed. Only constructing a real `IBInsyncClient` - which `IBKRBroker` does lazily, and only when no fake/test client is injected - requires the package; if it is missing, that construction raises a controlled `BrokerConnectionError` rather than an `ImportError`. The only other `ib_insync` import anywhere in the repository is in `archive/legacy_v0_4/broker/ibkr_client.py`, which is archived, dead code, not imported by anything under `core/`, `pages/`, or `main.py`.
- `RuntimeMode.LIVE` always raises `LiveModeDisabledError` in `RuntimeRouter.route()` (`core/runtime/router.py`), regardless of configuration. Live mode is hard-disabled and cannot be enabled by settings alone. Nothing in `core/broker/` changes this.
- `core/broker/models.py`'s `BrokerEnvironment` enum has `PAPER`, `LIVE`, and `SIMULATION` values for future use, but `core/broker/factory.py`'s `create_broker()` raises `BrokerUnsupportedOperationError` for anything other than `BrokerEnvironment.PAPER` - there is no code path that can construct a live or simulation broker today. `IBKRConnectionConfig.__post_init__` separately fails closed: constructing a config with `read_only=False` or `environment=BrokerEnvironment.LIVE` raises immediately, before any connection is attempted.

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

## IBKRBroker (read-only)

`IBKRBroker` (`core/broker/ibkr_broker.py`) implements `BrokerInterface` for **account inspection only** against Interactive Brokers via [`ib_insync`](https://ib-insync.readthedocs.io/). It is deliberately incapable of placing, cancelling, or modifying an order:

- `submit_order()` and `cancel_order()` always raise `BrokerUnsupportedOperationError` immediately - no third-party order-placement or cancellation method (`placeOrder`, `cancelOrder`, `reqGlobalCancel`, IB order-transmission flags) is referenced anywhere in `ibkr_broker.py` or `ibkr_client.py`. This is statically proven by `tests/unit/test_ibkr_broker.py`.
- `IBKRConnectionConfig` (host, port, client_id, optional account_id, timeout, `read_only`, `environment`) fails closed at construction time: `read_only=False` or `environment=BrokerEnvironment.LIVE` raise `BrokerValidationError`/`BrokerUnsupportedOperationError` before any connection attempt is possible.
- Connection is a single, explicitly-bounded (`config.timeout`) call into an injected `IBKRClientProtocol` - there is no automatic reconnection, retry loop, background worker, thread, or process anywhere in the adapter. `connect()`/`disconnect()` are idempotent, mirroring `PaperBroker`'s connection-state semantics.
- **Prerequisite**: a running IB Gateway or TWS instance with API access enabled, reachable at the configured host/port. Setting this up is outside the scope of this codebase; see Interactive Brokers' own documentation. `IBKRBroker` never launches, configures, or manages IB Gateway/TWS itself.
- **Dependency**: `ib_insync` is optional. Install it (`pip install ib_insync`) only if you intend to actually connect; importing `core.broker` never requires it. If it is missing and no fake client was injected, constructing the default client raises `BrokerConnectionError` with a clear message - never an `ImportError` that could break the rest of the platform.
- **Account mapping**: `equity` is read verbatim from IBKR's own `NetLiquidation` account tag (never recomputed as `cash + market_value`, so unrealised P&L is never double-counted). `reserved_cash` is always reported as `0.0` (no IBKR equivalent is surfaced in this milestone - documented, not fabricated). If more than one IBKR account is returned and no `account_id` was configured to disambiguate, `get_account()`/`get_positions()` raise `BrokerValidationError` rather than guessing.
- **Position mapping**: no market data is fetched. `current_price`, `market_value`, and `unrealised_pnl` on every `BrokerPosition` are always `None` - never a fabricated number. Only `average_entry_price` (from IBKR's `avgCost`) and `quantity` are populated from real data.
- **Order/fill mapping**: IBKR order statuses are mapped to the broker-neutral `BrokerOrderStatus` vocabulary; an unrecognised status falls back to `PENDING` (the safest neutral value) with the raw IBKR string preserved in `metadata["raw_status"]`. `get_order(order_id)` only searches currently-open orders - a read-only adapter has no separate persisted order history, so a filled/cancelled order that has aged out of IBKR's open-orders view returns `None`, not an error. Fills are deduplicated by IBKR's execution ID and returned in chronological order; `limit` returns the most recent N.
- **Logging**: connection attempts, successful connects/disconnects, and read counts are logged at `INFO`. Account identifiers are masked in log messages (e.g. `DU****23`) - the typed `BrokerAccount`/`BrokerPosition` objects returned to the caller still carry the real, unmasked identifier, since that is the caller's explicit request. No credentials, full account identifiers, session tokens, or raw `ib_insync` payloads are ever logged.
- **Runtime/UI isolation**: `IBKRBroker` is not referenced by `TradingApplication`, `RuntimeRouter`, `paper_runtime.py`, any Streamlit page, the Trade Queue, the scanner, or backtesting. No runtime mode invokes it and no UI control exists for it. It is only reachable by directly constructing `IBKRBroker`/`IBKRConnectionConfig` or calling `core.broker.factory.create_ibkr_broker()` from a script or test.
- **Testing**: `tests/unit/test_ibkr_broker.py` covers connection, account/position/order/fill mapping, read-only enforcement, and architectural isolation entirely against a hand-built fake client (`FakeIBKRClient`) - no real socket or database access occurs. An opt-in integration test (`tests/integration/test_ibkr_broker_integration.py`) exists for manually verifying against a real IB Gateway/TWS paper account; it is skipped unless `RUN_IBKR_INTEGRATION_TESTS=1` plus `IBKR_HOST`/`IBKR_PORT`/`IBKR_CLIENT_ID` are all set, is never run automatically, and only performs read operations (it also re-verifies `submit_order()`/`cancel_order()` still raise even against a live connection).

## PaperTradingService and broker-readiness

`PaperTradingService` (`core/services/paper_trading_service.py`) was deliberately built with a validated order lifecycle (`CREATED -> VALIDATED -> SUBMITTED -> FILLED`/`REJECTED`/`CANCELLED`/`EXPIRED`), typed `PaperOrder`/`PaperPosition`/`PaperTrade` models, and deterministic fill/slippage/commission conventions so that `PaperBroker` - and a future `IBKRBroker`/`AlpacaBroker`/`OANDABroker` behind the same `BrokerInterface` - could reuse the same shape without reimplementing order validation, cash/position-limit sizing, or `TradingDecision` consumption. `PaperTradingService` never imports `core.broker` (enforced by an AST-based import-boundary test in `tests/unit/test_paper_trading_service.py`); the dependency only runs one way, `core.broker` → `core.services`.

## Out of scope (currently)

- Order submission, cancellation, or modification through IBKR - `IBKRBroker` is permanently read-only in its current form; this is not a "not yet implemented" gap but a deliberate safety boundary.
- Alpaca, OANDA, or any other concrete broker adapter.
- Real credentials, live execution, or automatic reconnection/polling of any kind.
- Enabling `RuntimeMode.LIVE`.
- Wiring `BrokerInterface`/`PaperBroker`/`IBKRBroker` into any Streamlit page or runtime mode - both adapters are directly constructible for scripts/tests only.
- Market-data streaming, historical data, options/futures/forex, multi-currency aggregation, advisor-account aggregation, or reconciling IBKR positions against local paper-trading state.
- Order replace/amend, short selling, leverage, margin.
