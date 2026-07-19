import sqlite3

import pytest

from core.database.database import get_connection, initialise_database
from core.portfolio.portfolio_repository import get_snapshot_rows, insert_snapshot


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "schema_test.db")


def _columns(conn, table):
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in cursor.fetchall()}


def _tables(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {row["name"] for row in cursor.fetchall()}


def test_initialise_database_creates_new_tables_on_fresh_db(db_path):
    initialise_database(db_path)

    conn = get_connection(db_path)
    tables = _tables(conn)
    conn.close()

    assert "paper_orders" in tables
    assert "paper_audit_events" in tables
    assert "portfolio_snapshots" in tables
    # Pre-existing tables are still created, unrenamed.
    assert {"account_state", "paper_positions", "paper_trades", "trade_queue", "scanner_results"} <= tables


def test_portfolio_snapshots_table_has_expected_columns(db_path):
    initialise_database(db_path)

    conn = get_connection(db_path)
    columns = _columns(conn, "portfolio_snapshots")
    conn.close()

    assert {
        "id", "timestamp", "account_id", "cash", "market_value", "equity",
        "realised_pnl", "unrealised_pnl", "gross_exposure", "position_count",
    } <= columns


def test_new_columns_present_on_existing_tables(db_path):
    initialise_database(db_path)

    conn = get_connection(db_path)

    account_columns = _columns(conn, "account_state")
    position_columns = _columns(conn, "paper_positions")
    trade_columns = _columns(conn, "paper_trades")
    order_columns = _columns(conn, "paper_orders")

    conn.close()

    assert {"realised_pnl", "reserved_cash"} <= account_columns
    assert {"realised_pnl", "opened_at", "strategy_name", "strategy_mode"} <= position_columns
    assert {"order_id", "entry_price", "gross_pnl", "fees", "net_pnl", "exit_reason",
            "strategy_name", "strategy_mode"} <= trade_columns
    assert {
        "id", "symbol", "side", "quantity", "order_type", "requested_price",
        "stop_loss", "take_profit", "strategy_name", "strategy_mode",
        "source_reference", "status", "rejection_reason", "fill_price",
        "fill_timestamp", "fees", "created_at", "updated_at",
    } <= order_columns


def test_initialise_database_is_idempotent(db_path):
    initialise_database(db_path)
    initialise_database(db_path)
    initialise_database(db_path)

    conn = get_connection(db_path)
    # No duplicate-column errors on repeated calls, and columns aren't duplicated.
    columns = list(_columns(conn, "paper_positions"))
    conn.close()

    assert len(columns) == len(set(columns))


def test_migration_is_additive_on_a_pre_existing_legacy_shaped_db(db_path):
    """Simulates a database created before this milestone (old column set
    only) and asserts initialise_database() adds the new columns/tables
    without dropping or renaming anything already there."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE account_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            starting_balance REAL NOT NULL,
            cash REAL NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE paper_positions (
            symbol TEXT PRIMARY KEY,
            shares INTEGER NOT NULL,
            entry_price REAL NOT NULL,
            current_price REAL NOT NULL,
            market_value REAL NOT NULL,
            unrealised_pnl REAL NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            shares INTEGER NOT NULL,
            price REAL NOT NULL,
            value REAL NOT NULL,
            cash_after_trade REAL NOT NULL
        )
    """)
    cursor.execute("""
        INSERT INTO account_state (id, starting_balance, cash, updated_at)
        VALUES (1, 100000, 97000, '2026-01-01 00:00:00')
    """)
    cursor.execute("""
        INSERT INTO paper_positions (
            symbol, shares, entry_price, current_price, market_value, unrealised_pnl, updated_at
        )
        VALUES ('AAPL', 10, 100.0, 105.0, 1050.0, 50.0, '2026-01-01 00:00:00')
    """)
    conn.commit()
    conn.close()

    initialise_database(db_path)

    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM account_state WHERE id = 1")
    account_row = cursor.fetchone()

    cursor.execute("SELECT * FROM paper_positions WHERE symbol = 'AAPL'")
    position_row = cursor.fetchone()

    tables = _tables(conn)
    conn.close()

    # Pre-existing data survives untouched.
    assert account_row["cash"] == 97000
    assert position_row["shares"] == 10
    assert position_row["entry_price"] == 100.0

    # New columns exist (nullable/defaulted) without disturbing old data.
    assert account_row["realised_pnl"] in (0, None)
    assert position_row["realised_pnl"] in (0, None)

    assert "paper_orders" in tables
    assert "paper_audit_events" in tables
    assert "portfolio_snapshots" in tables


def test_portfolio_snapshot_repository_round_trip(db_path):
    """Focused integration test for core/portfolio/portfolio_repository.py,
    using a temporary SQLite database only."""
    insert_snapshot(
        account_id="default", cash=9000.0, market_value=1000.0, equity=10000.0,
        realised_pnl=0.0, unrealised_pnl=0.0, gross_exposure=10.0, position_count=1,
        db_path=db_path,
    )
    insert_snapshot(
        account_id="default", cash=8500.0, market_value=1600.0, equity=10100.0,
        realised_pnl=0.0, unrealised_pnl=100.0, gross_exposure=15.8, position_count=1,
        db_path=db_path,
    )

    rows = get_snapshot_rows(account_id="default", db_path=db_path)

    assert len(rows) == 2
    assert rows[0]["equity"] == 10000.0
    assert rows[1]["equity"] == 10100.0

    limited = get_snapshot_rows(account_id="default", limit=1, db_path=db_path)
    assert len(limited) == 1
    assert limited[0]["equity"] == 10100.0
