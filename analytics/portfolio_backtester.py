from risk.portfolio import Portfolio
from risk.position_sizer import calculate_position_size


class PortfolioBacktester:

    def __init__(self,
                 starting_balance=100000,
                 risk_percent=1,
                 max_positions=5):

        self.portfolio = Portfolio(
            starting_balance=starting_balance,
            max_open_positions=max_positions
        )

        self.risk_percent = risk_percent

        self.trade_log = []

    def process_trade(
        self,
        symbol,
        entry_price,
        stop_loss,
        take_profit,
        exit_price
    ):

        sizing = calculate_position_size(
            account_balance=self.portfolio.cash,
            risk_percent=self.risk_percent,
            entry_price=entry_price,
            stop_loss=stop_loss
        )

        if sizing is None:
            return

        result = self.portfolio.open_position(
            symbol=symbol,
            shares=sizing["shares"],
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit
        )

        if not result["approved"]:
            return

        close = self.portfolio.close_position(
            symbol,
            exit_price
        )

        self.trade_log.append({
            "symbol": symbol,
            "shares": sizing["shares"],
            "entry": entry_price,
            "exit": exit_price,
            "pnl": close["pnl"],
            "cash": close["cash"]
        })

    def summary(self):

        return {
            "cash": self.portfolio.cash,
            "trades": len(self.trade_log),
            "trade_log": self.trade_log
        }