import streamlit as st

from core.execution.execution_router import ExecutionRouter
from core.execution.trade_queue import (
    get_pending_trades,
    get_recent_queue_history,
    update_trade_status
)

st.set_page_config(page_title="Trade Queue", layout="wide")

st.title("Trade Approval Queue")

st.write(
    "Review scanner-generated trade ideas. Approving a trade sends it "
    "through the execution router. Current mode: PAPER."
)

execution_mode = st.selectbox(
    "Execution Mode",
    ["PAPER", "IBKR_PAPER", "IBKR_LIVE"],
    index=0
)

if execution_mode == "IBKR_LIVE":
    st.error(
        "Live trading is disabled for safety. This option is visible only "
        "for future development."
    )

router = ExecutionRouter(
    mode=execution_mode
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

    st.warning(
        "Approving this trade will execute it through the selected "
        "execution mode."
    )

    approve = st.button("Approve and Execute")
    reject = st.button("Reject Trade")

    if approve:
        update_trade_status(
            trade_id=selected_trade_id,
            status="EXECUTING"
        )

        success, message = router.execute_trade(
            symbol=selected_trade["Symbol"],
            side=selected_trade["Side"],
            shares=int(selected_trade["Shares"]),
            price=float(selected_trade["Price"])
        )

        if success:
            update_trade_status(
                trade_id=selected_trade_id,
                status="EXECUTED"
            )

            st.success(message)
        else:
            update_trade_status(
                trade_id=selected_trade_id,
                status="FAILED"
            )

            st.error(message)

        st.rerun()

    if reject:
        update_trade_status(
            trade_id=selected_trade_id,
            status="REJECTED"
        )

        st.warning(f"Trade {selected_trade_id} rejected.")
        st.rerun()

st.divider()

st.subheader("Execution / Queue History")

queue_history = get_recent_queue_history(limit=50)

if queue_history.empty:
    st.info("No queue history yet.")
else:
    st.dataframe(
        queue_history,
        use_container_width=True,
        hide_index=True
    )