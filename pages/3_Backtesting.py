import streamlit as st

from config.settings import settings
from core.services.backtest_service import (
    BacktestDataError,
    BacktestRequest,
    BacktestService,
    BacktestServiceError,
    InvalidBacktestRequestError,
)
from core.pipeline.models import ScanStrategyMode
from core.strategy.strategy_engine import AVAILABLE_STRATEGIES

st.set_page_config(page_title="Backtesting", layout="wide")

st.title("Backtesting")

backtest_mode_label = st.radio(
    "Backtest Mode",
    ["Single Strategy", "Strategy Voting"],
    horizontal=True
)

if backtest_mode_label == "Strategy Voting":
    backtest_mode = ScanStrategyMode.VOTING
    strategy_name = "EMA Trend"
    st.caption(
        "Strategy Voting combines every registered strategy's signal into "
        "one consensus BUY/NO TRADE decision, evaluated bar by bar."
    )
else:
    backtest_mode = ScanStrategyMode.SINGLE
    strategy_name = st.selectbox(
        "Strategy",
        AVAILABLE_STRATEGIES
    )

symbol = st.text_input("Symbol", "SPY")

period = st.selectbox(
    "Backtest Period",
    ["6mo", "1y", "2y", "5y"],
    index=2
)

initial_balance = st.number_input(
    "Initial Balance",
    min_value=1000,
    value=int(settings.STARTING_BALANCE),
    step=1000
)

short_ema = st.number_input(
    "Short EMA",
    min_value=1,
    value=20
)

long_ema = st.number_input(
    "Long EMA",
    min_value=2,
    value=50
)

rsi_threshold = st.number_input(
    "RSI Threshold",
    min_value=1,
    max_value=100,
    value=55
)

use_volume_filter = st.checkbox(
    "Use Volume Filter",
    value=True
)

use_regime_filter = st.checkbox(
    "Use Market Regime Filter",
    value=True
)

risk_percent = st.number_input(
    "Risk Per Trade (%)",
    min_value=0.1,
    max_value=10.0,
    value=1.0,
    step=0.1
)

atr_multiplier = st.number_input(
    "ATR Stop Multiplier",
    min_value=0.5,
    max_value=10.0,
    value=2.0,
    step=0.5
)

reward_risk_ratio = st.number_input(
    "Reward/Risk Ratio",
    min_value=0.5,
    max_value=10.0,
    value=2.0,
    step=0.5
)

minimum_alpha_score = st.slider(
    "Minimum Alpha Score to Trade",
    min_value=0,
    max_value=100,
    value=70,
    step=5
)

commission = st.number_input(
    "Commission per Trade ($)",
    min_value=0.0,
    value=0.0,
    step=0.5
)

slippage = st.number_input(
    "Slippage (%)",
    min_value=0.0,
    max_value=5.0,
    value=0.0,
    step=0.1
)

run_backtest_clicked = st.button("Run Backtest")

if run_backtest_clicked:
    request = BacktestRequest(
        symbol=symbol,
        strategy_mode=backtest_mode,
        strategy_name=strategy_name,
        period=period,
        interval="1d",
        initial_capital=initial_balance,
        short_ema=short_ema,
        long_ema=long_ema,
        rsi_threshold=rsi_threshold,
        use_volume_filter=use_volume_filter,
        use_regime_filter=use_regime_filter,
        risk_percent=risk_percent,
        atr_multiplier=atr_multiplier,
        reward_risk_ratio=reward_risk_ratio,
        minimum_alpha_score=minimum_alpha_score,
        commission=commission,
        slippage=slippage,
    )

    service = BacktestService()

    try:
        result = service.run(request)
    except InvalidBacktestRequestError as error:
        st.error(f"Invalid backtest configuration: {error}")
    except BacktestDataError as error:
        st.error(f"Market data error: {error}")
    except BacktestServiceError as error:
        st.error(f"Backtest could not be completed: {error}")
    else:
        metrics = result.metrics
        benchmark = result.benchmark_metrics

        for warning in result.warnings:
            st.warning(warning)

        st.subheader("Performance Summary")

        c1, c2, c3, c4 = st.columns(4)

        c1.metric("Final Equity", f"${metrics['Final Equity']:,.2f}")
        c2.metric("Total Return", f"{metrics['Total Return %']:.2f}%")
        c3.metric("Max Drawdown", f"{metrics['Max Drawdown %']:.2f}%")
        c4.metric("Sharpe Ratio", f"{metrics['Sharpe Ratio']:.2f}")

        c5, c6, c7, c8 = st.columns(4)

        c5.metric("Annualised Return", f"{metrics['Annualised Return %']:.2f}%")
        c6.metric("Total Trades", metrics["Total Trades"])
        c7.metric("Win Rate", f"{metrics['Win Rate %']:.2f}%")
        c8.metric("Profit Factor", f"{metrics['Profit Factor']:.2f}")

        c9, c10, c11, c12 = st.columns(4)

        c9.metric("Sortino Ratio", f"{metrics['Sortino Ratio']:.2f}")
        c10.metric("Volatility", f"{metrics['Volatility %']:.2f}%")
        c11.metric("Exposure", f"{metrics['Exposure %']:.2f}%")
        c12.metric("Total Fees", f"${metrics['Total Fees']:,.2f}")

        if benchmark:
            st.caption(
                f"Buy & hold benchmark: {benchmark['Total Return %']:.2f}% "
                f"total return, {benchmark['Max Drawdown %']:.2f}% max drawdown."
            )

        st.divider()

        st.subheader("Equity Curve")

        if result.equity_curve.empty:
            st.info("No equity curve available.")
        else:
            st.line_chart(
                result.equity_curve.set_index("Date")[["Equity"]]
            )

        st.subheader("Trade Log")

        if not result.trades:
            st.info("No completed trades found.")
        else:
            trade_rows = [
                {
                    "Entry Date": trade.entry_timestamp,
                    "Exit Date": trade.exit_timestamp,
                    "Entry Price": trade.entry_price,
                    "Exit Price": trade.exit_price,
                    "Quantity": trade.quantity,
                    "Stop Loss": trade.stop_loss,
                    "Take Profit": trade.take_profit,
                    "Gross P&L": trade.gross_pnl,
                    "Fees": trade.fees,
                    "Net P&L": trade.net_pnl,
                    "Exit Reason": trade.exit_reason,
                    "Strategy": trade.strategy_name,
                }
                for trade in result.trades
            ]

            st.dataframe(
                trade_rows,
                use_container_width=True,
                hide_index=True
            )
