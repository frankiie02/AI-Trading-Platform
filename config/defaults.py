DEFAULT_SETTINGS = {
    "RUNTIME_MODE": "research",

    "STARTING_BALANCE": 100000,
    "EXECUTION_MODE": "PAPER",

    "DATA_PROVIDER": "YAHOO",
    "DEFAULT_PERIOD": "1y",
    "DEFAULT_INTERVAL": "1d",

    "DEFAULT_SYMBOLS": [
        "SPY",
        "QQQ",
        "AAPL",
        "MSFT",
        "NVDA",
        "TSLA",
        "AMD"
    ],

    "DEFAULT_STRATEGY": "EMA Trend",
    "SHORT_EMA": 20,
    "LONG_EMA": 50,
    "RSI_THRESHOLD": 55,
    "USE_VOLUME_FILTER": True,

    "RISK_PER_TRADE": 1.0,
    "ATR_STOP_MULTIPLIER": 2.0,
    "REWARD_RISK_RATIO": 2.0,

    "MINIMUM_ALPHA_SCORE": 70,
    "USE_REGIME_FILTER": True,

    # Standalone scanner runtime (core/runtime/scanner_runtime.py). Kept
    # separate from the interactive-dashboard defaults above so the
    # unattended runtime can use its own small, safe symbol set and default
    # to not queueing trades, without changing the Streamlit page's widgets.
    "SCANNER_SYMBOLS": [
        "SPY",
        "QQQ",
        "AAPL"
    ],
    "SCANNER_STRATEGY_MODE": "single",
    "SCANNER_STRATEGY_NAME": "EMA Trend",
    "SCANNER_PERIOD": "1y",
    "SCANNER_INTERVAL": "1d",
    "SCANNER_SHORT_EMA": 20,
    "SCANNER_LONG_EMA": 50,
    "SCANNER_RSI_THRESHOLD": 55,
    "SCANNER_USE_VOLUME_FILTER": True,
    "SCANNER_USE_REGIME_FILTER": True,
    "SCANNER_RISK_PERCENT": 1.0,
    "SCANNER_ATR_MULTIPLIER": 2.0,
    "SCANNER_REWARD_RISK_RATIO": 2.0,
    "SCANNER_MINIMUM_ALPHA_SCORE": 70,
    "SCANNER_QUEUE_TRADES": False,

    # Standalone backtest runtime (core/runtime/backtest_runtime.py) and the
    # Backtesting Streamlit page (pages/3_Backtesting.py), both of which call
    # BacktestService. Kept separate from SCANNER_*/DEFAULT_* settings so the
    # unattended runtime has its own safe, small default configuration.
    "BACKTEST_SYMBOL": "SPY",
    "BACKTEST_PERIOD": "2y",
    "BACKTEST_INTERVAL": "1d",
    "BACKTEST_STRATEGY_MODE": "single",
    "BACKTEST_STRATEGY": "EMA Trend",
    "BACKTEST_INITIAL_CAPITAL": 100000,
    "BACKTEST_SHORT_EMA": 20,
    "BACKTEST_LONG_EMA": 50,
    "BACKTEST_RSI_THRESHOLD": 55,
    "BACKTEST_USE_VOLUME_FILTER": True,
    "BACKTEST_USE_REGIME_FILTER": True,
    "BACKTEST_RISK_PERCENT": 1.0,
    "BACKTEST_ATR_MULTIPLIER": 2.0,
    "BACKTEST_REWARD_RISK_RATIO": 2.0,
    "BACKTEST_MINIMUM_ALPHA_SCORE": 70,
    "BACKTEST_COMMISSION": 0.0,
    "BACKTEST_SLIPPAGE": 0.0,

    # Standalone paper runtime (core/runtime/paper_runtime.py) and the
    # Paper Trading / Order Management / Portfolio / Trade History
    # Streamlit pages, all of which call PaperTradingService. Kept separate
    # from DEFAULT_*/SCANNER_*/BACKTEST_* settings so the unattended
    # runtime has its own safe, conservative configuration. Automatic
    # trade-queue processing defaults to False: nothing executes without
    # an explicit opt-in.
    "PAPER_ACCOUNT_ID": "default",
    "PAPER_STARTING_BALANCE": 100000,
    "PAPER_COMMISSION": 0.0,
    "PAPER_SLIPPAGE": 0.0,
    "PAPER_MAX_OPEN_POSITIONS": 10,
    "PAPER_MAX_POSITION_PERCENT": 25.0,
    "PAPER_PROCESS_QUEUE": False,
    "PAPER_ALLOW_MANUAL_CLOSE": True,
    "PAPER_PRICE_SOURCE": "queue",
    "PAPER_REQUIRE_STOP_LOSS": False,
    "PAPER_REQUIRE_TAKE_PROFIT": False,

    "DATABASE_PATH": "data/trading_platform.db",

    "IBKR_HOST": "127.0.0.1",
    "IBKR_PAPER_PORT": 7497,
    "IBKR_LIVE_PORT": 7496,
    "IBKR_CLIENT_ID": 1,

    "LIVE_TRADING_ENABLED": False
}
