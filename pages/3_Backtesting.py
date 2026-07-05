import streamlit as st

from analytics.performance import calculate_performance
from config.settings import settings
from core.market_data.yahoo_data import download_price_data
from core.strategy.strategy_engine import (
    AVAILABLE_STRATEGIES,
    generate_strategy_signals
)

st.set_page_config(page_title="Backtesting", layout="wide")

st.title("Backtesting")

strategy_name = st.selectbox(
    "Strategy",
    AVAILABLE_STRATEGIES
)

symbol = st.text_input("Symbol", "SPY")

period = st.selectbox(
    "Backtest Period",
    ["6mo", "1y", "2y", "5y"],
    index=2
)

initial_balance = st.number_input(
    "Initial Balance",
    min_value=1000,
    value=int(settings.STARTING_BALANCE),
    step=1000
)

short_ema = st.number_input("Short EMA", min_value=1, value=20)
long_ema = st.number_input("Long EMA", min_value=2, value=50)
rsi_threshold = st.number_input("RSI Threshold", min_value=1, max_value=100, value=55)

use_volume_filter = st.checkbox(
    "Use Volume Filter",
    value=True
)

run_backtest = st.button("Run Backtest")

if run_backtest:
    data = download_price_data(
        symbol=symbol,
        period=period,
        interval="1d",
        auto_adjust=True
    )

    if data.empty:
        st.error("No data found.")
    else:
        data = generate_strategy_signals(
            df=data,
            strategy_name=strategy_name,
            short_ema=short_ema,
            long_ema=long_ema,
            rsi_threshold=rsi_threshold,
            use_volume_filter=use_volume_filter
        )

        data["Market Return"] = data["Close"].pct_change()
        data["Strategy Return"] = data["Market Return"] * data["Position"]

        data["Market Equity"] = initial_balance * (
            1 + data["Market Return"]
        ).cumprod()

        data["Strategy Equity"] = initial_balance * (
            1 + data["Strategy Return"]
        ).cumprod()

        metrics, trades = calculate_performance(data, initial_balance)

        st.subheader("Performance Summary")

        c1, c2, c3, c4 = st.columns(4)

        c1.metric("Final Value", f"${metrics['Final Value']:,.2f}")
        c2.metric(
            "Profit / Loss",
            f"${metrics['Profit/Loss']:,.2f}",
            f"{metrics['Profit/Loss %']:.2f}%"
        )
        c3.metric("Max Drawdown", f"{metrics['Max Drawdown %']:.2f}%")
        c4.metric("Sharpe Ratio", f"{metrics['Sharpe Ratio']:.2f}")

        c5, c6, c7, c8 = st.columns(4)

        c5.metric("CAGR", f"{metrics['CAGR %']:.2f}%")
        c6.metric("Total Trades", metrics["Total Trades"])
        c7.metric("Win Rate", f"{metrics['Win Rate %']:.2f}%")
        c8.metric("Profit Factor", f"{metrics['Profit Factor']:.2f}")

        st.divider()

        st.subheader("Equity Curve")
        st.line_chart(data[["Market Equity", "Strategy Equity"]])

        st.subheader("Price and Moving Averages")
        st.line_chart(data[["Close", "Short EMA", "Long EMA"]])

        st.subheader("RSI")
        st.line_chart(data[["RSI"]])

        st.subheader("Trade Log")

        if trades.empty:
            st.info("No completed trades found.")
        else:
            st.dataframe(
                trades,
                use_container_width=True,
                hide_index=True
            )

        st.subheader("Backtest Data")
        st.dataframe(
            data.tail(100),
            use_container_width=True
        )