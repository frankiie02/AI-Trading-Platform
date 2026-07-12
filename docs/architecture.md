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