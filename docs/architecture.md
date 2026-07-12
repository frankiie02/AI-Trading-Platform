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

`RuntimeRouter` (`core/runtime/router.py`) dispatches the resolved mode. In this first version it contains no trading logic:

- `research`, `scanner`, `backtest`, `paper`: recognised, but their standalone runtime services are not yet implemented — the router returns a controlled `RuntimeResult` describing this.
- `optimisation`: raises `UnsupportedRuntimeModeError` (not implemented yet).
- `live`: always raises `LiveModeDisabledError`. Live trading is hard-disabled and is not activated by this bootstrap.

The existing Streamlit dashboard (`streamlit run dashboard.py` and `pages/`) remains a separate, independent entry point and is unaffected by this bootstrap. It is not launched by `main.py`, and `main.py` does not import Streamlit, broker, execution, or strategy modules.

## Scanner Service (Stage 1)

`ScannerService` (`core/services/scanner_service.py`) extracts the Live Scanner business workflow currently embedded in `pages/1_Live_Scanner.py` into a reusable, testable service. It preserves the existing single-strategy scan path exactly:

```text
market data → strategy signals → regime detection → regime filter → risk (stop-loss / take-profit / position size) → alpha score → alpha grade → queue eligibility → BUY / NO TRADE decision
```

Key points:

- The service is not yet wired into the Streamlit page. `pages/1_Live_Scanner.py` is unchanged and continues to run its own inline workflow.
- Strategy voting (`core/voting/`) is not integrated; the service calls the existing single-strategy pipeline only (`generate_strategy_signals`).
- Every external collaborator (market data, strategy generation, regime detection/filter, alpha scoring/grading, risk calculations, scanner-result persistence, trade-queue persistence, ranking) is injected via constructor defaults, so the service contains no Streamlit, database, or broker code directly and can be tested with fakes.
- Each symbol is processed with its own exception handling; one symbol's failure (missing data, insufficient indicator history, or an unexpected error) produces a controlled error outcome (`SymbolScanOutcome`) without stopping the rest of the scan.
- Persistence and trade-queue writes remain fully delegated to the existing `save_scanner_results` and `save_buy_signals_to_queue` collaborators — the service does not duplicate their database logic. A failure in either raises a dedicated `ScannerPersistenceError` / `TradeQueuePersistenceError` rather than being silently swallowed.
- `SymbolScanOutcome.to_legacy_dict()` reproduces the exact dictionary shape the existing repository, trade-queue, and ranking functions expect, so those consumers require no changes.