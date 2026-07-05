import os
import pandas as pd
import streamlit as st

from config.settings import settings
from engine.scanner import Scanner
from engine.risk_engine import RiskEngine
from engine.execution_engine import ExecutionEngine
from risk.portfolio import Portfolio

st.title("Live Scanner")

starting_balance = st.sidebar.number_input(
    "Starting Balance",
    value=settings.STARTING_BALANCE
)

risk_percent = st.sidebar.number_input(
    "Risk % Per Trade",
    value=float(settings.RISK_PERCENT)
)

max_positions = st.sidebar.number_input(
    "Maximum Open Positions",
    value=settings.MAX_OPEN_POSITIONS
)

symbols = st.sidebar.multiselect(
    "Symbols",
    options=settings.SYMBOLS,
    default=settings.SYMBOLS
)

portfolio = Portfolio(
    starting_balance=starting_balance,
    max_open_positions=max_positions
)

scanner = Scanner(symbols)
risk_engine = RiskEngine(risk_percent=risk_percent)
execution_engine = ExecutionEngine()

if st.button("Run Market Scan"):
    signals = scanner.scan()
    trade_log = []

    if not signals:
        st.warning("No BUY signals found.")
    else:
        for signal in signals:
            trade, reason = risk_engine.approve_signal(signal, portfolio)

            st.subheader(signal.symbol)
            st.write(f"Strategy: {signal.strategy}")
            st.write(f"Confidence: {signal.confidence:.2f}")
            st.write(f"Score: {signal.score}/3")
            st.write(f"Risk Decision: {reason}")

            if trade:
                result = execution_engine.execute_trade(trade, portfolio)

                if result["approved"]:
                    trade_log.append({
                        "Symbol": trade.symbol,
                        "Strategy": signal.strategy,
                        "Confidence": signal.confidence,
                        "Score": signal.score,
                        "Shares": trade.shares,
                        "Entry Price": trade.entry_price,
                        "Stop Loss": trade.stop_loss,
                        "Take Profit": trade.take_profit,
                        "Capital Used": trade.capital,
                        "Cash Remaining": result["cash_remaining"]
                    })

        if trade_log:
            df = pd.DataFrame(trade_log)
            os.makedirs("logs", exist_ok=True)
            df.to_csv(settings.DASHBOARD_TRADE_LOG_PATH, index=False)

            st.subheader("Executed Trades")
            st.dataframe(df, use_container_width=True)

st.subheader("Portfolio Summary")
st.json(portfolio.summary())