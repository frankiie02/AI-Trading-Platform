from config.settings import settings
from core.execution.paper_trader import PaperTrader


class ExecutionRouter:
    def __init__(self, mode="PAPER"):
        self.mode = mode.upper()

        self.paper_trader = PaperTrader(
            starting_balance=settings.STARTING_BALANCE
        )

    def execute_trade(
        self,
        symbol,
        side,
        shares,
        price
    ):
        symbol = symbol.upper()
        side = side.upper()
        shares = int(shares)
        price = float(price)

        if self.mode == "PAPER":
            return self._execute_paper_trade(
                symbol=symbol,
                side=side,
                shares=shares,
                price=price
            )

        if self.mode == "IBKR_PAPER":
            return False, "IBKR Paper execution is not active yet."

        if self.mode == "IBKR_LIVE":
            return False, "Live trading is disabled for safety."

        return False, f"Unknown execution mode: {self.mode}"

    def _execute_paper_trade(
        self,
        symbol,
        side,
        shares,
        price
    ):
        if side == "BUY":
            return self.paper_trader.buy(
                symbol=symbol,
                shares=shares,
                price=price
            )

        if side == "SELL":
            return self.paper_trader.sell(
                symbol=symbol,
                shares=shares,
                price=price
            )

        return False, f"Unsupported trade side: {side}"