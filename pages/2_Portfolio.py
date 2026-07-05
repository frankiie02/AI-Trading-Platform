import streamlit as st

from config.settings import settings
from core.execution.paper_trader import PaperTrader

st.set_page_config(
    page_title="Portfolio",
    layout="wide"
)

st.title("Portfolio")

trader = PaperTrader(
    starting_balance=settings.STARTING_BALANCE
)

summary = trader.get_account_summary()
positions = trader.get_positions()

st.subheader("Account Overview")

c1, c2, c3, c4, c5 = st.columns(5)

c1.metric(
    "Starting Balance",
    f"${summary['Starting Balance']:,.2f}"
)

c2.metric(
    "Cash",
    f"${summary['Cash']:,.2f}"
)

c3.metric(
    "Portfolio Value",
    f"${summary['Portfolio Value']:,.2f}"
)

c4.metric(
    "Market Value",
    f"${summary['Market Value']:,.2f}"
)

c5.metric(
    "Unrealised P/L",
    f"${summary['Unrealised PnL']:,.2f}"
)

st.divider()

st.subheader("Open Positions")

if positions.empty:

    st.info("No open positions.")

else:

    st.dataframe(
        positions,
        use_container_width=True,
        hide_index=True
    )

st.divider()

st.subheader("Portfolio Allocation")

if not positions.empty:

    allocation = positions[
        ["Symbol", "Market Value"]
    ].copy()

    st.bar_chart(
        allocation,
        x="Symbol",
        y="Market Value"
    )

st.divider()

st.subheader("Portfolio Statistics")

if positions.empty:

    st.info("Nothing to calculate yet.")

else:

    average_position = (
        positions["Market Value"].mean()
    )

    largest_position = (
        positions["Market Value"].max()
    )

    total_positions = len(positions)

    s1, s2, s3 = st.columns(3)

    s1.metric(
        "Open Positions",
        total_positions
    )

    s2.metric(
        "Average Position",
        f"${average_position:,.2f}"
    )

    s3.metric(
        "Largest Position",
        f"${largest_position:,.2f}"
    )