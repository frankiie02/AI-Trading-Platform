import math


def calculate_position_size(
    account_balance,
    risk_percent,
    entry_price,
    stop_loss
):
    """
    Calculate position size using fixed fractional risk.

    Parameters
    ----------
    account_balance : float
    risk_percent : float
        Percentage of account to risk (e.g. 1 = 1%)
    entry_price : float
    stop_loss : float
    """

    risk_amount = account_balance * (risk_percent / 100)

    risk_per_share = abs(entry_price - stop_loss)

    if risk_per_share == 0:
        return None

    shares = math.floor(risk_amount / risk_per_share)

    capital_required = shares * entry_price

    return {
        "shares": shares,
        "risk_amount": round(risk_amount, 2),
        "risk_per_share": round(risk_per_share, 2),
        "capital_required": round(capital_required, 2),
    }