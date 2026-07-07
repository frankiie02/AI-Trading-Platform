from core.market_data.yahoo_data import download_price_data
from core.voting.engine import run_strategy_voting


def main():
    data = download_price_data(
        symbol="SPY",
        period="1y",
        interval="1d",
        auto_adjust=True
    )

    result = run_strategy_voting(data)

    print("Final Signal:", result["final_signal"])
    print("Vote Score:", result["vote_score"])
    print("Votes:", result["buy_votes"], "/", result["total_votes"])
    print("Confidence:", result["confidence"])
    print("Reasons:", result["reasons"])
    print("Strategy Votes:")

    for vote in result["strategy_votes"]:
        print(vote)


if __name__ == "__main__":
    main()