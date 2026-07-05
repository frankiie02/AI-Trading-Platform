class Settings:
    STARTING_BALANCE = 100000
    RISK_PERCENT = 1
    MAX_OPEN_POSITIONS = 5

    SYMBOLS = [
        "SPY",
        "QQQ",
        "AAPL",
        "MSFT",
        "NVDA",
        "TSLA",
        "AMD",
    ]

    STRATEGY_NAME = "Trend Join Long"

    TRADE_LOG_PATH = "logs/trade_log.csv"
    DASHBOARD_TRADE_LOG_PATH = "logs/dashboard_trade_log.csv"


settings = Settings()