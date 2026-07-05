import pandas as pd
import streamlit as st

from config.settings import settings
from core.execution.trade_queue import save_buy_signals_to_queue
from core.market_data.yahoo_data import download_price_data
from core.risk.risk_engine import (
    calculate_atr_stop_loss,
    calculate_position_size,
    calculate_take_profit
)
from core.scanner.scanner_repository import (
    get_recent_buy_signals,
    get_recent_scanner_results,
    save_scanner_results
)
from core.strategy.strategy_engine import (
    AVAILABLE_STRATEGIES,
    generate_strategy_signals
)

st.set_page_config(page_title="Live Scanner", layout="wide")

st.title("Live Scanner")

strategy_name = st.selectbox(
    "Strategy",
    AVAILABLE_STRATEGIES
)

default_symbols = "SPY, QQQ, AAPL, MSFT, NVDA, TSLA, AMD"

symbols_input = st.text_area(
    "Symbols to scan",
    value=default_symbols
)

period = st.selectbox(
    "Data Period",
    ["3mo", "6mo", "1y", "2y"],
    index=2
)

short_ema = st.number_input("Short EMA", min_value=1, value=20)
long_ema = st.number_input("Long EMA", min_value=2, value=50)

rsi_threshold = st.number_input(
    "RSI Threshold",
    min_value=1,
    max_value=100,
    value=55
)

risk_percent = st.number_input(
    "Risk Per Trade (%)",
    min_value=0.1,
    max_value=10.0,
    value=1.0,
    step=0.1
)

atr_multiplier = st.number_input(
    "ATR Stop Multiplier",
    min_value=0.5,
    max_value=10.0,
    value=2.0,
    step=0.5
)

reward_risk_ratio = st.number_input(
    "Reward/Risk Ratio",
    min_value=0.5,
    max_value=10.0,
    value=2.0,
    step=0.5
)

use_volume_filter = st.checkbox(
    "Use Volume Filter",
    value=True
)

add_to_queue = st.checkbox(
    "Add BUY signals to Trade Queue",
    value=True
)

minimum_confidence = st.slider(
    "Minimum Confidence to Queue",
    min_value=0,
    max_value=100,
    value=70,
    step=5
)

run_scan = st.button("Run Scan")

if run_scan:
    symbols = [
        symbol.strip().upper()
        for symbol in symbols_input.split(",")
        if symbol.strip()
    ]

    results = []
    progress = st.progress(0)

    for index, symbol in enumerate(symbols):
        data = download_price_data(
            symbol=symbol,
            period=period,
            interval="1d",
            auto_adjust=True
        )

        if data.empty:
            results.append({
                "Symbol": symbol,
                "Strategy": strategy_name,
                "Status": "ERROR",
                "Signal": "NO DATA",
                "Confidence": 0,
                "Reason": "No data returned",
                "Price": None,
                "RSI": None,
                "ATR": None,
                "Trend": "FAIL",
                "Momentum": "FAIL",
                "Volume": "FAIL",
                "Suggested Shares": 0,
                "Stop Loss": None,
                "Take Profit": None,
                "Dollar Risk": 0
            })

            progress.progress((index + 1) / len(symbols))
            continue

        data = generate_strategy_signals(
            df=data,
            strategy_name=strategy_name,
            short_ema=short_ema,
            long_ema=long_ema,
            rsi_threshold=rsi_threshold,
            use_volume_filter=use_volume_filter
        )

        clean_data = data.dropna()

        if clean_data.empty:
            results.append({
                "Symbol": symbol,
                "Strategy": strategy_name,
                "Status": "ERROR",
                "Signal": "NOT ENOUGH DATA",
                "Confidence": 0,
                "Reason": "Not enough indicator history",
                "Price": None,
                "RSI": None,
                "ATR": None,
                "Trend": "FAIL",
                "Momentum": "FAIL",
                "Volume": "FAIL",
                "Suggested Shares": 0,
                "Stop Loss": None,
                "Take Profit": None,
                "Dollar Risk": 0
            })

            progress.progress((index + 1) / len(symbols))
            continue

        latest = clean_data.iloc[-1]

        price = float(latest["Close"])
        atr = float(latest["ATR"])

        stop_loss = calculate_atr_stop_loss(
            entry_price=price,
            atr=atr,
            atr_multiplier=atr_multiplier
        )

        take_profit = calculate_take_profit(
            entry_price=price,
            stop_loss_price=stop_loss,
            reward_risk_ratio=reward_risk_ratio
        )

        shares, risk_amount = calculate_position_size(
            account_balance=settings.STARTING_BALANCE,
            entry_price=price,
            stop_loss_price=stop_loss,
            risk_percent=risk_percent
        )

        signal = "BUY" if latest["Signal"] == 1 else "NO TRADE"
        confidence = int(latest.get("Signal Confidence", 0))
        reason = latest.get("Signal Reason", "No reason available")

        if confidence < minimum_confidence:
            signal_for_queue = "NO TRADE"
        else:
            signal_for_queue = signal

        results.append({
            "Symbol": symbol,
            "Strategy": strategy_name,
            "Status": "OK",
            "Signal": signal_for_queue,
            "Confidence": confidence,
            "Reason": reason,
            "Price": round(price, 2),
            "RSI": round(float(latest["RSI"]), 2),
            "ATR": round(atr, 2),
            "Trend": "PASS" if latest["Trend Filter"] else "FAIL",
            "Momentum": "PASS" if latest["Momentum Filter"] else "FAIL",
            "Volume": "PASS" if latest["Volume Filter"] else "FAIL",
            "Suggested Shares": shares,
            "Stop Loss": round(stop_loss, 2),
            "Take Profit": round(take_profit, 2),
            "Dollar Risk": round(risk_amount, 2)
        })

        progress.progress((index + 1) / len(symbols))

    save_scanner_results(results)

    queued_count = 0

    if add_to_queue:
        queued_count = save_buy_signals_to_queue(results)

    results_df = pd.DataFrame(results)

    st.success(
        f"Scan complete. Results saved. "
        f"{queued_count} BUY signal(s) added to Trade Queue."
    )

    st.subheader("Scanner Results")

    st.dataframe(
        results_df.sort_values(
            by="Confidence",
            ascending=False
        ),
        use_container_width=True,
        hide_index=True
    )

    buy_signals = results_df[results_df["Signal"] == "BUY"]

    st.subheader("Buy Signals From This Scan")

    if buy_signals.empty:
        st.info("No buy signals found.")
    else:
        st.dataframe(
            buy_signals.sort_values(
                by="Confidence",
                ascending=False
            ),
            use_container_width=True,
            hide_index=True
        )

st.divider()

st.subheader("Recent Scanner History")

recent_results = get_recent_scanner_results(limit=50)

if recent_results.empty:
    st.info("No scanner history found yet.")
else:
    st.dataframe(
        recent_results,
        use_container_width=True,
        hide_index=True
    )

st.divider()

st.subheader("Recent Buy Signals")

recent_buys = get_recent_buy_signals(limit=25)

if recent_buys.empty:
    st.info("No saved buy signals yet.")
else:
    st.dataframe(
        recent_buys,
        use_container_width=True,
        hide_index=True
    )