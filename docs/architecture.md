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