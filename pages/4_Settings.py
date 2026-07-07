import streamlit as st

from config.config_manager import (
    load_settings,
    reset_settings,
    save_settings
)
from core.strategy.strategy_engine import AVAILABLE_STRATEGIES

st.set_page_config(page_title="Settings", layout="wide")

st.title("Settings")

st.write(
    "Manage platform configuration. Changes are saved to "
    "`config/settings.json` and persist after restart."
)

current_settings = load_settings()

st.subheader("General")

starting_balance = st.number_input(
    "Starting Balance",
    min_value=1000,
    value=int(current_settings["STARTING_BALANCE"]),
    step=1000
)

execution_mode = st.selectbox(
    "Execution Mode",
    ["PAPER", "IBKR_PAPER", "IBKR_LIVE"],
    index=["PAPER", "IBKR_PAPER", "IBKR_LIVE"].index(
        current_settings["EXECUTION_MODE"]
    )
)

if execution_mode == "IBKR_LIVE":
    st.error("Live trading is disabled unless LIVE_TRADING_ENABLED is true.")

data_provider = st.selectbox(
    "Data Provider",
    ["YAHOO", "IBKR"],
    index=["YAHOO", "IBKR"].index(
        current_settings["DATA_PROVIDER"]
    )
)

default_period = st.selectbox(
    "Default Data Period",
    ["3mo", "6mo", "1y", "2y", "5y"],
    index=["3mo", "6mo", "1y", "2y", "5y"].index(
        current_settings["DEFAULT_PERIOD"]
    )
)

default_interval = st.selectbox(
    "Default Interval",
    ["1d", "1h", "30m", "15m", "5m"],
    index=["1d", "1h", "30m", "15m", "5m"].index(
        current_settings["DEFAULT_INTERVAL"]
    )
)

st.divider()

st.subheader("Scanner")

default_symbols_text = st.text_area(
    "Default Symbols",
    value=", ".join(current_settings["DEFAULT_SYMBOLS"])
)

minimum_alpha_score = st.slider(
    "Minimum Alpha Score",
    min_value=0,
    max_value=100,
    value=int(current_settings["MINIMUM_ALPHA_SCORE"]),
    step=5
)

use_regime_filter = st.checkbox(
    "Use Market Regime Filter",
    value=bool(current_settings["USE_REGIME_FILTER"])
)

st.divider()

st.subheader("Strategy")

default_strategy = st.selectbox(
    "Default Strategy",
    AVAILABLE_STRATEGIES,
    index=AVAILABLE_STRATEGIES.index(
        current_settings["DEFAULT_STRATEGY"]
    )
    if current_settings["DEFAULT_STRATEGY"] in AVAILABLE_STRATEGIES
    else 0
)

short_ema = st.number_input(
    "Short EMA",
    min_value=1,
    value=int(current_settings["SHORT_EMA"])
)

long_ema = st.number_input(
    "Long EMA",
    min_value=2,
    value=int(current_settings["LONG_EMA"])
)

rsi_threshold = st.number_input(
    "RSI Threshold",
    min_value=1,
    max_value=100,
    value=int(current_settings["RSI_THRESHOLD"])
)

use_volume_filter = st.checkbox(
    "Use Volume Filter",
    value=bool(current_settings["USE_VOLUME_FILTER"])
)

st.divider()

st.subheader("Risk")

risk_per_trade = st.number_input(
    "Risk Per Trade (%)",
    min_value=0.1,
    max_value=10.0,
    value=float(current_settings["RISK_PER_TRADE"]),
    step=0.1
)

atr_stop_multiplier = st.number_input(
    "ATR Stop Multiplier",
    min_value=0.5,
    max_value=10.0,
    value=float(current_settings["ATR_STOP_MULTIPLIER"]),
    step=0.5
)

reward_risk_ratio = st.number_input(
    "Reward/Risk Ratio",
    min_value=0.5,
    max_value=10.0,
    value=float(current_settings["REWARD_RISK_RATIO"]),
    step=0.5
)

st.divider()

st.subheader("Interactive Brokers")

ibkr_host = st.text_input(
    "IBKR Host",
    value=current_settings["IBKR_HOST"]
)

ibkr_paper_port = st.number_input(
    "IBKR Paper Port",
    min_value=1,
    value=int(current_settings["IBKR_PAPER_PORT"])
)

ibkr_live_port = st.number_input(
    "IBKR Live Port",
    min_value=1,
    value=int(current_settings["IBKR_LIVE_PORT"])
)

ibkr_client_id = st.number_input(
    "IBKR Client ID",
    min_value=1,
    value=int(current_settings["IBKR_CLIENT_ID"])
)

live_trading_enabled = st.checkbox(
    "Enable Live Trading",
    value=bool(current_settings["LIVE_TRADING_ENABLED"])
)

st.divider()

save = st.button("Save Settings")
reset = st.button("Reset to Defaults")

if save:
    updated_settings = current_settings.copy()

    updated_settings["STARTING_BALANCE"] = starting_balance
    updated_settings["EXECUTION_MODE"] = execution_mode
    updated_settings["DATA_PROVIDER"] = data_provider
    updated_settings["DEFAULT_PERIOD"] = default_period
    updated_settings["DEFAULT_INTERVAL"] = default_interval

    updated_settings["DEFAULT_SYMBOLS"] = [
        symbol.strip().upper()
        for symbol in default_symbols_text.split(",")
        if symbol.strip()
    ]

    updated_settings["MINIMUM_ALPHA_SCORE"] = minimum_alpha_score
    updated_settings["USE_REGIME_FILTER"] = use_regime_filter

    updated_settings["DEFAULT_STRATEGY"] = default_strategy
    updated_settings["SHORT_EMA"] = short_ema
    updated_settings["LONG_EMA"] = long_ema
    updated_settings["RSI_THRESHOLD"] = rsi_threshold
    updated_settings["USE_VOLUME_FILTER"] = use_volume_filter

    updated_settings["RISK_PER_TRADE"] = risk_per_trade
    updated_settings["ATR_STOP_MULTIPLIER"] = atr_stop_multiplier
    updated_settings["REWARD_RISK_RATIO"] = reward_risk_ratio

    updated_settings["IBKR_HOST"] = ibkr_host
    updated_settings["IBKR_PAPER_PORT"] = ibkr_paper_port
    updated_settings["IBKR_LIVE_PORT"] = ibkr_live_port
    updated_settings["IBKR_CLIENT_ID"] = ibkr_client_id
    updated_settings["LIVE_TRADING_ENABLED"] = live_trading_enabled

    save_settings(updated_settings)

    st.success("Settings saved. Restart the dashboard to fully apply changes.")

if reset:
    reset_settings()
    st.warning("Settings reset to defaults. Restart the dashboard to fully apply changes.")