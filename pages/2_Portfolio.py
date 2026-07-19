import pandas as pd
import streamlit as st

from config.settings import settings
from core.market_data.yahoo_data import download_price_data
from core.services.paper_trading_service import PaperTradingService, PaperTradingServiceError
from core.services.portfolio_service import PortfolioService, PortfolioServiceError

st.set_page_config(page_title="Portfolio", layout="wide")

st.title("Portfolio")

st.write(
    "Read-only portfolio analytics over the local paper account. Refreshing "
    "prices is the only action on this page that changes state - it goes "
    "through PaperTradingService; everything else below is computed by "
    "PortfolioService."
)


def _pct(value, decimals=2):
    return f"{value:.{decimals}f}%" if value is not None else "N/A"


paper_service = PaperTradingService(
    starting_balance=settings.STARTING_BALANCE,
    commission=settings.PAPER_COMMISSION,
    slippage_percent=settings.PAPER_SLIPPAGE,
    max_open_positions=settings.PAPER_MAX_OPEN_POSITIONS,
    max_position_percent=settings.PAPER_MAX_POSITION_PERCENT,
    require_stop_loss=settings.PAPER_REQUIRE_STOP_LOSS,
    require_take_profit=settings.PAPER_REQUIRE_TAKE_PROFIT,
)

portfolio_service = PortfolioService(
    starting_balance=settings.STARTING_BALANCE,
    paper_trading_service=paper_service,
)

refresh_prices = st.button("Refresh Position Prices")

if refresh_prices:
    positions = portfolio_service.get_positions()

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
                paper_service.update_positions(price_map)
                closed = paper_service.check_exits(price_map)
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

st.divider()

try:
    analysis = portfolio_service.get_analysis()
except PortfolioServiceError as error:
    st.error(f"Could not load portfolio analytics: {error}")
    st.stop()

summary = analysis.summary

st.subheader("Account Overview")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Starting Capital", f"${summary.starting_capital:,.2f}")
c2.metric("Cash", f"${summary.cash:,.2f}")
c3.metric("Equity", f"${summary.equity:,.2f}")
c4.metric("Total Return", _pct(summary.total_return_pct))

c5, c6, c7, c8 = st.columns(4)
c5.metric("Total P/L", f"${summary.total_pnl:,.2f}")
c6.metric("Realised P/L", f"${summary.realised_pnl:,.2f}")
c7.metric("Unrealised P/L", f"${summary.unrealised_pnl:,.2f}")
c8.metric("Gross Exposure", _pct(summary.gross_exposure_pct))

c9, c10 = st.columns(2)
c9.metric("Cash %", _pct(summary.cash_pct))
c10.metric("Open Positions", summary.position_count)

st.divider()

st.subheader("Open Positions")

if not analysis.positions:
    st.info("No open positions.")
else:
    st.dataframe(
        pd.DataFrame([
            {
                "Symbol": p.symbol,
                "Shares": p.quantity,
                "Entry Price": p.average_entry_price,
                "Current Price": p.current_price,
                "Cost Basis": p.cost_basis,
                "Market Value": p.market_value,
                "Unrealised PnL": p.unrealised_pnl,
                "Unrealised Return %": p.unrealised_return_pct,
                "Weight %": p.portfolio_weight_pct,
            }
            for p in analysis.positions
        ]),
        use_container_width=True,
        hide_index=True
    )

st.divider()

st.subheader("Portfolio Allocation")

if not analysis.allocation:
    st.info("No allocation to display.")
else:
    allocation_df = pd.DataFrame(analysis.allocation).rename(columns={
        "symbol": "Symbol", "market_value": "Market Value", "weight_pct": "Weight %"
    })
    st.bar_chart(allocation_df, x="Symbol", y="Market Value")

st.divider()

st.subheader("Portfolio Statistics")

if not analysis.positions:
    st.info("Nothing to calculate yet.")
else:
    s1, s2, s3 = st.columns(3)
    s1.metric("Open Positions", summary.position_count)
    s2.metric(
        "Average Position",
        f"${summary.average_position_value:,.2f}" if summary.average_position_value is not None else "N/A"
    )
    s3.metric("Largest Position", _pct(summary.largest_position_pct))

st.divider()

st.subheader("Performance")

performance = analysis.performance

if performance.equity_curve:
    equity_df = pd.DataFrame(performance.equity_curve)
    st.line_chart(equity_df, x="timestamp", y="equity")

    p1, p2, p3 = st.columns(3)
    p1.metric("Current Drawdown", _pct(performance.current_drawdown_pct))
    p2.metric("Max Drawdown", _pct(performance.max_drawdown_pct))
    p3.metric(
        "Sharpe (per snapshot period)",
        f"{performance.sharpe_ratio:.2f}" if performance.sharpe_ratio is not None else "N/A"
    )
else:
    st.info("No portfolio snapshots yet. Create one below to start tracking equity history.")

st.divider()

st.subheader("Completed Trades")

t1, t2, t3, t4 = st.columns(4)
t1.metric("Completed Trades", performance.total_completed_trades)
t2.metric("Win Rate", _pct(performance.win_rate_pct))
t3.metric("Profit Factor", f"{performance.profit_factor:.2f}")
t4.metric("Expectancy", f"${performance.expectancy:,.2f}")

st.divider()

for warning in analysis.warnings:
    st.warning(warning)

if analysis.reconciliation is not None:
    if analysis.reconciliation.balanced:
        st.success("Portfolio reconciliation balanced.")
    else:
        st.error(f"Reconciliation mismatch detected: {analysis.reconciliation.differences}")

st.divider()

create_snapshot_clicked = st.button("Create Portfolio Snapshot")

if create_snapshot_clicked:
    try:
        snapshot = portfolio_service.create_snapshot()
    except PortfolioServiceError as error:
        st.error(f"Could not create snapshot: {error}")
    else:
        st.success(
            f"Snapshot #{snapshot.snapshot_id} created at {snapshot.timestamp} "
            f"(equity ${snapshot.equity:,.2f})."
        )
        st.rerun()
