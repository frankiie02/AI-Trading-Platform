def calculate_metrics(trades, initial_balance=10000):
    if trades.empty:
        return {}

    total_trades = len(trades)
    wins = trades[trades["PnL %"] > 0]
    losses = trades[trades["PnL %"] <= 0]

    final_balance = trades.iloc[-1]["Balance"]
    net_profit_pct = ((final_balance - initial_balance) / initial_balance) * 100

    win_rate = (len(wins) / total_trades) * 100

    gross_profit = wins["PnL %"].sum()
    gross_loss = abs(losses["PnL %"].sum())
    profit_factor = gross_profit / gross_loss if gross_loss != 0 else None

    return {
        "Total Trades": total_trades,
        "Wins": len(wins),
        "Losses": len(losses),
        "Win Rate %": round(win_rate, 2),
        "Net Profit %": round(net_profit_pct, 2),
        "Final Balance": round(final_balance, 2),
        "Profit Factor": round(profit_factor, 2) if profit_factor else None,
        "Average Trade %": round(trades["PnL %"].mean(), 2),
        "Best Trade %": round(trades["PnL %"].max(), 2),
        "Worst Trade %": round(trades["PnL %"].min(), 2),
    }