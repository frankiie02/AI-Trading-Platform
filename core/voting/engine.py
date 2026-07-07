from core.indicators.pipeline import build_indicator_pipeline
from core.strategy.registry import STRATEGY_REGISTRY


def run_strategy_voting(
    df,
    short_ema=20,
    long_ema=50,
    rsi_threshold=55,
    use_volume_filter=True
):
    if df.empty:
        return {
            "final_signal": "NO TRADE",
            "vote_score": 0,
            "buy_votes": 0,
            "total_votes": 0,
            "confidence": 0,
            "reasons": "No data available",
            "strategy_votes": []
        }

    enriched_df = build_indicator_pipeline(
        df=df,
        short_ema=short_ema,
        long_ema=long_ema
    )

    strategy_votes = []
    buy_votes = 0
    total_votes = 0
    confidence_total = 0
    reasons = []

    for strategy_name, strategy_function in STRATEGY_REGISTRY.items():
        strategy_df = strategy_function(
            df=enriched_df.copy(),
            short_ema=short_ema,
            long_ema=long_ema,
            rsi_threshold=rsi_threshold,
            use_volume_filter=use_volume_filter
        )

        clean_df = strategy_df.dropna()

        if clean_df.empty:
            continue

        latest = clean_df.iloc[-1]

        signal_value = int(latest.get("Signal", 0))
        signal = "BUY" if signal_value == 1 else "NO TRADE"

        confidence = int(latest.get("Signal Confidence", 0))
        reason = latest.get("Signal Reason", "No reason available")

        total_votes += 1
        confidence_total += confidence

        if signal == "BUY":
            buy_votes += 1
            reasons.append(f"{strategy_name}: {reason}")

        strategy_votes.append({
            "Strategy": strategy_name,
            "Signal": signal,
            "Confidence": confidence,
            "Reason": reason
        })

    if total_votes == 0:
        return {
            "final_signal": "NO TRADE",
            "vote_score": 0,
            "buy_votes": 0,
            "total_votes": 0,
            "confidence": 0,
            "reasons": "No valid strategy votes",
            "strategy_votes": []
        }

    vote_score = (buy_votes / total_votes) * 100
    average_confidence = confidence_total / total_votes

    final_confidence = round(
        (vote_score * 0.6) + (average_confidence * 0.4),
        2
    )

    if buy_votes >= 2 and final_confidence >= 60:
        final_signal = "BUY"
    else:
        final_signal = "NO TRADE"

    if not reasons:
        reasons.append("No strategy consensus")

    return {
        "final_signal": final_signal,
        "vote_score": round(vote_score, 2),
        "buy_votes": buy_votes,
        "total_votes": total_votes,
        "confidence": final_confidence,
        "reasons": " | ".join(reasons),
        "strategy_votes": strategy_votes
    }