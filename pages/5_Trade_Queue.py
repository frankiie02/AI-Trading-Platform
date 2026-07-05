import streamlit as st

from core.execution.trade_queue import (
    get_pending_trades,
    update_trade_status
)

st.set_page_config(page_title="Trade Queue", layout="wide")

st.title("Trade Approval Queue")

st.write(
    "Review scanner-generated trade ideas before approving them for execution."
)

pending_trades = get_pending_trades()

st.subheader("Pending Trades")

if pending_trades.empty:
    st.info("No pending trades in the queue.")
else:
    st.dataframe(
        pending_trades,
        use_container_width=True,
        hide_index=True
    )

    st.divider()

    st.subheader("Review Trade")

    trade_ids = pending_trades["ID"].tolist()

    selected_trade_id = st.selectbox(
        "Select Trade ID",
        trade_ids
    )

    selected_trade = pending_trades[
        pending_trades["ID"] == selected_trade_id
    ].iloc[0]

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Symbol", selected_trade["Symbol"])
    c2.metric("Side", selected_trade["Side"])
    c3.metric("Shares", int(selected_trade["Shares"]))
    c4.metric("Price", f"${selected_trade['Price']:,.2f}")

    c5, c6, c7 = st.columns(3)

    c5.metric("Stop Loss", f"${selected_trade['Stop Loss']:,.2f}")
    c6.metric("Take Profit", f"${selected_trade['Take Profit']:,.2f}")
    c7.metric("Dollar Risk", f"${selected_trade['Dollar Risk']:,.2f}")

    approve = st.button("Approve Trade")
    reject = st.button("Reject Trade")

    if approve:
        update_trade_status(
            trade_id=selected_trade_id,
            status="APPROVED"
        )

        st.success(f"Trade {selected_trade_id} approved.")
        st.rerun()

    if reject:
        update_trade_status(
            trade_id=selected_trade_id,
            status="REJECTED"
        )

        st.warning(f"Trade {selected_trade_id} rejected.")
        st.rerun()