import pandas as pd

from indicators.atr import calculate_atr


def run_backtest(data, symbol, initial_balance=10000):
    df = data.copy()

    df["EMA_20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA_50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["Volume_Avg_20"] = df["Volume"].rolling(20).mean()
    df["ATR"] = calculate_atr(df)

    trades = []
    balance = initial_balance
    in_position = False
    entry_price = None
    stop_loss = None
    take_profit = None
    entry_date = None

    for i in range(50, len(df)):
        row = df.iloc[i]

        if not in_position:
            rules_pass = (
                row["Close"] > row["EMA_20"]
                and row["EMA_20"] > row["EMA_50"]
                and row["Volume"] > row["Volume_Avg_20"]
            )

            if rules_pass:
                entry_price = float(row["Close"])
                atr = float(row["ATR"])
                stop_loss = entry_price - (2 * atr)
                take_profit = entry_price + (4 * atr)
                entry_date = row["Date"]
                in_position = True

        else:
            exit_price = None
            exit_reason = None

            if row["Low"] <= stop_loss:
                exit_price = stop_loss
                exit_reason = "STOP_LOSS"
            elif row["High"] >= take_profit:
                exit_price = take_profit
                exit_reason = "TAKE_PROFIT"

            if exit_price:
                pnl_pct = ((exit_price - entry_price) / entry_price) * 100
                balance = balance * (1 + pnl_pct / 100)

                trades.append({
                    "Symbol": symbol,
                    "Entry Date": entry_date,
                    "Exit Date": row["Date"],
                    "Entry Price": round(entry_price, 2),
                    "Exit Price": round(exit_price, 2),
                    "Exit Reason": exit_reason,
                    "PnL %": round(pnl_pct, 2),
                    "Balance": round(balance, 2),
                })

                in_position = False

    return pd.DataFrame(trades)