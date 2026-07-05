import os
import pandas as pd
import streamlit as st

from config.settings import settings

st.set_page_config(page_title="Portfolio", layout="wide")

st.title("📊 Portfolio Dashboard")

starting_balance = settings.STARTING_BALANCE
trade_log = settings.DASHBOARD_TRADE_LOG_PATH

if os.path.exists(trade_log):

    trades = pd.read_csv(trade_log)

    if not trades.empty:

        capital_used = trades["Capital Used"].sum()
        cash = trades["Cash Remaining"].iloc[-1]

        portfolio_value = cash + capital_used

        pnl = portfolio_value - starting_balance

        pnl_pct = (pnl / starting_balance) * 100

        col1,col2,col3,col4,col5 = st.columns(5)

        col1.metric(
            "Starting Balance",
            f"${starting_balance:,.2f}"
        )

        col2.metric(
            "Portfolio Value",
            f"${portfolio_value:,.2f}"
        )

        col3.metric(
            "Cash",
            f"${cash:,.2f}"
        )

        col4.metric(
            "Capital Invested",
            f"${capital_used:,.2f}"
        )

        col5.metric(
            "Profit / Loss",
            f"${pnl:,.2f}",
            f"{pnl_pct:.2f}%"
        )

        st.divider()

        st.subheader("Current Positions")

        st.dataframe(
            trades,
            use_container_width=True,
            hide_index=True
        )

        st.divider()

        st.subheader("Allocation")

        allocation = (
            trades
            .groupby("Symbol")["Capital Used"]
            .sum()
            .sort_values(ascending=False)
        )

        st.bar_chart(allocation)

        st.divider()

        st.subheader("Portfolio Allocation %")

        pie = allocation.reset_index()

        pie["Allocation %"] = (
            pie["Capital Used"] /
            pie["Capital Used"].sum()
        ) * 100

        st.dataframe(
            pie,
            use_container_width=True,
            hide_index=True
        )

else:

    st.info("No trades have been generated yet.")