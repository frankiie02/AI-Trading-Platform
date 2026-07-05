def calculate_alpha_score(row):
    score = 0
    reasons = []

    if row.get("Trend Filter", False):
        score += 20
        reasons.append("Trend bullish")

    if row.get("Momentum Filter", False):
        score += 20
        reasons.append("Momentum confirmed")

    if row.get("Volume Filter", False):
        score += 15
        reasons.append("Volume confirmed")

    rsi = row.get("RSI", None)

    if rsi is not None:
        if 50 <= rsi <= 70:
            score += 15
            reasons.append("RSI healthy")
        elif 45 <= rsi < 50:
            score += 8
            reasons.append("RSI recovering")
        elif rsi > 70:
            score += 5
            reasons.append("RSI extended")

    atr = row.get("ATR", None)
    close = row.get("Close", None)

    if atr is not None and close is not None and close > 0:
        atr_percent = (atr / close) * 100

        if 1 <= atr_percent <= 5:
            score += 15
            reasons.append("Volatility acceptable")
        elif atr_percent < 1:
            score += 7
            reasons.append("Low volatility")
        else:
            score += 3
            reasons.append("High volatility")

    macd = row.get("MACD", None)
    macd_signal = row.get("MACD Signal", None)
    macd_histogram = row.get("MACD Histogram", None)

    if (
        macd is not None
        and macd_signal is not None
        and macd_histogram is not None
    ):
        if macd > macd_signal and macd_histogram > 0:
            score += 15
            reasons.append("MACD bullish")

    score = min(score, 100)

    if not reasons:
        reasons.append("No strong alpha factors")

    return score, ", ".join(reasons)


def classify_alpha_grade(score):
    if score >= 90:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B+"
    if score >= 60:
        return "B"
    if score >= 50:
        return "C"
    return "D"