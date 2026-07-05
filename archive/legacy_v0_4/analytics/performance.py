import numpy as np
import pandas as pd


def extract_trades(data):
    trades = []

    in_trade = False
    entry_price = None
    entry_date = None

    for date, row in data.iterrows():
        position = row["Position"]
        close_price = row["Close"]

        if not in_trade and position == 1:
            in_trade = True
            entry_price = close_price
            entry_date = date

        elif in_trade and position == 0:
            exit_price = close_price
            exit_date = date

            pnl = exit_price - entry_price
            pnl_pct = (pnl / entry_price) * 100

            trades.append({
                "Entry Date": entry_date,
                "Exit Date": exit_date,
                "Entry Price": entry_price,
                "Exit Price": exit_price,
                "PnL": pnl,
                "PnL %": pnl_pct,
            })

            in_trade = False

    return pd.DataFrame(trades)


def calculate_performance(data, initial_balance):
    data = data.copy()

    final_value = data["Strategy Equity"].iloc[-1]
    profit_loss = final_value - initial_balance
    profit_loss_pct = (profit_loss / initial_balance) * 100

    running_max = data["Strategy Equity"].cummax()
    drawdown = (data["Strategy Equity"] - running_max) / running_max
    max_drawdown = drawdown.min() * 100

    daily_returns = data["Strategy Return"].dropna()

    if daily_returns.std() != 0:
        sharpe_ratio = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
    else:
        sharpe_ratio = 0

    total_days = len(data)
    years = total_days / 252

    if years > 0:
        cagr = ((final_value / initial_balance) ** (1 / years) - 1) * 100
    else:
        cagr = 0

    trades = extract_trades(data)
    total_trades = len(trades)

    if total_trades > 0:
        winning_trades = trades[trades["PnL"] > 0]
        losing_trades = trades[trades["PnL"] <= 0]

        win_rate = (len(winning_trades) / total_trades) * 100

        average_winner = winning_trades["PnL"].mean() if not winning_trades.empty else 0
        average_loser = losing_trades["PnL"].mean() if not losing_trades.empty else 0

        gross_profit = winning_trades["PnL"].sum()
        gross_loss = abs(losing_trades["PnL"].sum())

        profit_factor = gross_profit / gross_loss if gross_loss != 0 else 0
    else:
        win_rate = 0
        average_winner = 0
        average_loser = 0
        profit_factor = 0

    metrics = {
        "Final Value": final_value,
        "Profit/Loss": profit_loss,
        "Profit/Loss %": profit_loss_pct,
        "Max Drawdown %": max_drawdown,
        "Sharpe Ratio": sharpe_ratio,
        "CAGR %": cagr,
        "Total Trades": total_trades,
        "Win Rate %": win_rate,
        "Average Winner": average_winner,
        "Average Loser": average_loser,
        "Profit Factor": profit_factor,
    }

    return metrics, trades