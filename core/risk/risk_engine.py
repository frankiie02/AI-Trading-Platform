def calculate_position_size(
    account_balance,
    entry_price,
    stop_loss_price,
    risk_percent=1
):
    risk_amount = account_balance * (risk_percent / 100)

    risk_per_share = entry_price - stop_loss_price

    if risk_per_share <= 0:
        return 0, risk_amount

    shares = int(risk_amount / risk_per_share)

    return shares, risk_amount


def calculate_atr_stop_loss(
    entry_price,
    atr,
    atr_multiplier=2
):
    return entry_price - (atr * atr_multiplier)


def calculate_take_profit(
    entry_price,
    stop_loss_price,
    reward_risk_ratio=2
):
    risk_per_share = entry_price - stop_loss_price

    return entry_price + (risk_per_share * reward_risk_ratio)