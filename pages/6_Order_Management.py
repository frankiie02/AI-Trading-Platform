import streamlit as st

from config.settings import settings
from core.execution.paper_trader import PaperTrader
from core.market_data.yahoo_data import download_price_data
from core.portfolio.position_monitor import refresh_paper_position_prices

st.set_page_config(page_title="Order Management", layout="wide")

st.title("Order Management")

st.write(
    "Manage open paper positions: close full or partial positions, "
    "move stop-loss, update take-profit, set break-even, and set trailing stop."
)

trader = PaperTrader(
    starting_balance=settings.STARTING_BALANCE
)

refresh = st.button("Refresh Position Prices")

if refresh:
    success, message = refresh_paper_position_prices(
        starting_balance=settings.STARTING_BALANCE
    )

    if success:
        st.success(message)
    else:
        st.warning(message)

    st.rerun()

positions = trader.get_positions()

st.subheader("Open Positions")

if positions.empty:
    st.info("No open positions to manage.")
else:
    st.dataframe(
        positions,
        use_container_width=True,
        hide_index=True
    )

    st.divider()

    st.subheader("Select Position")

    symbols = positions["Symbol"].tolist()

    selected_symbol = st.selectbox(
        "Position",
        symbols
    )

    selected_position = positions[
        positions["Symbol"] == selected_symbol
    ].iloc[0]

    shares_held = int(selected_position["Shares"])
    entry_price = float(selected_position["Entry Price"])
    current_price = float(selected_position["Current Price"])

    current_stop_loss = selected_position["Stop Loss"]
    current_take_profit = selected_position["Take Profit"]
    current_trailing_stop = selected_position["Trailing Stop"]

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Symbol", selected_symbol)
    c2.metric("Shares Held", shares_held)
    c3.metric("Entry Price", f"${entry_price:,.2f}")
    c4.metric("Current Price", f"${current_price:,.2f}")

    st.divider()

    st.subheader("Close Position")

    close_shares = st.number_input(
        "Shares to close",
        min_value=1,
        max_value=shares_held,
        value=shares_held,
        step=1
    )

    price_mode = st.selectbox(
        "Close Price Mode",
        ["Current Stored Price", "Latest Market Price", "Manual Price"]
    )

    manual_close_price = st.number_input(
        "Manual Close Price",
        min_value=0.01,
        value=float(current_price),
        step=0.01
    )

    close_price = current_price

    if price_mode == "Latest Market Price":
        data = download_price_data(
            symbol=selected_symbol,
            period="5d",
            interval="1d",
            auto_adjust=True
        )

        if data.empty:
            st.warning("Could not fetch latest market price. Using stored price.")
        else:
            close_price = float(data["Close"].iloc[-1])
            st.info(f"Latest price for {selected_symbol}: ${close_price:,.2f}")

    elif price_mode == "Manual Price":
        close_price = manual_close_price

    col_a, col_b = st.columns(2)

    with col_a:
        close_partial = st.button("Close Selected Shares")

    with col_b:
        close_full = st.button("Close Full Position")

    if close_partial:
        success, message = trader.sell(
            symbol=selected_symbol,
            shares=close_shares,
            price=close_price
        )

        if success:
            st.success(message)
        else:
            st.error(message)

        st.rerun()

    if close_full:
        success, message = trader.sell(
            symbol=selected_symbol,
            shares=shares_held,
            price=close_price
        )

        if success:
            st.success(message)
        else:
            st.error(message)

        st.rerun()

    st.divider()

    st.subheader("Update Order Levels")

    stop_loss_value = (
        float(current_stop_loss)
        if current_stop_loss is not None and str(current_stop_loss) != "nan"
        else 0.0
    )

    take_profit_value = (
        float(current_take_profit)
        if current_take_profit is not None and str(current_take_profit) != "nan"
        else 0.0
    )

    trailing_stop_value = (
        float(current_trailing_stop)
        if current_trailing_stop is not None and str(current_trailing_stop) != "nan"
        else 0.0
    )

    new_stop_loss = st.number_input(
        "Stop Loss",
        min_value=0.0,
        value=stop_loss_value,
        step=0.01
    )

    new_take_profit = st.number_input(
        "Take Profit",
        min_value=0.0,
        value=take_profit_value,
        step=0.01
    )

    new_trailing_stop = st.number_input(
        "Trailing Stop",
        min_value=0.0,
        value=trailing_stop_value,
        step=0.01
    )

    update_levels = st.button("Save Order Levels")
    break_even = st.button("Move Stop Loss to Break-Even")

    if update_levels:
        stop_loss_to_save = new_stop_loss if new_stop_loss > 0 else None
        take_profit_to_save = new_take_profit if new_take_profit > 0 else None
        trailing_stop_to_save = new_trailing_stop if new_trailing_stop > 0 else None

        success, message = trader.update_position_levels(
            symbol=selected_symbol,
            stop_loss=stop_loss_to_save,
            take_profit=take_profit_to_save,
            trailing_stop=trailing_stop_to_save
        )

        if success:
            st.success(message)
        else:
            st.error(message)

        st.rerun()

    if break_even:
        success, message = trader.set_break_even(
            symbol=selected_symbol
        )

        if success:
            st.success(message)
        else:
            st.error(message)

        st.rerun()