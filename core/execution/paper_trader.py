from datetime import datetime

import pandas as pd

from core.database.database import (
    DB_PATH,
    get_connection,
    initialise_account,
    initialise_database
)


class PaperTrader:
    def __init__(
        self,
        starting_balance=100000,
        db_path=DB_PATH
    ):
        self.starting_balance = float(starting_balance)
        self.db_path = db_path

        initialise_database(self.db_path)
        initialise_account(self.starting_balance, self.db_path)

    def _now(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _get_cash(self):
        conn = get_connection(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT cash FROM account_state WHERE id = 1")
        row = cursor.fetchone()

        conn.close()

        if row is None:
            return self.starting_balance

        return float(row["cash"])

    def _set_cash(self, cash):
        conn = get_connection(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE account_state
            SET cash = ?, updated_at = ?
            WHERE id = 1
        """, (
            float(cash),
            self._now()
        ))

        conn.commit()
        conn.close()

    def _log_trade(self, symbol, side, shares, price, value, cash_after_trade):
        conn = get_connection(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO paper_trades (
                timestamp,
                symbol,
                side,
                shares,
                price,
                value,
                cash_after_trade
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            self._now(),
            symbol.upper(),
            side.upper(),
            int(shares),
            float(price),
            float(value),
            float(cash_after_trade)
        ))

        conn.commit()
        conn.close()

    def get_positions(self):
        conn = get_connection(self.db_path)

        positions = pd.read_sql_query(
            """
            SELECT
                symbol AS Symbol,
                shares AS Shares,
                entry_price AS "Entry Price",
                current_price AS "Current Price",
                market_value AS "Market Value",
                unrealised_pnl AS "Unrealised PnL",
                updated_at AS "Updated At"
            FROM paper_positions
            ORDER BY symbol
            """,
            conn
        )

        conn.close()

        return positions

    @property
    def positions(self):
        return self.get_positions()

    def get_trade_log(self):
        conn = get_connection(self.db_path)

        trades = pd.read_sql_query(
            """
            SELECT
                timestamp AS Timestamp,
                symbol AS Symbol,
                side AS Side,
                shares AS Shares,
                price AS Price,
                value AS Value,
                cash_after_trade AS "Cash After Trade"
            FROM paper_trades
            ORDER BY id DESC
            """,
            conn
        )

        conn.close()

        return trades

    def buy(self, symbol, shares, price):
        symbol = symbol.upper()
        shares = int(shares)
        price = float(price)

        if shares <= 0:
            return False, "Shares must be greater than zero."

        cash = self._get_cash()
        cost = shares * price

        if cost > cash:
            return False, "Not enough cash to place this trade."

        conn = get_connection(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM paper_positions WHERE symbol = ?",
            (symbol,)
        )

        position = cursor.fetchone()

        if position:
            old_shares = int(position["shares"])
            old_entry = float(position["entry_price"])

            new_shares = old_shares + shares
            new_entry = (
                (old_shares * old_entry) + (shares * price)
            ) / new_shares

            market_value = new_shares * price
            unrealised_pnl = (price - new_entry) * new_shares

            cursor.execute("""
                UPDATE paper_positions
                SET
                    shares = ?,
                    entry_price = ?,
                    current_price = ?,
                    market_value = ?,
                    unrealised_pnl = ?,
                    updated_at = ?
                WHERE symbol = ?
            """, (
                new_shares,
                new_entry,
                price,
                market_value,
                unrealised_pnl,
                self._now(),
                symbol
            ))

        else:
            cursor.execute("""
                INSERT INTO paper_positions (
                    symbol,
                    shares,
                    entry_price,
                    current_price,
                    market_value,
                    unrealised_pnl,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol,
                shares,
                price,
                price,
                cost,
                0,
                self._now()
            ))

        new_cash = cash - cost

        cursor.execute("""
            UPDATE account_state
            SET cash = ?, updated_at = ?
            WHERE id = 1
        """, (
            new_cash,
            self._now()
        ))

        conn.commit()
        conn.close()

        self._log_trade(
            symbol=symbol,
            side="BUY",
            shares=shares,
            price=price,
            value=cost,
            cash_after_trade=new_cash
        )

        return True, f"Bought {shares} shares of {symbol} at ${price:,.2f}."

    def sell(self, symbol, shares, price):
        symbol = symbol.upper()
        shares = int(shares)
        price = float(price)

        if shares <= 0:
            return False, "Shares must be greater than zero."

        conn = get_connection(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM paper_positions WHERE symbol = ?",
            (symbol,)
        )

        position = cursor.fetchone()

        if position is None:
            conn.close()
            return False, f"No open position found for {symbol}."

        current_shares = int(position["shares"])

        if shares > current_shares:
            conn.close()
            return False, "Cannot sell more shares than currently held."

        cash = self._get_cash()
        proceeds = shares * price
        remaining_shares = current_shares - shares

        if remaining_shares == 0:
            cursor.execute(
                "DELETE FROM paper_positions WHERE symbol = ?",
                (symbol,)
            )
        else:
            entry_price = float(position["entry_price"])
            market_value = remaining_shares * price
            unrealised_pnl = (price - entry_price) * remaining_shares

            cursor.execute("""
                UPDATE paper_positions
                SET
                    shares = ?,
                    current_price = ?,
                    market_value = ?,
                    unrealised_pnl = ?,
                    updated_at = ?
                WHERE symbol = ?
            """, (
                remaining_shares,
                price,
                market_value,
                unrealised_pnl,
                self._now(),
                symbol
            ))

        new_cash = cash + proceeds

        cursor.execute("""
            UPDATE account_state
            SET cash = ?, updated_at = ?
            WHERE id = 1
        """, (
            new_cash,
            self._now()
        ))

        conn.commit()
        conn.close()

        self._log_trade(
            symbol=symbol,
            side="SELL",
            shares=shares,
            price=price,
            value=proceeds,
            cash_after_trade=new_cash
        )

        return True, f"Sold {shares} shares of {symbol} at ${price:,.2f}."

    def update_prices(self, price_map):
        conn = get_connection(self.db_path)
        cursor = conn.cursor()

        for symbol, price in price_map.items():
            symbol = symbol.upper()
            price = float(price)

            cursor.execute(
                "SELECT * FROM paper_positions WHERE symbol = ?",
                (symbol,)
            )

            position = cursor.fetchone()

            if position:
                shares = int(position["shares"])
                entry_price = float(position["entry_price"])

                market_value = shares * price
                unrealised_pnl = (price - entry_price) * shares

                cursor.execute("""
                    UPDATE paper_positions
                    SET
                        current_price = ?,
                        market_value = ?,
                        unrealised_pnl = ?,
                        updated_at = ?
                    WHERE symbol = ?
                """, (
                    price,
                    market_value,
                    unrealised_pnl,
                    self._now(),
                    symbol
                ))

        conn.commit()
        conn.close()

    def get_account_summary(self):
        cash = self._get_cash()
        positions = self.get_positions()

        if positions.empty:
            market_value = 0
            unrealised_pnl = 0
            open_positions = 0
        else:
            market_value = float(positions["Market Value"].sum())
            unrealised_pnl = float(positions["Unrealised PnL"].sum())
            open_positions = len(positions)

        portfolio_value = cash + market_value

        return {
            "Starting Balance": self.starting_balance,
            "Cash": cash,
            "Market Value": market_value,
            "Portfolio Value": portfolio_value,
            "Unrealised PnL": unrealised_pnl,
            "Open Positions": open_positions,
        }