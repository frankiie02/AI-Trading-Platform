import pandas as pd
import streamlit as st

from config.settings import settings
from core.services.paper_trading_service import PaperTradingService, PaperTradingServiceError

st.set_page_config(page_title="Trade History", layout="wide")

st.title("Trade History")

st.write(
    "Completed paper trades (round-trip entries and exits), read-only. "
    "Use Order Management to close open positions."
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
    trades = service.get_trades()
except PaperTradingServiceError as error:
    st.error(f"Could not load trade history: {error}")
    st.stop()

if not trades:
    st.info("No completed trades yet.")
else:
    trades_df = pd.DataFrame([
        {
            "Trade ID": t.trade_id,
            "Symbol": t.symbol,
            "Quantity": t.quantity,
            "Entry Price": t.entry_price,
            "Exit Price": t.exit_price,
            "Exit Timestamp": t.exit_timestamp,
            "Gross PnL": t.gross_pnl,
            "Fees": t.fees,
            "Net PnL": t.net_pnl,
            "Exit Reason": t.exit_reason,
            "Strategy": t.strategy_name,
        }
        for t in trades
    ])

    st.subheader("Summary")

    total_trades = len(trades_df)
    winners = trades_df[trades_df["Net PnL"] > 0]
    win_rate = (len(winners) / total_trades * 100) if total_trades else 0.0
    total_net_pnl = trades_df["Net PnL"].sum()

    s1, s2, s3 = st.columns(3)
    s1.metric("Total Trades", total_trades)
    s2.metric("Win Rate", f"{win_rate:.1f}%")
    s3.metric("Total Net PnL", f"${total_net_pnl:,.2f}")

    st.divider()

    st.subheader("Completed Trades")

    st.dataframe(trades_df, use_container_width=True, hide_index=True)
