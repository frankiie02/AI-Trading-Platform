from datetime import datetime

import pandas as pd

from core.database.database import (
    DB_PATH,
    get_connection,
    initialise_database
)


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def add_trade_to_queue(
    symbol,
    side,
    shares,
    price,
    stop_loss=None,
    take_profit=None,
    dollar_risk=None,
    source="scanner",
    db_path=DB_PATH
):
    initialise_database(db_path)

    if shares <= 0:
        return False, "Shares must be greater than zero."

    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO trade_queue (
            created_at,
            symbol,
            side,
            shares,
            price,
            stop_loss,
            take_profit,
            dollar_risk,
            status,
            source,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        now(),
        symbol.upper(),
        side.upper(),
        int(shares),
        float(price),
        stop_loss,
        take_profit,
        dollar_risk,
        "PENDING",
        source,
        now()
    ))

    conn.commit()
    conn.close()

    return True, f"Added {side.upper()} {shares} {symbol.upper()} to trade queue."


def save_buy_signals_to_queue(results, db_path=DB_PATH):
    added = 0

    for row in results:
        if row.get("Signal") != "BUY":
            continue

        shares = int(row.get("Suggested Shares") or 0)

        if shares <= 0:
            continue

        success, _ = add_trade_to_queue(
            symbol=row.get("Symbol"),
            side="BUY",
            shares=shares,
            price=row.get("Price"),
            stop_loss=row.get("Stop Loss"),
            take_profit=row.get("Take Profit"),
            dollar_risk=row.get("Dollar Risk"),
            source="scanner",
            db_path=db_path
        )

        if success:
            added += 1

    return added


def get_pending_trades(db_path=DB_PATH):
    initialise_database(db_path)

    conn = get_connection(db_path)

    trades = pd.read_sql_query(
        """
        SELECT
            id AS ID,
            created_at AS "Created At",
            symbol AS Symbol,
            side AS Side,
            shares AS Shares,
            price AS Price,
            stop_loss AS "Stop Loss",
            take_profit AS "Take Profit",
            dollar_risk AS "Dollar Risk",
            status AS Status,
            source AS Source
        FROM trade_queue
        WHERE status = 'PENDING'
        ORDER BY id DESC
        """,
        conn
    )

    conn.close()

    return trades


def get_recent_queue_history(limit=50, db_path=DB_PATH):
    initialise_database(db_path)

    conn = get_connection(db_path)

    history = pd.read_sql_query(
        """
        SELECT
            id AS ID,
            created_at AS "Created At",
            symbol AS Symbol,
            side AS Side,
            shares AS Shares,
            price AS Price,
            status AS Status,
            source AS Source,
            updated_at AS "Updated At"
        FROM trade_queue
        ORDER BY id DESC
        LIMIT ?
        """,
        conn,
        params=(limit,)
    )

    conn.close()

    return history


def update_trade_status(
    trade_id,
    status,
    db_path=DB_PATH
):
    initialise_database(db_path)

    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE trade_queue
        SET status = ?, updated_at = ?
        WHERE id = ?
    """, (
        status.upper(),
        now(),
        int(trade_id)
    ))

    conn.commit()
    conn.close()


def get_trade_by_id(trade_id, db_path=DB_PATH):
    initialise_database(db_path)

    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM trade_queue
        WHERE id = ?
    """, (
        int(trade_id),
    ))

    row = cursor.fetchone()
    conn.close()

    return row