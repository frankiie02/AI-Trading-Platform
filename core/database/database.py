import os
import sqlite3
from datetime import datetime


DB_PATH = "data/trading_platform.db"


def get_connection(db_path=DB_PATH):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def add_column_if_missing(cursor, table_name, column_name, column_definition):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row["name"] for row in cursor.fetchall()]

    if column_name not in columns:
        cursor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
        )


def initialise_database(db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS account_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            starting_balance REAL NOT NULL,
            cash REAL NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # Additive columns for PaperTradingService: realised_pnl is the
    # cumulative realised gain/loss across all closed trades (kept in sync
    # with SUM(paper_trades.net_pnl) and checked by reconcile());
    # reserved_cash is 0 unless/until a future milestone introduces
    # working (not-yet-filled) orders that hold cash aside.
    add_column_if_missing(cursor, "account_state", "realised_pnl", "REAL DEFAULT 0")
    add_column_if_missing(cursor, "account_state", "reserved_cash", "REAL DEFAULT 0")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS paper_positions (
            symbol TEXT PRIMARY KEY,
            shares INTEGER NOT NULL,
            entry_price REAL NOT NULL,
            current_price REAL NOT NULL,
            market_value REAL NOT NULL,
            unrealised_pnl REAL NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    add_column_if_missing(cursor, "paper_positions", "stop_loss", "REAL")
    add_column_if_missing(cursor, "paper_positions", "take_profit", "REAL")
    add_column_if_missing(cursor, "paper_positions", "trailing_stop", "REAL")
    # Additive columns for PaperTradingService (core/services/paper_trading_service.py):
    # realised_pnl accumulates gains/losses from partial closes while a
    # position stays open; opened_at is distinct from updated_at (which the
    # legacy PaperTrader already mutates on every price refresh).
    add_column_if_missing(cursor, "paper_positions", "realised_pnl", "REAL DEFAULT 0")
    add_column_if_missing(cursor, "paper_positions", "opened_at", "TEXT")
    add_column_if_missing(cursor, "paper_positions", "strategy_name", "TEXT")
    add_column_if_missing(cursor, "paper_positions", "strategy_mode", "TEXT")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS paper_trades (
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

    # Additive columns for PaperTradingService round-trip trade records.
    # paper_trades remains a flat fill ledger (one row per fill, written by
    # both the legacy PaperTrader and PaperTradingService); these extra
    # columns are populated only on exit fills (PaperTradingService), giving
    # a round-trip trade record without duplicating the ledger. Legacy rows
    # written by PaperTrader leave them NULL.
    add_column_if_missing(cursor, "paper_trades", "order_id", "INTEGER")
    add_column_if_missing(cursor, "paper_trades", "entry_price", "REAL")
    add_column_if_missing(cursor, "paper_trades", "gross_pnl", "REAL")
    add_column_if_missing(cursor, "paper_trades", "fees", "REAL")
    add_column_if_missing(cursor, "paper_trades", "net_pnl", "REAL")
    add_column_if_missing(cursor, "paper_trades", "exit_reason", "TEXT")
    add_column_if_missing(cursor, "paper_trades", "strategy_name", "TEXT")
    add_column_if_missing(cursor, "paper_trades", "strategy_mode", "TEXT")

    # Order lifecycle for PaperTradingService (CREATED -> VALIDATED ->
    # SUBMITTED -> FILLED, or REJECTED/CANCELLED/EXPIRED). Distinct from the
    # pre-existing trade_queue table, which only tracks a pre-execution
    # staging status ("PENDING" -> free-text), not a validated order
    # state machine with fill price/fees/rejection reason.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS paper_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            order_type TEXT NOT NULL,
            requested_price REAL,
            stop_loss REAL,
            take_profit REAL,
            strategy_name TEXT,
            strategy_mode TEXT,
            source_reference TEXT,
            status TEXT NOT NULL,
            rejection_reason TEXT,
            fill_price REAL,
            fill_timestamp TEXT,
            fees REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # Audit/state-event trail for PaperTradingService (order/position
    # lifecycle events), used for reconciliation and diagnostics.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS paper_audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            symbol TEXT,
            order_id INTEGER,
            details TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scanner_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_time TEXT NOT NULL,
            symbol TEXT NOT NULL,
            status TEXT NOT NULL,
            signal TEXT NOT NULL,
            price REAL,
            rsi REAL,
            atr REAL,
            trend TEXT,
            momentum TEXT,
            volume TEXT,
            suggested_shares INTEGER,
            stop_loss REAL,
            take_profit REAL,
            dollar_risk REAL
        )
    """)

    add_column_if_missing(cursor, "scanner_results", "strategy", "TEXT")
    add_column_if_missing(cursor, "scanner_results", "confidence", "REAL")
    add_column_if_missing(cursor, "scanner_results", "alpha_score", "REAL")
    add_column_if_missing(cursor, "scanner_results", "alpha_grade", "TEXT")
    add_column_if_missing(cursor, "scanner_results", "reason", "TEXT")
    add_column_if_missing(cursor, "scanner_results", "alpha_reasons", "TEXT")
    add_column_if_missing(cursor, "scanner_results", "market_regime", "TEXT")
    add_column_if_missing(cursor, "scanner_results", "strategy_allowed", "TEXT")
    add_column_if_missing(cursor, "scanner_results", "regime_reason", "TEXT")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trade_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            shares INTEGER NOT NULL,
            price REAL NOT NULL,
            stop_loss REAL,
            take_profit REAL,
            dollar_risk REAL,
            status TEXT NOT NULL,
            source TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def initialise_account(starting_balance, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM account_state WHERE id = 1")
    existing = cursor.fetchone()

    if existing is None:
        cursor.execute("""
            INSERT INTO account_state (
                id,
                starting_balance,
                cash,
                updated_at
            )
            VALUES (?, ?, ?, ?)
        """, (
            1,
            starting_balance,
            starting_balance,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))

    conn.commit()
    conn.close()
