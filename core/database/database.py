import os
import sqlite3
from datetime import datetime


DB_PATH = "data/trading_platform.db"


def get_connection(db_path=DB_PATH):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


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