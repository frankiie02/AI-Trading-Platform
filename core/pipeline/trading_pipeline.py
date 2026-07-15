import logging
from typing import Callable, Optional

import pandas as pd

from core.alpha.filters import should_queue_trade
from core.alpha.scoring import calculate_alpha_score, classify_alpha_grade
from core.indicators.pipeline import build_indicator_pipeline
from core.pipeline.models import (
    ScanStrategyMode,
    TradingDecision,
    TradingPipelineRequest,
)
from core.regime.detector import detect_market_regime
from core.regime.filters import strategy_allowed
from core.risk.risk_engine import (
    calculate_atr_stop_loss,
    calculate_position_size,
    calculate_take_profit
)
from core.strategy.strategy_engine import generate_strategy_signals
from core.voting.engine import run_strategy_voting


# A voting BUY is only regime-permitted when a strict majority of the
# strategies that voted BUY would individually be allowed to trade in the
# detected regime. This reuses the existing single-strategy regime rule
# (`strategy_allowed`) rather than inventing a new regime formula.
VOTING_MOMENTUM_CONSENSUS_VOTES = 2


class TradingPipelineError(Exception):
    """Base class for TradingPipeline evaluation failures."""


class InsufficientDataError(TradingPipelineError):
    """Raised when there isn't enough usable indicator history to decide."""


class InvalidStrategyConfigurationError(TradingPipelineError):
    """Raised when the requested strategy configuration cannot be evaluated."""


class PipelineEvaluationError(TradingPipelineError):
    """Raised when strategy/voting/regime/alpha/risk evaluation fails."""


class TradingPipeline:
    """Reusable market data -> indicators -> strategy/voting -> regime ->
    alpha -> risk -> decision workflow, shared by ScannerService and future
    BacktestService/PaperTradingService/LiveTradingService. Performs no
    market-data downloading, persistence, database access, broker
    submission, or Streamlit rendering."""

    def __init__(
        self,
        strategy_fn: Callable = generate_strategy_signals,
        voting_fn: Callable = run_strategy_voting,
        indicator_pipeline_fn: Callable = build_indicator_pipeline,
        regime_detector: Callable = detect_market_regime,
        regime_allowance_fn: Callable = strategy_allowed,
        alpha_score_fn: Callable = calculate_alpha_score,
        alpha_grade_fn: Callable = classify_alpha_grade,
        queue_eligibility_fn: Callable = should_queue_trade,
        stop_loss_fn: Callable = calculate_atr_stop_loss,
        take_profit_fn: Callable = calculate_take_profit,
        position_size_fn: Callable = calculate_position_size,
        logger: Optional[logging.Logger] = None,
    ):
        self._strategy_fn = strategy_fn
        self._voting_fn = voting_fn
        self._indicator_pipeline_fn = indicator_pipeline_fn
        self._regime_detector = regime_detector
        self._regime_allowance_fn = regime_allowance_fn
        self._alpha_score_fn = alpha_score_fn
        self._alpha_grade_fn = alpha_grade_fn
        self._queue_eligibility_fn = queue_eligibility_fn
        self._stop_loss_fn = stop_loss_fn
        self._take_profit_fn = take_profit_fn
        self._position_size_fn = position_size_fn
        self._logger = logger or logging.getLogger(__name__)

    def evaluate(self, request: TradingPipelineRequest) -> TradingDecision:
        if request.strategy_mode is ScanStrategyMode.VOTING:
            return self._evaluate_voting(request)
        return self._evaluate_single(request)

    # ------------------------------------------------------------------
    # Single-strategy path (unchanged behaviour)
    # ------------------------------------------------------------------

    def _evaluate_single(self, request: TradingPipelineRequest) -> TradingDecision:
        try:
            data = self._strategy_fn(
                df=request.data,
                strategy_name=request.strategy_name,
                short_ema=request.short_ema,
                long_ema=request.long_ema,
                rsi_threshold=request.rsi_threshold,
                use_volume_filter=request.use_volume_filter
            )
        except Exception as exc:
            self._logger.exception(
                "Strategy signal generation failed for %s", request.symbol
            )
            raise PipelineEvaluationError(
                "Strategy signal generation failed."
            ) from exc

        clean_data = data.dropna()

        if clean_data.empty:
            raise InsufficientDataError("Not enough indicator history")

        try:
            market_regime = self._regime_detector(clean_data)
            is_strategy_allowed = self._regime_allowance_fn(
                request.strategy_name, market_regime
            )
            regime_reason = self._single_regime_reason(
                request.strategy_name, market_regime, is_strategy_allowed
            )

            latest = clean_data.iloc[-1]
            raw_signal = "BUY" if latest["Signal"] == 1 else "NO TRADE"
            confidence = int(latest.get("Signal Confidence", 0))
            reason = latest.get("Signal Reason", "No reason available")

            return self._build_decision(
                symbol=request.symbol,
                request=request,
                clean_data=clean_data,
                alpha_input=latest,
                raw_signal=raw_signal,
                confidence=confidence,
                reason=reason,
                is_strategy_allowed=is_strategy_allowed,
                regime_reason=regime_reason,
                market_regime=market_regime,
            )
        except Exception as exc:
            self._logger.exception(
                "Unexpected error while evaluating %s", request.symbol
            )
            raise PipelineEvaluationError(
                "Unexpected error during scan."
            ) from exc

    @staticmethod
    def _single_regime_reason(strategy_name, market_regime, is_allowed) -> str:
        if is_allowed:
            return (
                f"{strategy_name} is allowed in {market_regime.value} market."
            )
        return f"{strategy_name} is blocked in {market_regime.value} market."

    # ------------------------------------------------------------------
    # Voting path
    # ------------------------------------------------------------------

    def _evaluate_voting(self, request: TradingPipelineRequest) -> TradingDecision:
        try:
            enriched = self._indicator_pipeline_fn(
                df=request.data,
                short_ema=request.short_ema,
                long_ema=request.long_ema
            )
        except Exception as exc:
            self._logger.exception(
                "Indicator enrichment failed for %s", request.symbol
            )
            raise PipelineEvaluationError(
                "Indicator enrichment failed."
            ) from exc

        clean_data = enriched.dropna()

        if clean_data.empty:
            raise InsufficientDataError("Not enough indicator history")

        try:
            vote_result = self._voting_fn(
                df=request.data,
                short_ema=request.short_ema,
                long_ema=request.long_ema,
                rsi_threshold=request.rsi_threshold,
                use_volume_filter=request.use_volume_filter
            )
        except Exception as exc:
            self._logger.exception(
                "Strategy voting failed for %s", request.symbol
            )
            raise PipelineEvaluationError("Strategy voting failed.") from exc

        try:
            market_regime = self._regime_detector(clean_data)

            strategy_votes = vote_result.get("strategy_votes", [])
            buy_voting_strategy_names = [
                vote["Strategy"]
                for vote in strategy_votes
                if vote.get("Signal") == "BUY"
            ]

            is_strategy_allowed = self._voting_regime_allowed(
                buy_voting_strategy_names, market_regime
            )
            regime_reason = self._voting_regime_reason(
                buy_voting_strategy_names, market_regime, is_strategy_allowed
            )

            latest = clean_data.iloc[-1]
            buy_votes = vote_result.get("buy_votes", 0)
            alpha_input = self._build_voting_alpha_input(
                latest, request, buy_votes
            )

            raw_signal = vote_result.get("final_signal", "NO TRADE")
            confidence = int(round(vote_result.get("confidence", 0)))
            reason = vote_result.get("reasons", "No strategy consensus")

            decision = self._build_decision(
                symbol=request.symbol,
                request=request,
                clean_data=clean_data,
                alpha_input=alpha_input,
                raw_signal=raw_signal,
                confidence=confidence,
                reason=reason,
                is_strategy_allowed=is_strategy_allowed,
                regime_reason=regime_reason,
                market_regime=market_regime,
            )

            decision.vote_score = vote_result.get("vote_score", 0)
            decision.buy_votes = buy_votes
            decision.total_votes = vote_result.get("total_votes", 0)
            decision.strategy_votes = strategy_votes

            return decision
        except Exception as exc:
            self._logger.exception(
                "Unexpected error while evaluating %s", request.symbol
            )
            raise PipelineEvaluationError(
                "Unexpected error during scan."
            ) from exc

    def _voting_regime_allowed(self, buy_voting_strategy_names, market_regime) -> bool:
        """A voting BUY is regime-permitted only when a strict majority of
        the strategies that voted BUY are individually allowed to trade in
        the detected regime (existing `strategy_allowed` rule, unchanged)."""
        if not buy_voting_strategy_names:
            return False

        allowed_count = sum(
            1
            for name in buy_voting_strategy_names
            if self._regime_allowance_fn(name, market_regime)
        )

        return allowed_count > len(buy_voting_strategy_names) / 2

    @staticmethod
    def _voting_regime_reason(buy_voting_strategy_names, market_regime, is_allowed) -> str:
        if not buy_voting_strategy_names:
            return f"No strategies voted BUY in {market_regime.value} market."

        names = ", ".join(buy_voting_strategy_names)

        if is_allowed:
            return (
                f"Majority of BUY-voting strategies ({names}) are allowed "
                f"in {market_regime.value} market."
            )
        return (
            f"Majority of BUY-voting strategies ({names}) are blocked "
            f"in {market_regime.value} market."
        )

    @staticmethod
    def _build_voting_alpha_input(latest, request: TradingPipelineRequest, buy_votes: int) -> dict:
        """Assembles the row alpha scoring needs from indicator-pipeline
        output. Uses the same primitives every registered strategy already
        applies (Short EMA/Long EMA crossover, Volume vs Volume Average) so
        no new trend/volume rule is introduced. Momentum is approximated by
        the voting engine's own consensus gate (>=2 BUY votes), since there
        is no single shared momentum formula across strategies."""
        alpha_input = latest.to_dict()

        alpha_input["Trend Filter"] = bool(latest["Short EMA"] > latest["Long EMA"])
        alpha_input["Momentum Filter"] = buy_votes >= VOTING_MOMENTUM_CONSENSUS_VOTES

        if request.use_volume_filter:
            alpha_input["Volume Filter"] = bool(
                latest["Volume"] > latest["Volume Average"]
            )
        else:
            alpha_input["Volume Filter"] = True

        return alpha_input

    # ------------------------------------------------------------------
    # Shared decision assembly (regime/alpha/risk/queue-eligibility)
    # ------------------------------------------------------------------

    def _build_decision(
        self,
        symbol: str,
        request: TradingPipelineRequest,
        clean_data: pd.DataFrame,
        alpha_input,
        raw_signal: str,
        confidence: int,
        reason: str,
        is_strategy_allowed: bool,
        regime_reason: str,
        market_regime,
    ) -> TradingDecision:
        latest = clean_data.iloc[-1]

        price = float(latest["Close"])
        atr = float(latest["ATR"])

        stop_loss = self._stop_loss_fn(
            entry_price=price,
            atr=atr,
            atr_multiplier=request.atr_multiplier
        )

        take_profit = self._take_profit_fn(
            entry_price=price,
            stop_loss_price=stop_loss,
            reward_risk_ratio=request.reward_risk_ratio
        )

        shares, risk_amount = self._position_size_fn(
            account_balance=request.account_balance,
            entry_price=price,
            stop_loss_price=stop_loss,
            risk_percent=request.risk_percent
        )

        alpha_score, alpha_reasons = self._alpha_score_fn(alpha_input)
        alpha_grade = self._alpha_grade_fn(alpha_score)

        queue_allowed_by_alpha = self._queue_eligibility_fn(
            signal=raw_signal,
            alpha_score=alpha_score,
            minimum_score=request.minimum_alpha_score
        )

        if request.use_regime_filter:
            final_signal = (
                "BUY"
                if queue_allowed_by_alpha and is_strategy_allowed
                else "NO TRADE"
            )
        else:
            final_signal = "BUY" if queue_allowed_by_alpha else "NO TRADE"

        return TradingDecision(
            symbol=symbol,
            status="OK",
            strategy_mode=request.strategy_mode,
            strategy_name=request.strategy_name,
            raw_signal=raw_signal,
            final_signal=final_signal,
            confidence=confidence,
            signal_reason=reason,
            regime=market_regime.value,
            strategy_allowed=is_strategy_allowed,
            regime_reason=regime_reason,
            alpha_score=alpha_score,
            alpha_grade=alpha_grade,
            alpha_reasons=alpha_reasons,
            current_price=round(price, 2),
            rsi=round(float(latest["RSI"]), 2),
            atr=round(atr, 2),
            trend=bool(alpha_input.get("Trend Filter", False)),
            momentum=bool(alpha_input.get("Momentum Filter", False)),
            volume=bool(alpha_input.get("Volume Filter", False)),
            stop_loss=round(stop_loss, 2),
            take_profit=round(take_profit, 2),
            suggested_shares=shares,
            dollar_risk=round(risk_amount, 2),
            queue_eligible=(final_signal == "BUY")
        )
