from datetime import datetime

import pandas as pd

from core.database.database import (
    DB_PATH,
    get_connection,
    initialise_database
)


def save_scanner_results(results, db_path=DB_PATH):
    initialise_database(db_path)

    if not results:
        return

    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_connection(db_path)
    cursor = conn.cursor()

    for row in results:
        cursor.execute("""
            INSERT INTO scanner_results (
                scan_time,
                symbol,
                strategy,
                status,
                signal,
                confidence,
                alpha_score,
                alpha_grade,
                reason,
                alpha_reasons,
                market_regime,
                strategy_allowed,
                regime_reason,
                price,
                rsi,
                atr,
                trend,
                momentum,
                volume,
                suggested_shares,
                stop_loss,
                take_profit,
                dollar_risk
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            scan_time,
            row.get("Symbol"),
            row.get("Strategy"),
            row.get("Status"),
            row.get("Signal"),
            row.get("Confidence"),
            row.get("Alpha Score"),
            row.get("Alpha Grade"),
            row.get("Reason"),
            row.get("Alpha Reasons"),
            row.get("Market Regime"),
            row.get("Strategy Allowed"),
            row.get("Regime Reason"),
            row.get("Price"),
            row.get("RSI"),
            row.get("ATR"),
            row.get("Trend"),
            row.get("Momentum"),
            row.get("Volume"),
            row.get("Suggested Shares"),
            row.get("Stop Loss"),
            row.get("Take Profit"),
            row.get("Dollar Risk")
        ))

    conn.commit()
    conn.close()


def get_recent_scanner_results(limit=100, db_path=DB_PATH):
    initialise_database(db_path)

    conn = get_connection(db_path)

    results = pd.read_sql_query(
        """
        SELECT
            scan_time AS "Scan Time",
            symbol AS Symbol,
            strategy AS Strategy,
            status AS Status,
            signal AS Signal,
            confidence AS Confidence,
            alpha_score AS "Alpha Score",
            alpha_grade AS "Alpha Grade",
            market_regime AS "Market Regime",
            strategy_allowed AS "Strategy Allowed",
            regime_reason AS "Regime Reason",
            price AS Price,
            rsi AS RSI,
            atr AS ATR,
            trend AS Trend,
            momentum AS Momentum,
            volume AS Volume,
            suggested_shares AS "Suggested Shares",
            stop_loss AS "Stop Loss",
            take_profit AS "Take Profit",
            dollar_risk AS "Dollar Risk"
        FROM scanner_results
        ORDER BY id DESC
        LIMIT ?
        """,
        conn,
        params=(limit,)
    )

    conn.close()

    return results


def get_recent_buy_signals(limit=50, db_path=DB_PATH):
    initialise_database(db_path)

    conn = get_connection(db_path)

    results = pd.read_sql_query(
        """
        SELECT
            scan_time AS "Scan Time",
            symbol AS Symbol,
            strategy AS Strategy,
            alpha_score AS "Alpha Score",
            alpha_grade AS "Alpha Grade",
            market_regime AS "Market Regime",
            price AS Price,
            rsi AS RSI,
            atr AS ATR,
            suggested_shares AS "Suggested Shares",
            stop_loss AS "Stop Loss",
            take_profit AS "Take Profit",
            dollar_risk AS "Dollar Risk"
        FROM scanner_results
        WHERE signal = 'BUY'
        ORDER BY id DESC
        LIMIT ?
        """,
        conn,
        params=(limit,)
    )

    conn.close()

    return results