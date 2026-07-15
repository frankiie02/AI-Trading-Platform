import pandas as pd
import streamlit as st

from core.scanner.scanner_repository import (
    get_recent_buy_signals,
    get_recent_scanner_results
)
from core.services.scanner_service import (
    ScanRequest,
    ScannerPersistenceError,
    ScannerService,
    ScanStrategyMode,
    TradeQueuePersistenceError
)
from core.strategy.strategy_engine import AVAILABLE_STRATEGIES

st.set_page_config(page_title="Live Scanner", layout="wide")

st.title("Live Scanner")

scanner_mode_label = st.radio(
    "Scanner Mode",
    ["Single Strategy", "Strategy Voting"],
    horizontal=True
)

if scanner_mode_label == "Strategy Voting":
    scanner_mode = ScanStrategyMode.VOTING
    strategy_name = None
    st.caption(
        "Strategy Voting combines every registered strategy's signal into "
        "one consensus BUY/NO TRADE decision."
    )
else:
    scanner_mode = ScanStrategyMode.SINGLE
    strategy_name = st.selectbox(
        "Strategy",
        AVAILABLE_STRATEGIES
    )

default_symbols = "SPY, QQQ, AAPL, MSFT, NVDA, TSLA, AMD"

symbols_input = st.text_area(
    "Symbols to scan",
    value=default_symbols
)

period = st.selectbox(
    "Data Period",
    ["3mo", "6mo", "1y", "2y"],
    index=2
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

use_volume_filter = st.checkbox(
    "Use Volume Filter",
    value=True
)

use_regime_filter = st.checkbox(
    "Use Market Regime Filter",
    value=True
)

add_to_queue = st.checkbox(
    "Add BUY signals to Trade Queue",
    value=True
)

minimum_alpha_score = st.slider(
    "Minimum Alpha Score to Queue",
    min_value=0,
    max_value=100,
    value=70,
    step=5
)

run_scan = st.button("Run Scan")

if run_scan:
    symbols = [
        symbol.strip().upper()
        for symbol in symbols_input.split(",")
        if symbol.strip()
    ]

    request_kwargs = dict(
        symbols=symbols,
        strategy_mode=scanner_mode,
        period=period,
        interval="1d",
        short_ema=short_ema,
        long_ema=long_ema,
        rsi_threshold=rsi_threshold,
        use_volume_filter=use_volume_filter,
        use_regime_filter=use_regime_filter,
        risk_percent=risk_percent,
        atr_multiplier=atr_multiplier,
        reward_risk_ratio=reward_risk_ratio,
        minimum_alpha_score=minimum_alpha_score,
        queue_trades=add_to_queue
    )

    if strategy_name is not None:
        request_kwargs["strategy_name"] = strategy_name

    request = ScanRequest(**request_kwargs)

    progress_bar = st.progress(0)
    progress_status = st.empty()

    def _progress_callback(completed, total, symbol):
        progress_bar.progress(completed / total)
        progress_status.text(f"Scanning {symbol} ({completed}/{total})")

    service = ScannerService()

    try:
        result = service.scan(request, progress_callback=_progress_callback)
    except ScannerPersistenceError as error:
        st.error(f"Scanner results could not be saved: {error}")
    except TradeQueuePersistenceError as error:
        st.error(
            f"Eligible trades could not be added to the trade queue: {error}"
        )
    else:
        failed_outcomes = [
            outcome for outcome in result.outcomes if outcome.status == "ERROR"
        ]

        if failed_outcomes:
            st.warning(
                f"{len(failed_outcomes)} symbol(s) failed: "
                + ", ".join(
                    f"{outcome.symbol} ({outcome.signal_reason})"
                    for outcome in failed_outcomes
                )
            )

        st.success(
            f"Scan complete. Results saved. "
            f"{result.queued_count} BUY signal(s) added to Trade Queue."
        )

        st.subheader("Ranked Scanner Results")

        st.dataframe(
            result.ranked,
            use_container_width=True,
            hide_index=True
        )

        top_opportunities = result.ranked[
            result.ranked["Signal"] == "BUY"
        ].head(10) if not result.ranked.empty else result.ranked

        st.subheader("Top Tradeable Opportunities")

        if top_opportunities.empty:
            st.info("No tradeable opportunities found.")
        else:
            st.dataframe(
                top_opportunities,
                use_container_width=True,
                hide_index=True
            )

        if scanner_mode == ScanStrategyMode.VOTING:
            voting_rows = [
                {
                    "Symbol": outcome.symbol,
                    "Vote Score": outcome.vote_score,
                    "BUY Votes": outcome.buy_votes,
                    "Total Votes": outcome.total_votes,
                    "Confidence": outcome.confidence,
                    "Reasons": outcome.signal_reason
                }
                for outcome in result.outcomes
                if outcome.status == "OK"
            ]

            st.subheader("Voting Detail")

            if voting_rows:
                st.dataframe(
                    pd.DataFrame(voting_rows),
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("No successful voting outcomes to display.")

st.divider()

st.subheader("Recent Scanner History")

recent_results = get_recent_scanner_results(limit=50)

if recent_results.empty:
    st.info("No scanner history found yet.")
else:
    st.dataframe(
        recent_results,
        use_container_width=True,
        hide_index=True
    )

st.divider()

st.subheader("Recent Buy Signals")

recent_buys = get_recent_buy_signals(limit=25)

if recent_buys.empty:
    st.info("No saved buy signals yet.")
else:
    st.dataframe(
        recent_buys,
        use_container_width=True,
        hide_index=True
    )
