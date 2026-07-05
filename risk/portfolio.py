class Portfolio:
    def __init__(self, starting_balance=100000, max_open_positions=5):
        self.starting_balance = starting_balance
        self.cash = starting_balance
        self.max_open_positions = max_open_positions
        self.positions = {}

    def can_open_position(self, symbol, capital_required):
        if symbol in self.positions:
            return False, "Already holding this symbol"

        if len(self.positions) >= self.max_open_positions:
            return False, "Maximum open positions reached"

        if capital_required > self.cash:
            return False, "Not enough cash"

        return True, "Approved"

    def open_position(self, symbol, shares, entry_price, stop_loss, take_profit):
        capital_required = shares * entry_price

        approved, reason = self.can_open_position(symbol, capital_required)

        if not approved:
            return {
                "approved": False,
                "reason": reason
            }

        self.cash -= capital_required

        self.positions[symbol] = {
            "shares": shares,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "capital_required": capital_required
        }

        return {
            "approved": True,
            "reason": "Position opened",
            "cash_remaining": round(self.cash, 2)
        }

    def close_position(self, symbol, exit_price):
        if symbol not in self.positions:
            return {
                "closed": False,
                "reason": "Position not found"
            }

        position = self.positions.pop(symbol)

        proceeds = position["shares"] * exit_price
        cost = position["shares"] * position["entry_price"]
        pnl = proceeds - cost

        self.cash += proceeds

        return {
            "closed": True,
            "symbol": symbol,
            "pnl": round(pnl, 2),
            "cash": round(self.cash, 2)
        }

    def summary(self):
        return {
            "cash": round(self.cash, 2),
            "open_positions": len(self.positions),
            "positions": list(self.positions.keys())
        }