import matplotlib.pyplot as plt


def create_equity_curve(trades, output_path="analytics/equity_curve.png"):
    if trades.empty:
        return

    plt.figure(figsize=(10, 5))
    plt.plot(trades["Exit Date"], trades["Balance"])
    plt.title("Equity Curve")
    plt.xlabel("Date")
    plt.ylabel("Balance")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()


def create_drawdown_chart(trades, output_path="analytics/drawdown.png"):
    if trades.empty:
        return

    balance = trades["Balance"]
    peak = balance.cummax()
    drawdown = ((balance - peak) / peak) * 100

    plt.figure(figsize=(10, 5))
    plt.plot(trades["Exit Date"], drawdown)
    plt.title("Drawdown")
    plt.xlabel("Date")
    plt.ylabel("Drawdown %")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()