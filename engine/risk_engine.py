from models.trade import Trade
from risk.position_sizer import calculate_position_size


class RiskEngine:
    def __init__(self, risk_percent=1):
        self.risk_percent = risk_percent

    def approve_signal(self, signal, portfolio):
        sizing = calculate_position_size(
            account_balance=portfolio.cash,
            risk_percent=self.risk_percent,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss
        )

        if sizing is None or sizing["shares"] <= 0:
            return None, "Invalid position size"

        approved, reason = portfolio.can_open_position(
            signal.symbol,
            sizing["capital_required"]
        )

        if not approved:
            return None, reason

        signal.approved = True

        trade = Trade(
            symbol=signal.symbol,
            entry_date=signal.timestamp,
            entry_price=signal.entry_price,
            shares=sizing["shares"],
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit
        )

        return trade, "Approved"