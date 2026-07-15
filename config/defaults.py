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

    "DATABASE_PATH": "data/trading_platform.db",

    "IBKR_HOST": "127.0.0.1",
    "IBKR_PAPER_PORT": 7497,
    "IBKR_LIVE_PORT": 7496,
    "IBKR_CLIENT_ID": 1,

    "LIVE_TRADING_ENABLED": False
}
