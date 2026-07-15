"""Persistence functions for PaperTradingService (core/services/paper_trading_service.py).

Mirrors the existing core/execution/trade_queue.py and
core/scanner/scanner_repository.py convention: flat, table-scoped functions
that hand-write SQL via core.database.database.get_connection, with no ORM
and no generic repository base class. PaperTradingService calls these
functions instead of embedding raw SQL, and never opens a sqlite3
connection itself.

Fills are applied atomically: cash/position/trade-ledger/order-status are
all written inside a single connection/transaction per fill, with a
rollback on any failure. This is an approved correctness fix relative to
the legacy core/execution/paper_trader.py, whose buy()/sell() span two
separate connections/commits with no rollback path; paper_trader.py itself
is left untouched.
"""
from datetime import datetime
from typing import Optional

from core.database.database import DB_PATH, get_connection, initialise_database


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ----------------------------------------------------------------------
# Account state
# ----------------------------------------------------------------------

def get_account_row(db_path=DB_PATH):
    initialise_database(db_path)

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM account_state WHERE id = 1")
        return cursor.fetchone()
    finally:
        conn.close()


# ----------------------------------------------------------------------
# Positions
# ----------------------------------------------------------------------

def get_position_row(symbol, db_path=DB_PATH):
    initialise_database(db_path)

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM paper_positions WHERE symbol = ?", (symbol,))
        return cursor.fetchone()
    finally:
        conn.close()


def get_all_position_rows(db_path=DB_PATH):
    initialise_database(db_path)

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM paper_positions ORDER BY symbol")
        return cursor.fetchall()
    finally:
        conn.close()


def update_position_prices(symbol, current_price, db_path=DB_PATH) -> None:
    """Mark-to-market a single open position (mirrors PaperTrader.update_prices'
    per-symbol formula, applied through the new schema's realised_pnl-aware
    row shape)."""
    initialise_database(db_path)

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT shares, entry_price FROM paper_positions WHERE symbol = ?", (symbol,))
        row = cursor.fetchone()

        if row is None:
            return

        shares = row["shares"]
        entry_price = row["entry_price"]
        market_value = shares * current_price
        unrealised_pnl = (current_price - entry_price) * shares

        cursor.execute("""
            UPDATE paper_positions
            SET current_price = ?, market_value = ?, unrealised_pnl = ?, updated_at = ?
            WHERE symbol = ?
        """, (current_price, market_value, unrealised_pnl, now(), symbol))

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_position_levels(symbol, stop_loss=None, take_profit=None, db_path=DB_PATH) -> None:
    initialise_database(db_path)

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE paper_positions
            SET stop_loss = COALESCE(?, stop_loss),
                take_profit = COALESCE(?, take_profit),
                updated_at = ?
            WHERE symbol = ?
        """, (stop_loss, take_profit, now(), symbol))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ----------------------------------------------------------------------
# Orders
# ----------------------------------------------------------------------

def insert_order(
    symbol, side, quantity, order_type, requested_price,
    stop_loss, take_profit, strategy_name, strategy_mode,
    source_reference, status, db_path=DB_PATH
) -> int:
    initialise_database(db_path)

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        timestamp = now()
        cursor.execute("""
            INSERT INTO paper_orders (
                symbol, side, quantity, order_type, requested_price,
                stop_loss, take_profit, strategy_name, strategy_mode,
                source_reference, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol, side, quantity, order_type, requested_price,
            stop_loss, take_profit, strategy_name, strategy_mode,
            source_reference, status, timestamp, timestamp
        ))
        conn.commit()
        return cursor.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_order_status(order_id, status, rejection_reason=None, quantity=None, db_path=DB_PATH) -> None:
    initialise_database(db_path)

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE paper_orders
            SET status = ?,
                rejection_reason = COALESCE(?, rejection_reason),
                quantity = COALESCE(?, quantity),
                updated_at = ?
            WHERE id = ?
        """, (status, rejection_reason, quantity, now(), order_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_order_row(order_id, db_path=DB_PATH):
    initialise_database(db_path)

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM paper_orders WHERE id = ?", (order_id,))
        return cursor.fetchone()
    finally:
        conn.close()


def get_order_rows(status: Optional[str] = None, db_path=DB_PATH):
    initialise_database(db_path)

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()

        if status is None:
            cursor.execute("SELECT * FROM paper_orders ORDER BY id DESC")
        else:
            cursor.execute(
                "SELECT * FROM paper_orders WHERE status = ? ORDER BY id DESC",
                (status,)
            )

        return cursor.fetchall()
    finally:
        conn.close()


# ----------------------------------------------------------------------
# Trades (fill ledger, extended with round-trip economics on exits)
# ----------------------------------------------------------------------

def get_trade_rows(db_path=DB_PATH):
    initialise_database(db_path)

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM paper_trades ORDER BY id DESC")
        return cursor.fetchall()
    finally:
        conn.close()


def sum_realised_pnl(db_path=DB_PATH) -> float:
    initialise_database(db_path)

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(SUM(net_pnl), 0) AS total FROM paper_trades WHERE exit_reason IS NOT NULL"
        )
        row = cursor.fetchone()
        return float(row["total"]) if row else 0.0
    finally:
        conn.close()


# ----------------------------------------------------------------------
# Audit events
# ----------------------------------------------------------------------

def insert_audit_event(event_type, symbol=None, order_id=None, details=None, db_path=DB_PATH) -> None:
    initialise_database(db_path)

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO paper_audit_events (timestamp, event_type, symbol, order_id, details)
            VALUES (?, ?, ?, ?, ?)
        """, (now(), event_type, symbol, order_id, details))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ----------------------------------------------------------------------
# Atomic fill application
# ----------------------------------------------------------------------

def apply_entry_fill(
    order_id, symbol, quantity, fill_price, fees,
    stop_loss, take_profit, strategy_name, strategy_mode,
    db_path=DB_PATH
) -> float:
    """Atomically debits cash, opens/adds to a position (weighted-average
    entry price on adds, matching the existing PaperTrader convention),
    records the fill in paper_trades, and marks the order FILLED. Single
    transaction: any failure rolls back every part of the fill together.

    Returns the resulting cash balance.
    """
    initialise_database(db_path)

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        timestamp = now()

        cursor.execute("SELECT cash FROM account_state WHERE id = 1")
        row = cursor.fetchone()
        cash = row["cash"] if row else 0.0

        cost = quantity * fill_price + fees
        new_cash = cash - cost

        cursor.execute("SELECT * FROM paper_positions WHERE symbol = ?", (symbol,))
        existing = cursor.fetchone()

        if existing is not None:
            old_shares = existing["shares"]
            old_entry = existing["entry_price"]
            new_shares = old_shares + quantity
            new_entry = ((old_shares * old_entry) + (quantity * fill_price)) / new_shares
            market_value = new_shares * fill_price
            unrealised_pnl = (fill_price - new_entry) * new_shares

            cursor.execute("""
                UPDATE paper_positions
                SET shares = ?, entry_price = ?, current_price = ?, market_value = ?,
                    unrealised_pnl = ?, stop_loss = COALESCE(?, stop_loss),
                    take_profit = COALESCE(?, take_profit), updated_at = ?
                WHERE symbol = ?
            """, (
                new_shares, new_entry, fill_price, market_value, unrealised_pnl,
                stop_loss, take_profit, timestamp, symbol
            ))
        else:
            market_value = quantity * fill_price

            cursor.execute("""
                INSERT INTO paper_positions (
                    symbol, shares, entry_price, current_price, market_value,
                    unrealised_pnl, stop_loss, take_profit, trailing_stop,
                    realised_pnl, opened_at, updated_at, strategy_name, strategy_mode
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, NULL, 0, ?, ?, ?, ?)
            """, (
                symbol, quantity, fill_price, fill_price, market_value,
                stop_loss, take_profit, timestamp, timestamp, strategy_name, strategy_mode
            ))

        cursor.execute(
            "UPDATE account_state SET cash = ?, updated_at = ? WHERE id = 1",
            (new_cash, timestamp)
        )

        cursor.execute("""
            INSERT INTO paper_trades (
                timestamp, symbol, side, shares, price, value, cash_after_trade,
                order_id, entry_price, fees, strategy_name, strategy_mode
            ) VALUES (?, ?, 'BUY', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp, symbol, quantity, fill_price, quantity * fill_price, new_cash,
            order_id, fill_price, fees, strategy_name, strategy_mode
        ))

        cursor.execute("""
            UPDATE paper_orders
            SET status = 'FILLED', fill_price = ?, fill_timestamp = ?, fees = ?,
                quantity = ?, updated_at = ?
            WHERE id = ?
        """, (fill_price, timestamp, fees, quantity, timestamp, order_id))

        conn.commit()
        return new_cash
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def apply_exit_fill(
    symbol, quantity, fill_price, fees, exit_reason,
    strategy_name, strategy_mode, order_id=None,
    db_path=DB_PATH
) -> dict:
    """Atomically closes (fully or partially) an open position, credits
    cash, accumulates realised P&L on both the position (if left open) and
    the account, records the fill/round-trip trade in paper_trades, and
    (if order_id is given) marks that order FILLED. Single transaction.

    Returns a dict: cash, gross_pnl, net_pnl, remaining_shares, entry_price.
    """
    initialise_database(db_path)

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        timestamp = now()

        cursor.execute("SELECT * FROM paper_positions WHERE symbol = ?", (symbol,))
        position = cursor.fetchone()

        if position is None:
            raise ValueError(f"No open position for {symbol}.")

        current_shares = position["shares"]
        entry_price = position["entry_price"]
        existing_realised = position["realised_pnl"] or 0.0

        if quantity > current_shares:
            raise ValueError(
                f"Cannot close {quantity} shares of {symbol}; only "
                f"{current_shares} are held."
            )

        gross_pnl = (fill_price - entry_price) * quantity
        net_pnl = gross_pnl - fees
        proceeds = fill_price * quantity - fees

        remaining_shares = current_shares - quantity

        if remaining_shares == 0:
            cursor.execute("DELETE FROM paper_positions WHERE symbol = ?", (symbol,))
        else:
            market_value = remaining_shares * fill_price
            unrealised_pnl = (fill_price - entry_price) * remaining_shares
            new_realised = existing_realised + net_pnl

            cursor.execute("""
                UPDATE paper_positions
                SET shares = ?, current_price = ?, market_value = ?,
                    unrealised_pnl = ?, realised_pnl = ?, updated_at = ?
                WHERE symbol = ?
            """, (
                remaining_shares, fill_price, market_value, unrealised_pnl,
                new_realised, timestamp, symbol
            ))

        cursor.execute("SELECT cash, realised_pnl FROM account_state WHERE id = 1")
        account_row = cursor.fetchone()
        cash = account_row["cash"] if account_row else 0.0
        account_realised = (account_row["realised_pnl"] or 0.0) if account_row else 0.0

        new_cash = cash + proceeds
        new_account_realised = account_realised + net_pnl

        cursor.execute("""
            UPDATE account_state SET cash = ?, realised_pnl = ?, updated_at = ? WHERE id = 1
        """, (new_cash, new_account_realised, timestamp))

        cursor.execute("""
            INSERT INTO paper_trades (
                timestamp, symbol, side, shares, price, value, cash_after_trade,
                order_id, entry_price, gross_pnl, fees, net_pnl, exit_reason,
                strategy_name, strategy_mode
            ) VALUES (?, ?, 'SELL', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp, symbol, quantity, fill_price, proceeds, new_cash,
            order_id, entry_price, gross_pnl, fees, net_pnl, exit_reason,
            strategy_name, strategy_mode
        ))

        if order_id is not None:
            cursor.execute("""
                UPDATE paper_orders
                SET status = 'FILLED', fill_price = ?, fill_timestamp = ?, fees = ?, updated_at = ?
                WHERE id = ?
            """, (fill_price, timestamp, fees, timestamp, order_id))

        conn.commit()

        return {
            "cash": new_cash,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "remaining_shares": remaining_shares,
            "entry_price": entry_price,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
