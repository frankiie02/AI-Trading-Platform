import pandas as pd
import streamlit as st

from config.settings import settings
from core.execution.trade_queue import get_pending_trades
from core.market_data.yahoo_data import download_price_data
from core.pipeline.models import ScanStrategyMode, TradingDecision
from core.services.paper_trading_service import (
    InsufficientCashError,
    InvalidPaperOrderError,
    OrderStatus,
    PaperTradingService,
    PaperTradingServiceError,
)

st.set_page_config(page_title="Paper Trading", layout="wide")

st.title("Paper Trading")

st.write(
    "Simulate trades using virtual cash before connecting to a real broker. "
    "Orders go through a validated CREATED -> VALIDATED -> SUBMITTED -> FILLED "
    "lifecycle, with deterministic slippage/commission - this page is fully "
    "local/simulated, no broker is involved."
)


def _service() -> PaperTradingService:
    return PaperTradingService(
        starting_balance=settings.STARTING_BALANCE,
        commission=settings.PAPER_COMMISSION,
        slippage_percent=settings.PAPER_SLIPPAGE,
        max_open_positions=settings.PAPER_MAX_OPEN_POSITIONS,
        max_position_percent=settings.PAPER_MAX_POSITION_PERCENT,
        require_stop_loss=settings.PAPER_REQUIRE_STOP_LOSS,
        require_take_profit=settings.PAPER_REQUIRE_TAKE_PROFIT,
    )


service = _service()

try:
    account = service.get_account()
except PaperTradingServiceError as error:
    st.error(f"Could not load the paper account: {error}")
    st.stop()

st.subheader("Account Summary")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Starting Balance", f"${account.starting_balance:,.2f}")
c2.metric("Cash", f"${account.cash:,.2f}")
c3.metric("Equity", f"${account.equity:,.2f}")
c4.metric("Realised P/L", f"${account.realised_pnl:,.2f}")
c5.metric("Unrealised P/L", f"${account.unrealised_pnl:,.2f}")

st.divider()

st.subheader("Place Paper Trade")

hold_for_review = st.checkbox(
    "Hold for review before filling",
    value=False,
    help="When checked, the order stops at VALIDATED and must be filled or "
    "cancelled from Order Management instead of filling immediately."
)

symbol = st.text_input("Symbol", "SPY").upper()

shares = st.number_input("Shares", min_value=1, value=1, step=1)

price_mode = st.selectbox("Price Mode", ["Latest Market Price", "Manual Price"])

manual_price = st.number_input("Manual Price", min_value=0.01, value=100.00, step=0.01)

stop_loss_input = st.number_input("Stop Loss (0 = none)", min_value=0.0, value=0.0, step=0.01)
take_profit_input = st.number_input("Take Profit (0 = none)", min_value=0.0, value=0.0, step=0.01)

latest_price = None

if price_mode == "Latest Market Price":
    data = download_price_data(symbol=symbol, period="5d", interval="1d", auto_adjust=True)

    if data.empty:
        st.warning("Could not fetch latest market price. Use manual price instead.")
    else:
        latest_price = float(data["Close"].iloc[-1])
        st.info(f"Latest price for {symbol}: ${latest_price:,.2f}")

trade_price = latest_price if latest_price else manual_price

place_trade = st.button("Place Paper Trade (BUY)")

if place_trade:
    decision = TradingDecision(
        symbol=symbol,
        final_signal="BUY",
        raw_signal="BUY",
        strategy_name="Manual",
        strategy_mode=ScanStrategyMode.SINGLE,
        current_price=trade_price,
        stop_loss=stop_loss_input if stop_loss_input > 0 else None,
        take_profit=take_profit_input if take_profit_input > 0 else None,
        suggested_shares=int(shares),
    )

    try:
        order = service.create_order_from_decision(
            decision, source_reference="manual", auto_fill=not hold_for_review
        )
    except (InvalidPaperOrderError, InsufficientCashError) as error:
        st.error(str(error))
    except PaperTradingServiceError as error:
        st.error(f"Order could not be processed: {error}")
    else:
        if order.status == OrderStatus.FILLED.value:
            st.success(f"Order #{order.order_id} filled: {order.quantity} {order.symbol} @ ${order.fill_price:,.2f}")
            st.rerun()
        elif order.status == OrderStatus.REJECTED.value:
            st.error(f"Order #{order.order_id} rejected: {order.rejection_reason}")
        else:
            st.info(f"Order #{order.order_id} created with status {order.status}; review it in Order Management.")
            st.rerun()

st.divider()

st.subheader("Queued Eligible Signals")

pending = get_pending_trades()

if pending.empty:
    st.info("No queued signals pending.")
else:
    st.dataframe(pending, use_container_width=True, hide_index=True)

    selected_ids = st.multiselect(
        "Select queue item(s) to process",
        options=pending["ID"].tolist(),
    )

    process_selected = st.button("Process Selected Queue Item(s)")

    if process_selected:
        if not selected_ids:
            st.warning("Select at least one queue item first.")
        else:
            try:
                result = service.process_queue(
                    enabled=True, queue_ids=selected_ids, auto_fill=not hold_for_review
                )
            except PaperTradingServiceError as error:
                st.error(f"Queue processing failed: {error}")
            else:
                st.success(
                    f"Processed {len(result.orders_created)} item(s): "
                    f"{len(result.orders_filled)} filled, {len(result.orders_rejected)} rejected."
                )

                for warning in result.warnings:
                    st.warning(warning)

                for error_message in result.errors:
                    st.error(error_message)

                st.rerun()

st.divider()

st.subheader("Open Positions")

positions = service.get_positions()

if not positions:
    st.info("No open paper positions yet.")
else:
    st.dataframe(
        pd.DataFrame([
            {
                "Symbol": p.symbol,
                "Shares": p.quantity,
                "Entry Price": p.average_entry_price,
                "Current Price": p.current_price,
                "Market Value": p.market_value,
                "Unrealised PnL": p.unrealised_pnl,
                "Realised PnL": p.realised_pnl,
                "Stop Loss": p.stop_loss,
                "Take Profit": p.take_profit,
            }
            for p in positions
        ]),
        use_container_width=True,
        hide_index=True
    )

st.divider()

st.subheader("Recent Orders")

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
                "Source": o.source_reference,
                "Updated At": o.updated_at,
            }
            for o in orders[:25]
        ]),
        use_container_width=True,
        hide_index=True
    )
