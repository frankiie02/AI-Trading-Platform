def passes_minimum_alpha(score, minimum_score=70):
    return score >= minimum_score


def should_queue_trade(signal, alpha_score, minimum_score=70):
    return signal == "BUY" and alpha_score >= minimum_score


def filter_tradeable_results(results, minimum_score=70):
    filtered = []

    for row in results:
        signal = row.get("Signal", "NO TRADE")
        alpha_score = row.get("Alpha Score", 0)

        if should_queue_trade(
            signal=signal,
            alpha_score=alpha_score,
            minimum_score=minimum_score
        ):
            filtered.append(row)

    return filtered