import pandas as pd
import streamlit as st

from config.settings import settings
from core.analytics.performance import calculate_performance
from core.market_data.yahoo_data import download_price_data
from core.risk.risk_engine import (
    calculate_atr_stop_loss,
    calculate_position_size,
    calculate_take_profit
)
from core.strategy.trend_momentum_strategy import generate_signals

st.set_page_config(page_title="Backtesting", layout="wide")

st.title("Professional Backtesting Engine")

st.write(
    "Backtest a multi-factor strategy using EMA trend, RSI momentum, "
    "volume confirmation, ATR stop-loss, and risk-based position sizing."
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

short_ema = st.number_input(
    "Short EMA",
    min_value=1,
    value=20
)

long_ema = st.number_input(
    "Long EMA",
    min_value=2,
    value=50
)

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

run_backtest = st.button("Run Backtest")

if run_backtest:
    data = download_price_data(
        symbol=symbol,
        period=period,
        interval="1d",
        auto_adjust=True
    )

    if data.empty:
        st.error("No data found for this symbol.")
    else:
        data = generate_signals(
            data,
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

        clean_data = data.dropna()

        if clean_data.empty:
            st.error("Not enough data to calculate indicators.")
        else:
            latest_row = clean_data.iloc[-1]

            entry_price = latest_row["Close"]
            atr = latest_row["ATR"]

            stop_loss = calculate_atr_stop_loss(
                entry_price=entry_price,
                atr=atr,
                atr_multiplier=atr_multiplier
            )

            take_profit = calculate_take_profit(
                entry_price=entry_price,
                stop_loss_price=stop_loss,
                reward_risk_ratio=reward_risk_ratio
            )

            shares, risk_amount = calculate_position_size(
                account_balance=initial_balance,
                entry_price=entry_price,
                stop_loss_price=stop_loss,
                risk_percent=risk_percent
            )

            metrics, trades = calculate_performance(
                data,
                initial_balance
            )

            st.subheader("Performance Summary")

            c1, c2, c3, c4 = st.columns(4)

            c1.metric(
                "Final Value",
                f"${metrics['Final Value']:,.2f}"
            )

            c2.metric(
                "Profit / Loss",
                f"${metrics['Profit/Loss']:,.2f}",
                f"{metrics['Profit/Loss %']:.2f}%"
            )

            c3.metric(
                "Max Drawdown",
                f"{metrics['Max Drawdown %']:.2f}%"
            )

            c4.metric(
                "Sharpe Ratio",
                f"{metrics['Sharpe Ratio']:.2f}"
            )

            c5, c6, c7, c8 = st.columns(4)

            c5.metric(
                "CAGR",
                f"{metrics['CAGR %']:.2f}%"
            )

            c6.metric(
                "Total Trades",
                metrics["Total Trades"]
            )

            c7.metric(
                "Win Rate",
                f"{metrics['Win Rate %']:.2f}%"
            )

            c8.metric(
                "Profit Factor",
                f"{metrics['Profit Factor']:.2f}"
            )

            st.divider()

            st.subheader("Risk Engine")

            r1, r2, r3, r4 = st.columns(4)

            r1.metric(
                "Suggested Shares",
                shares
            )

            r2.metric(
                "Dollar Risk",
                f"${risk_amount:,.2f}"
            )

            r3.metric(
                "Stop Loss",
                f"${stop_loss:,.2f}"
            )

            r4.metric(
                "Take Profit",
                f"${take_profit:,.2f}"
            )

            st.divider()

            st.subheader("Signal Status")

            s1, s2, s3, s4 = st.columns(4)

            s1.metric(
                "Trend Filter",
                "PASS" if latest_row["Trend Filter"] else "FAIL"
            )

            s2.metric(
                "Momentum Filter",
                "PASS" if latest_row["Momentum Filter"] else "FAIL"
            )

            s3.metric(
                "Volume Filter",
                "PASS" if latest_row["Volume Filter"] else "FAIL"
            )

            s4.metric(
                "Current Signal",
                "BUY" if latest_row["Signal"] == 1 else "NO TRADE"
            )

            st.divider()

            st.subheader("Equity Curve")

            st.line_chart(
                data[["Market Equity", "Strategy Equity"]]
            )

            st.subheader("Price, EMA and Trend")

            st.line_chart(
                data[["Close", "Short EMA", "Long EMA"]]
            )

            st.subheader("RSI")

            st.line_chart(
                data[["RSI"]]
            )

            st.divider()

            st.subheader("Trade Log")

            if not trades.empty:
                st.dataframe(
                    trades,
                    use_container_width=True,
                    hide_index=True
                )

                csv = trades.to_csv(index=False)

                st.download_button(
                    label="Download Trade Log CSV",
                    data=csv,
                    file_name=f"{symbol}_backtest_trades.csv",
                    mime="text/csv"
                )
            else:
                st.info("No completed trades found for this backtest.")

            st.divider()

            st.subheader("Backtest Data")

            st.dataframe(
                data.tail(100),
                use_container_width=True
            )