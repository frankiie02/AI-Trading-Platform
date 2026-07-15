# Roadmap

## Completed

- Market data service
- Technical indicators
- Strategy framework
- Strategy registry
- EMA Trend strategy
- RSI Pullback strategy
- Breakout strategy
- MACD Momentum strategy
- Trend Momentum strategy
- Alpha scoring engine
- Market regime engine
- Live scanner
- Backtesting
- SQLite database
- Paper trading
- Trade queue
- Execution router
- Portfolio monitoring
- Order management
- Strategy voting engine
- Runtime bootstrap and application architecture (`TradingApplication`, `RuntimeRouter`, `RuntimeMode`)
- Reusable `ScannerService` (single-strategy and strategy-voting modes), wired into both the Live Scanner Streamlit page and the standalone `scanner` runtime mode

## Next

- Bollinger Reversal strategy
- ADX Trend Strength strategy
- SuperTrend strategy
- Configuration cleanup
- IBKR paper trading integration
- IBKR live trading integration
- Standalone `research`/`backtest`/`paper` runtime services (currently placeholder "not implemented" results)
- Voting metadata persistence (would require a `scanner_results` schema change; currently in-memory/display-only)