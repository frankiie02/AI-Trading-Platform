import os
import pandas as pd
from datetime import datetime


class PaperTrader:
    def __init__(
        self,
        starting_balance=100000,
        portfolio_path="data/paper_portfolio.csv",
        trade_log_path="data/paper_trade_log.csv"
    ):
        self.starting_balance = starting_balance
        self.portfolio_path = portfolio_path
        self.trade_log_path = trade_log_path

        os.makedirs(os.path.dirname(self.portfolio_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.trade_log_path), exist_ok=True)

        self.cash = self._load_cash()
        self.positions = self._load_positions()

    def _load_cash(self):
        if os.path.exists(self.portfolio_path):
            portfolio = pd.read_csv(self.portfolio_path)

            if not portfolio.empty and "Cash" in portfolio.columns:
                return float(portfolio["Cash"].iloc[-1])

        return float(self.starting_balance)

    def _load_positions(self):
        if os.path.exists(self.portfolio_path):
            portfolio = pd.read_csv(self.portfolio_path)

            required_columns = [
                "Symbol",
                "Shares",
                "Entry Price",
                "Current Price",
                "Market Value",
                "Unrealised PnL"
            ]

            if all(col in portfolio.columns for col in required_columns):
                return portfolio[required_columns].copy()

        return pd.DataFrame(
            columns=[
                "Symbol",
                "Shares",
                "Entry Price",
                "Current Price",
                "Market Value",
                "Unrealised PnL"
            ]
        )

    def buy(self, symbol, shares, price):
        if shares <= 0:
            return False, "Shares must be greater than zero."

        cost = shares * price

        if cost > self.cash:
            return False, "Not enough cash to place this trade."

        existing_position = self.positions[
            self.positions["Symbol"] == symbol
        ]

        if not existing_position.empty:
            index = existing_position.index[0]

            old_shares = self.positions.loc[index, "Shares"]
            old_entry = self.positions.loc[index, "Entry Price"]

            new_shares = old_shares + shares
            new_entry = (
                (old_shares * old_entry) + (shares * price)
            ) / new_shares

            self.positions.loc[index, "Shares"] = new_shares
            self.positions.loc[index, "Entry Price"] = new_entry
            self.positions.loc[index, "Current Price"] = price
        else:
            new_position = pd.DataFrame([{
                "Symbol": symbol,
                "Shares": shares,
                "Entry Price": price,
                "Current Price": price,
                "Market Value": shares * price,
                "Unrealised PnL": 0
            }])

            self.positions = pd.concat(
                [self.positions, new_position],
                ignore_index=True
            )

        self.cash -= cost
        self._update_market_values()
        self._save_state()
        self._log_trade(symbol, "BUY", shares, price, cost)

        return True, f"Bought {shares} shares of {symbol} at ${price:,.2f}."

    def sell(self, symbol, shares, price):
        if shares <= 0:
            return False, "Shares must be greater than zero."

        position = self.positions[
            self.positions["Symbol"] == symbol
        ]

        if position.empty:
            return False, f"No open position found for {symbol}."

        index = position.index[0]
        current_shares = self.positions.loc[index, "Shares"]

        if shares > current_shares:
            return False, "Cannot sell more shares than currently held."

        proceeds = shares * price

        self.positions.loc[index, "Shares"] = current_shares - shares
        self.positions.loc[index, "Current Price"] = price

        if self.positions.loc[index, "Shares"] == 0:
            self.positions = self.positions.drop(index).reset_index(drop=True)

        self.cash += proceeds
        self._update_market_values()
        self._save_state()
        self._log_trade(symbol, "SELL", shares, price, proceeds)

        return True, f"Sold {shares} shares of {symbol} at ${price:,.2f}."

    def update_prices(self, price_map):
        for symbol, price in price_map.items():
            mask = self.positions["Symbol"] == symbol

            if mask.any():
                self.positions.loc[mask, "Current Price"] = price

        self._update_market_values()
        self._save_state()

    def _update_market_values(self):
        if self.positions.empty:
            return

        self.positions["Market Value"] = (
            self.positions["Shares"] *
            self.positions["Current Price"]
        )

        self.positions["Unrealised PnL"] = (
            self.positions["Current Price"] -
            self.positions["Entry Price"]
        ) * self.positions["Shares"]

    def _save_state(self):
        portfolio = self.positions.copy()

        if portfolio.empty:
            portfolio = pd.DataFrame(
                columns=[
                    "Symbol",
                    "Shares",
                    "Entry Price",
                    "Current Price",
                    "Market Value",
                    "Unrealised PnL"
                ]
            )

        portfolio["Cash"] = self.cash
        portfolio["Updated At"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        portfolio.to_csv(self.portfolio_path, index=False)

    def _log_trade(self, symbol, side, shares, price, value):
        trade = pd.DataFrame([{
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Symbol": symbol,
            "Side": side,
            "Shares": shares,
            "Price": price,
            "Value": value,
            "Cash After Trade": self.cash
        }])

        if os.path.exists(self.trade_log_path):
            existing = pd.read_csv(self.trade_log_path)
            trade_log = pd.concat([existing, trade], ignore_index=True)
        else:
            trade_log = trade

        trade_log.to_csv(self.trade_log_path, index=False)

    def get_account_summary(self):
        total_market_value = (
            self.positions["Market Value"].sum()
            if not self.positions.empty
            else 0
        )

        unrealised_pnl = (
            self.positions["Unrealised PnL"].sum()
            if not self.positions.empty
            else 0
        )

        portfolio_value = self.cash + total_market_value

        return {
            "Starting Balance": self.starting_balance,
            "Cash": self.cash,
            "Market Value": total_market_value,
            "Portfolio Value": portfolio_value,
            "Unrealised PnL": unrealised_pnl,
            "Open Positions": len(self.positions),
        }