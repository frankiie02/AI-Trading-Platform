import pandas as pd
import streamlit as st

from config.settings import settings
from core.market_data.yahoo_data import download_price_data
from core.services.paper_trading_service import PaperTradingService, PaperTradingServiceError

st.set_page_config(page_title="Portfolio", layout="wide")

st.title("Portfolio")

service = PaperTradingService(
    starting_balance=settings.STARTING_BALANCE,
    commission=settings.PAPER_COMMISSION,
    slippage_percent=settings.PAPER_SLIPPAGE,
    max_open_positions=settings.PAPER_MAX_OPEN_POSITIONS,
    max_position_percent=settings.PAPER_MAX_POSITION_PERCENT,
    require_stop_loss=settings.PAPER_REQUIRE_STOP_LOSS,
    require_take_profit=settings.PAPER_REQUIRE_TAKE_PROFIT,
)

refresh_prices = st.button("Refresh Position Prices")

if refresh_prices:
    positions = service.get_positions()

    if not positions:
        st.warning("No open positions to refresh.")
    else:
        price_map = {}

        for position in positions:
            data = download_price_data(
                symbol=position.symbol, period="5d", interval="1d", auto_adjust=True
            )

            if not data.empty:
                price_map[position.symbol] = float(data["Close"].iloc[-1])

        if not price_map:
            st.warning("Could not fetch any updated prices.")
        else:
            try:
                service.update_positions(price_map)
                closed = service.check_exits(price_map)
            except PaperTradingServiceError as error:
                st.error(f"Price refresh failed: {error}")
            else:
                st.success(f"Updated prices for {len(price_map)} position(s).")

                for trade in closed:
                    st.info(
                        f"{trade.symbol} closed via {trade.exit_reason} "
                        f"@ ${trade.exit_price:,.2f} (net P/L ${trade.net_pnl:,.2f})."
                    )

                st.rerun()

try:
    account = service.get_account()
    positions = service.get_positions()
except PaperTradingServiceError as error:
    st.error(f"Could not load the paper account: {error}")
    st.stop()

st.subheader("Account Overview")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Starting Balance", f"${account.starting_balance:,.2f}")
c2.metric("Cash", f"${account.cash:,.2f}")
c3.metric("Equity", f"${account.equity:,.2f}")
c4.metric("Realised P/L", f"${account.realised_pnl:,.2f}")
c5.metric("Unrealised P/L", f"${account.unrealised_pnl:,.2f}")

st.divider()

st.subheader("Open Positions")

positions_df = pd.DataFrame([
    {
        "Symbol": p.symbol,
        "Shares": p.quantity,
        "Entry Price": p.average_entry_price,
        "Current Price": p.current_price,
        "Market Value": p.market_value,
        "Unrealised PnL": p.unrealised_pnl,
        "Realised PnL": p.realised_pnl,
    }
    for p in positions
])

if positions_df.empty:
    st.info("No open positions.")
else:
    st.dataframe(positions_df, use_container_width=True, hide_index=True)

st.divider()

st.subheader("Portfolio Allocation")

if positions_df.empty:
    st.info("No allocation to display.")
else:
    st.bar_chart(
        positions_df[["Symbol", "Market Value"]],
        x="Symbol",
        y="Market Value"
    )

st.divider()

st.subheader("Portfolio Statistics")

if positions_df.empty:
    st.info("Nothing to calculate yet.")
else:
    average_position = positions_df["Market Value"].mean()
    largest_position = positions_df["Market Value"].max()
    total_positions = len(positions_df)

    s1, s2, s3 = st.columns(3)
    s1.metric("Open Positions", total_positions)
    s2.metric("Average Position", f"${average_position:,.2f}")
    s3.metric("Largest Position", f"${largest_position:,.2f}")
