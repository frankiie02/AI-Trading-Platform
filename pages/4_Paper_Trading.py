import streamlit as st

from config.settings import settings
from core.execution.paper_trader import PaperTrader
from core.market_data.yahoo_data import download_price_data

st.set_page_config(page_title="Paper Trading", layout="wide")

st.title("Paper Trading")

st.write(
    "Simulate trades using virtual cash before connecting to a real broker. "
    "This page now stores paper trades and positions in SQLite."
)

trader = PaperTrader(
    starting_balance=settings.STARTING_BALANCE
)

summary = trader.get_account_summary()

st.subheader("Account Summary")

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
    "Market Value",
    f"${summary['Market Value']:,.2f}"
)

c4.metric(
    "Portfolio Value",
    f"${summary['Portfolio Value']:,.2f}"
)

c5.metric(
    "Unrealised P/L",
    f"${summary['Unrealised PnL']:,.2f}"
)

st.divider()

st.subheader("Place Paper Trade")

symbol = st.text_input("Symbol", "SPY").upper()

trade_type = st.selectbox(
    "Trade Type",
    ["BUY", "SELL"]
)

shares = st.number_input(
    "Shares",
    min_value=1,
    value=1,
    step=1
)

price_mode = st.selectbox(
    "Price Mode",
    ["Latest Market Price", "Manual Price"]
)

manual_price = st.number_input(
    "Manual Price",
    min_value=0.01,
    value=100.00,
    step=0.01
)

latest_price = None

if price_mode == "Latest Market Price":
    data = download_price_data(
        symbol=symbol,
        period="5d",
        interval="1d",
        auto_adjust=True
    )

    if data.empty:
        st.warning(
            "Could not fetch latest market price. Use manual price instead."
        )
    else:
        latest_price = float(data["Close"].iloc[-1])
        st.info(f"Latest price for {symbol}: ${latest_price:,.2f}")

trade_price = latest_price if latest_price else manual_price

place_trade = st.button("Place Paper Trade")

if place_trade:
    if trade_type == "BUY":
        success, message = trader.buy(
            symbol=symbol,
            shares=shares,
            price=trade_price
        )
    else:
        success, message = trader.sell(
            symbol=symbol,
            shares=shares,
            price=trade_price
        )

    if success:
        st.success(message)
    else:
        st.error(message)

    st.rerun()

st.divider()

st.subheader("Open Positions")

positions = trader.get_positions()

if positions.empty:
    st.info("No open paper positions yet.")
else:
    st.dataframe(
        positions,
        use_container_width=True,
        hide_index=True
    )

st.divider()

st.subheader("Paper Trade Log")

trade_log = trader.get_trade_log()

if trade_log.empty:
    st.info("No paper trades logged yet.")
else:
    st.dataframe(
        trade_log,
        use_container_width=True,
        hide_index=True
    )