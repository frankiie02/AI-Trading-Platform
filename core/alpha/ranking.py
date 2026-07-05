import pandas as pd


def rank_opportunities(results):
    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)

    if "Alpha Score" not in df.columns:
        df["Alpha Score"] = 0

    ranked = df.sort_values(
        by="Alpha Score",
        ascending=False
    ).reset_index(drop=True)

    ranked["Rank"] = ranked.index + 1

    columns = ["Rank"] + [
        col for col in ranked.columns if col != "Rank"
    ]

    return ranked[columns]


def get_top_opportunities(results, limit=10):
    ranked = rank_opportunities(results)

    if ranked.empty:
        return ranked

    return ranked.head(limit)