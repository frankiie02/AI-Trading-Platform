import pandas as pd
import streamlit as st

from config.settings import settings
from core.market_data.yahoo_data import download_price_data
from core.services.paper_trading_service import (
    ExitReason,
    InvalidOrderStateTransitionError,
    InvalidPaperOrderError,
    OrderStatus,
    PaperTradingService,
    PaperTradingServiceError,
    PositionNotFoundError,
)

st.set_page_config(page_title="Order Management", layout="wide")

st.title("Order Management")

st.write(
    "Manage paper orders and open positions: cancel orders still in a "
    "cancellable state, close full or partial positions, and update "
    "stop-loss/take-profit levels. All actions go through PaperTradingService "
    "- no direct database access happens on this page."
)

service = PaperTradingService(
    starting_balance=settings.STARTING_BALANCE,
    commission=settings.PAPER_COMMISSION,
    slippage_percent=settings.PAPER_SLIPPAGE,
    max_open_positions=settings.PAPER_MAX_OPEN_POSITIONS,
    max_position_percent=settings.PAPER_MAX_POSITION_PERCENT,
    require_stop_loss=settings.PAPER_REQUIRE_STOP_LOSS,
    require_take_profit=settings.PAPER_REQUIRE_TAKE_PROFIT,
)

_CANCELLABLE = {OrderStatus.CREATED.value, OrderStatus.VALIDATED.value, OrderStatus.SUBMITTED.value}

st.subheader("Orders")

orders = service.get_orders()

if not orders:
    st.info("No orders yet.")
else:
    st.dataframe(
        pd.DataFrame([
            {
                "Order ID": o.order_id,
                "Symbol": o.symbol,
                "Side": o.side,
                "Quantity": o.quantity,
                "Status": o.status,
                "Requested Price": o.requested_price,
                "Fill Price": o.fill_price,
                "Rejection Reason": o.rejection_reason,
                "Fees": o.fees,
                "Updated At": o.updated_at,
            }
            for o in orders
        ]),
        use_container_width=True,
        hide_index=True
    )

    reviewable_orders = [o for o in orders if o.status in _CANCELLABLE]

    if reviewable_orders:
        st.divider()
        st.subheader("Review Held Orders")

        order_lookup = {
            f"#{o.order_id} {o.symbol} ({o.status})": o.order_id for o in reviewable_orders
        }

        selected_label = st.selectbox("Order", list(order_lookup.keys()))
        selected_order_id = order_lookup[selected_label]

        col_a, col_b = st.columns(2)

        with col_a:
            fill_now = st.button("Fill Now")

        with col_b:
            cancel_now = st.button("Cancel Order")

        if fill_now:
            try:
                order = next(o for o in reviewable_orders if o.order_id == selected_order_id)

                if order.status == OrderStatus.VALIDATED.value:
                    service.submit_order(selected_order_id)

                service.fill_order(selected_order_id)
            except (InvalidOrderStateTransitionError, InvalidPaperOrderError) as error:
                st.error(str(error))
            except PaperTradingServiceError as error:
                st.error(f"Order could not be filled: {error}")
            else:
                st.success(f"Order #{selected_order_id} filled.")
                st.rerun()

        if cancel_now:
            try:
                service.cancel_order(selected_order_id)
            except InvalidOrderStateTransitionError as error:
                st.error(str(error))
            except PaperTradingServiceError as error:
                st.error(f"Order could not be cancelled: {error}")
            else:
                st.success(f"Order #{selected_order_id} cancelled.")
                st.rerun()
    else:
        st.info("No orders are currently held for review.")

st.divider()

st.subheader("Open Positions")

positions = service.get_positions()

if not positions:
    st.info("No open positions to manage.")
else:
    st.dataframe(
        pd.DataFrame([
            {
                "Symbol": p.symbol,
                "Shares": p.quantity,
                "Entry Price": p.average_entry_price,
                "Current Price": p.current_price,
                "Stop Loss": p.stop_loss,
                "Take Profit": p.take_profit,
                "Unrealised PnL": p.unrealised_pnl,
                "Realised PnL": p.realised_pnl,
            }
            for p in positions
        ]),
        use_container_width=True,
        hide_index=True
    )

    st.divider()

    st.subheader("Select Position")

    symbols = [p.symbol for p in positions]
    selected_symbol = st.selectbox("Position", symbols)
    selected_position = next(p for p in positions if p.symbol == selected_symbol)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Symbol", selected_position.symbol)
    c2.metric("Shares Held", selected_position.quantity)
    c3.metric("Entry Price", f"${selected_position.average_entry_price:,.2f}")
    c4.metric("Current Price", f"${selected_position.current_price:,.2f}")

    st.divider()

    st.subheader("Close Position")

    close_shares = st.number_input(
        "Shares to close",
        min_value=1,
        max_value=int(selected_position.quantity),
        value=int(selected_position.quantity),
        step=1
    )

    price_mode = st.selectbox(
        "Close Price Mode",
        ["Current Stored Price", "Latest Market Price", "Manual Price"]
    )

    manual_close_price = st.number_input(
        "Manual Close Price",
        min_value=0.01,
        value=float(selected_position.current_price),
        step=0.01
    )

    close_price = selected_position.current_price

    if price_mode == "Latest Market Price":
        data = download_price_data(symbol=selected_symbol, period="5d", interval="1d", auto_adjust=True)

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

    if close_partial or close_full:
        quantity = int(selected_position.quantity) if close_full else int(close_shares)

        try:
            trade = service.close_position(
                selected_symbol, quantity=quantity, price=close_price, reason=ExitReason.MANUAL
            )
        except (PositionNotFoundError, InvalidPaperOrderError) as error:
            st.error(str(error))
        except PaperTradingServiceError as error:
            st.error(f"Position could not be closed: {error}")
        else:
            st.success(
                f"Closed {trade.quantity} {trade.symbol} @ ${trade.exit_price:,.2f} "
                f"(net P/L ${trade.net_pnl:,.2f})."
            )
            st.rerun()

    st.divider()

    st.subheader("Update Stop Loss / Take Profit")

    stop_loss_value = float(selected_position.stop_loss) if selected_position.stop_loss else 0.0
    take_profit_value = float(selected_position.take_profit) if selected_position.take_profit else 0.0

    new_stop_loss = st.number_input("Stop Loss", min_value=0.0, value=stop_loss_value, step=0.01)
    new_take_profit = st.number_input("Take Profit", min_value=0.0, value=take_profit_value, step=0.01)

    update_levels = st.button("Save Order Levels")

    if update_levels:
        try:
            service.update_position_levels(
                selected_symbol,
                stop_loss=new_stop_loss if new_stop_loss > 0 else None,
                take_profit=new_take_profit if new_take_profit > 0 else None,
            )
        except PositionNotFoundError as error:
            st.error(str(error))
        except PaperTradingServiceError as error:
            st.error(f"Levels could not be updated: {error}")
        else:
            st.success(f"Updated order levels for {selected_symbol}.")
            st.rerun()
