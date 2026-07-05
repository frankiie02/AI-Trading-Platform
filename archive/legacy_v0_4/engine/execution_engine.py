class ExecutionEngine:
    def execute_trade(self, trade, portfolio):
        result = portfolio.open_position(
            symbol=trade.symbol,
            shares=trade.shares,
            entry_price=trade.entry_price,
            stop_loss=trade.stop_loss,
            take_profit=trade.take_profit
        )

        return result

    def close_trade(self, trade, portfolio, exit_price, exit_date):
        trade.close(exit_price, exit_date)

        result = portfolio.close_position(
            symbol=trade.symbol,
            exit_price=exit_price
        )

        return result