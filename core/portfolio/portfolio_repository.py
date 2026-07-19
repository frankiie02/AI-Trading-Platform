"""Portfolio snapshot persistence for PortfolioService (core/services/portfolio_service.py).

Mirrors the existing core/execution/paper_orders_repository.py convention:
flat, table-scoped functions that hand-write SQL via
core.database.database.get_connection, with no ORM. Snapshot writes are a
single-row insert (no multi-table transaction is needed here, unlike the
order-fill functions in paper_orders_repository.py).
"""
from datetime import datetime
from typing import Optional

from core.database.database import DB_PATH, get_connection, initialise_database


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def insert_snapshot(
    account_id, cash, market_value, equity, realised_pnl, unrealised_pnl,
    gross_exposure, position_count, db_path=DB_PATH
) -> int:
    initialise_database(db_path)

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO portfolio_snapshots (
                timestamp, account_id, cash, market_value, equity,
                realised_pnl, unrealised_pnl, gross_exposure, position_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            now(), account_id, cash, market_value, equity,
            realised_pnl, unrealised_pnl, gross_exposure, position_count
        ))
        conn.commit()
        return cursor.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_snapshot_rows(account_id=None, limit: Optional[int] = None, db_path=DB_PATH):
    """Returns snapshot rows in chronological order (oldest first), matching
    the order an equity curve is plotted in."""
    initialise_database(db_path)

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()

        if account_id is not None:
            query = "SELECT * FROM portfolio_snapshots WHERE account_id = ? ORDER BY id ASC"
            params = (account_id,)
        else:
            query = "SELECT * FROM portfolio_snapshots ORDER BY id ASC"
            params = ()

        cursor.execute(query, params)
        rows = cursor.fetchall()

        if limit is not None:
            rows = rows[-limit:]

        return rows
    finally:
        conn.close()
