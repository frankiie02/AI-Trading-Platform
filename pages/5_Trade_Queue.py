import pandas as pd
import streamlit as st

from config.settings import settings
from core.services.paper_trading_service import PaperTradingService, PaperTradingServiceError

st.set_page_config(page_title="Trade Queue", layout="wide")

st.title("Trade Approval Queue")

st.write(
    "Review scanner-generated trade ideas and process selected ones through "
    "PaperTradingService. This is a local, simulated paper account - no "
    "broker is involved."
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

st.subheader("Pending Trades")

pending = service.get_pending_queue_items()

if pending.empty:
    st.info("No pending trades in the queue.")
else:
    st.dataframe(pending, use_container_width=True, hide_index=True)

    st.divider()

    st.subheader("Process Selected")

    hold_for_review = st.checkbox(
        "Hold for review before filling",
        value=False,
        help="When checked, each processed order stops at VALIDATED and must "
        "be filled or cancelled from Order Management instead of filling "
        "immediately."
    )

    selected_ids = st.multiselect(
        "Select queue item(s) to process",
        options=pending["ID"].tolist(),
    )

    process_selected = st.button("Process Selected")

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

                # No st.rerun() here: warnings/errors from individual queue
                # items must stay visible for the user to read, rather than
                # being wiped by an immediate rerun. The pending/orders
                # tables below already reflect the post-processing state on
                # this same run.

st.divider()

st.subheader("Recent Paper Orders From Queue")

orders = [o for o in service.get_orders() if (o.source_reference or "").startswith("trade_queue:")]

if not orders:
    st.info("No queued signals have been processed yet.")
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
