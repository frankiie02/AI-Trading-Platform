import logging
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import pandas as pd

from config.settings import settings
from core.alpha.ranking import rank_opportunities
from core.execution.trade_queue import save_buy_signals_to_queue
from core.market_data.yahoo_data import download_price_data
from core.pipeline.models import ScanStrategyMode, TradingPipelineRequest
from core.pipeline.trading_pipeline import (
    InsufficientDataError,
    TradingPipeline,
    TradingPipelineError
)
from core.scanner.scanner_repository import save_scanner_results


VOTING_STRATEGY_LABEL = "Strategy Voting"


class ScannerServiceError(Exception):
    """Base class for ScannerService-level failures."""


class ScannerPersistenceError(ScannerServiceError):
    """Raised when scanner results cannot be persisted."""


class TradeQueuePersistenceError(ScannerServiceError):
    """Raised when eligible trades cannot be saved to the trade queue."""


@dataclass
class ScanRequest:
    symbols: List[str]
    strategy_name: str = "EMA Trend"
    strategy_mode: ScanStrategyMode = ScanStrategyMode.SINGLE
    period: str = "1y"
    interval: str = "1d"
    short_ema: int = 20
    long_ema: int = 50
    rsi_threshold: int = 55
    use_volume_filter: bool = True
    use_regime_filter: bool = True
    risk_percent: float = 1.0
    atr_multiplier: float = 2.0
    reward_risk_ratio: float = 2.0
    minimum_alpha_score: int = 70
    queue_trades: bool = True

    def __post_init__(self):
        self.symbols = self._normalise_symbols(self.symbols)

        if not isinstance(self.strategy_mode, ScanStrategyMode):
            self.strategy_mode = ScanStrategyMode(self.strategy_mode)

    @staticmethod
    def _normalise_symbols(symbols) -> List[str]:
        normalised = []
        seen = set()

        for raw_symbol in symbols:
            symbol = raw_symbol.strip().upper()

            if not symbol or symbol in seen:
                continue

            seen.add(symbol)
            normalised.append(symbol)

        return normalised


@dataclass
class SymbolScanOutcome:
    symbol: str
    status: str
    strategy: str
    price: Optional[float] = None
    raw_signal: str = "NO TRADE"
    final_signal: str = "NO TRADE"
    confidence: int = 0
    signal_reason: str = ""
    regime: str = "Unknown"
    regime_reason: str = ""
    alpha_score: int = 0
    alpha_grade: str = "D"
    alpha_reasons: str = ""
    rsi: Optional[float] = None
    atr: Optional[float] = None
    trend_pass: bool = False
    momentum_pass: bool = False
    volume_pass: bool = False
    regime_allows_strategy: bool = False
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    suggested_shares: int = 0
    dollar_risk: float = 0.0
    queue_eligible: bool = False
    error_reason: Optional[str] = None
    # Voting-mode-only metadata. Left as None for single-strategy outcomes
    # rather than forced to a meaningless default (e.g. zero).
    vote_score: Optional[float] = None
    buy_votes: Optional[int] = None
    total_votes: Optional[int] = None
    strategy_votes: Optional[List[dict]] = None

    def to_legacy_dict(self) -> dict:
        """Reproduces the exact dict shape consumed by save_scanner_results,
        save_buy_signals_to_queue, rank_opportunities and the Streamlit table.

        Voting metadata is appended only for voting outcomes, and only as
        extra keys: save_scanner_results/save_buy_signals_to_queue read
        known keys via dict.get(...), so unknown extra keys are ignored and
        are not persisted to the (unchanged) database schema. Voting
        metadata therefore only ever lives in memory / the ranked table.
        """
        legacy = {
            "Symbol": self.symbol,
            "Strategy": self.strategy,
            "Status": self.status,
            "Signal": self.final_signal,
            "Confidence": self.confidence,
            "Alpha Score": self.alpha_score,
            "Alpha Grade": self.alpha_grade,
            "Reason": self.signal_reason,
            "Alpha Reasons": self.alpha_reasons,
            "Market Regime": self.regime,
            "Strategy Allowed": "YES" if self.regime_allows_strategy else "NO",
            "Regime Reason": self.regime_reason,
            "Price": self.price,
            "RSI": self.rsi,
            "ATR": self.atr,
            "Trend": "PASS" if self.trend_pass else "FAIL",
            "Momentum": "PASS" if self.momentum_pass else "FAIL",
            "Volume": "PASS" if self.volume_pass else "FAIL",
            "Suggested Shares": self.suggested_shares,
            "Stop Loss": self.stop_loss,
            "Take Profit": self.take_profit,
            "Dollar Risk": self.dollar_risk
        }

        if self.strategy_votes is not None:
            legacy["Vote Score"] = self.vote_score
            legacy["BUY Votes"] = self.buy_votes
            legacy["Total Votes"] = self.total_votes

        return legacy


@dataclass
class ScanStatistics:
    symbols_requested: int = 0
    symbols_processed: int = 0
    successful_symbols: int = 0
    failed_symbols: int = 0
    buy_signals: int = 0
    no_trade_signals: int = 0
    queued_trades: int = 0
    elapsed_seconds: float = 0.0


@dataclass
class ScanResult:
    outcomes: List[SymbolScanOutcome] = field(default_factory=list)
    legacy_results: List[dict] = field(default_factory=list)
    ranked: pd.DataFrame = field(default_factory=pd.DataFrame)
    queued_count: int = 0
    statistics: ScanStatistics = field(default_factory=ScanStatistics)


class ScannerService:
    def __init__(
        self,
        market_data_fn: Callable = download_price_data,
        pipeline: Optional[TradingPipeline] = None,
        save_results_fn: Callable = save_scanner_results,
        save_queue_fn: Callable = save_buy_signals_to_queue,
        ranking_fn: Callable = rank_opportunities,
        account_balance: Optional[float] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._market_data_fn = market_data_fn
        self._pipeline = pipeline or TradingPipeline()
        self._save_results_fn = save_results_fn
        self._save_queue_fn = save_queue_fn
        self._ranking_fn = ranking_fn
        self._account_balance = (
            account_balance
            if account_balance is not None
            else settings.STARTING_BALANCE
        )
        self._logger = logger or logging.getLogger(__name__)

    def scan(
        self,
        request: ScanRequest,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> ScanResult:
        start_time = time.monotonic()

        outcomes = []
        total = len(request.symbols)

        for index, symbol in enumerate(request.symbols):
            outcome = self._scan_symbol(symbol, request)
            outcomes.append(outcome)

            if progress_callback is not None:
                try:
                    progress_callback(index + 1, total, symbol)
                except Exception:
                    self._logger.exception(
                        "Progress callback failed for symbol %s", symbol
                    )

        legacy_results = [outcome.to_legacy_dict() for outcome in outcomes]

        try:
            self._save_results_fn(legacy_results)
        except Exception as exc:
            self._logger.exception("Failed to persist scanner results.")
            raise ScannerPersistenceError(
                "Failed to persist scanner results."
            ) from exc

        queued_count = 0

        if request.queue_trades:
            try:
                queued_count = self._save_queue_fn(legacy_results)
            except Exception as exc:
                self._logger.exception(
                    "Failed to save eligible trades to the trade queue."
                )
                raise TradeQueuePersistenceError(
                    "Failed to save eligible trades to the trade queue."
                ) from exc

        ranked = self._ranking_fn(legacy_results)

        statistics = self._build_statistics(
            request=request,
            outcomes=outcomes,
            queued_count=queued_count,
            elapsed_seconds=time.monotonic() - start_time
        )

        return ScanResult(
            outcomes=outcomes,
            legacy_results=legacy_results,
            ranked=ranked,
            queued_count=queued_count,
            statistics=statistics
        )

    # ------------------------------------------------------------------
    # Symbol dispatch
    # ------------------------------------------------------------------

    def _scan_symbol(
        self,
        symbol: str,
        request: ScanRequest
    ) -> SymbolScanOutcome:
        display_strategy = self._display_strategy_name(request)

        try:
            data = self._market_data_fn(
                symbol=symbol,
                period=request.period,
                interval=request.interval,
                auto_adjust=True
            )
        except Exception:
            self._logger.exception(
                "Market data download failed for %s", symbol
            )
            return self._error_outcome(
                symbol=symbol,
                strategy=display_strategy,
                signal_label="SCAN ERROR",
                reason="Market data download failed."
            )

        if data.empty:
            return self._error_outcome(
                symbol=symbol,
                strategy=display_strategy,
                signal_label="NO DATA",
                reason="No data returned",
                regime_reason="No data available"
            )

        pipeline_request = TradingPipelineRequest(
            symbol=symbol,
            data=data,
            strategy_mode=request.strategy_mode,
            strategy_name=request.strategy_name,
            short_ema=request.short_ema,
            long_ema=request.long_ema,
            rsi_threshold=request.rsi_threshold,
            use_volume_filter=request.use_volume_filter,
            use_regime_filter=request.use_regime_filter,
            account_balance=self._account_balance,
            risk_percent=request.risk_percent,
            atr_multiplier=request.atr_multiplier,
            reward_risk_ratio=request.reward_risk_ratio,
            minimum_alpha_score=request.minimum_alpha_score,
        )

        try:
            decision = self._pipeline.evaluate(pipeline_request)
        except InsufficientDataError as exc:
            return self._error_outcome(
                symbol=symbol,
                strategy=display_strategy,
                signal_label="NOT ENOUGH DATA",
                reason=str(exc)
            )
        except TradingPipelineError as exc:
            return self._error_outcome(
                symbol=symbol,
                strategy=display_strategy,
                signal_label="SCAN ERROR",
                reason=str(exc)
            )

        return self._outcome_from_decision(symbol, display_strategy, decision)

    @staticmethod
    def _display_strategy_name(request: ScanRequest) -> str:
        if request.strategy_mode is ScanStrategyMode.VOTING:
            return VOTING_STRATEGY_LABEL
        return request.strategy_name

    @staticmethod
    def _outcome_from_decision(
        symbol: str,
        display_strategy: str,
        decision
    ) -> SymbolScanOutcome:
        return SymbolScanOutcome(
            symbol=symbol,
            status="OK",
            strategy=display_strategy,
            price=decision.current_price,
            raw_signal=decision.raw_signal,
            final_signal=decision.final_signal,
            confidence=decision.confidence,
            signal_reason=decision.signal_reason,
            regime=decision.regime,
            regime_reason=decision.regime_reason,
            alpha_score=decision.alpha_score,
            alpha_grade=decision.alpha_grade,
            alpha_reasons=decision.alpha_reasons,
            rsi=decision.rsi,
            atr=decision.atr,
            trend_pass=decision.trend,
            momentum_pass=decision.momentum,
            volume_pass=decision.volume,
            regime_allows_strategy=decision.strategy_allowed,
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
            suggested_shares=decision.suggested_shares,
            dollar_risk=decision.dollar_risk,
            queue_eligible=decision.queue_eligible,
            vote_score=decision.vote_score,
            buy_votes=decision.buy_votes,
            total_votes=decision.total_votes,
            strategy_votes=decision.strategy_votes,
        )

    def _error_outcome(
        self,
        symbol: str,
        strategy: str,
        signal_label: str,
        reason: str,
        regime_reason: Optional[str] = None
    ) -> SymbolScanOutcome:
        return SymbolScanOutcome(
            symbol=symbol,
            status="ERROR",
            strategy=strategy,
            final_signal=signal_label,
            raw_signal=signal_label,
            confidence=0,
            signal_reason=reason,
            regime="Unknown",
            regime_reason=regime_reason if regime_reason is not None else reason,
            alpha_score=0,
            alpha_grade="D",
            alpha_reasons=reason,
            error_reason=reason
        )

    def _build_statistics(
        self,
        request: ScanRequest,
        outcomes: List[SymbolScanOutcome],
        queued_count: int,
        elapsed_seconds: float
    ) -> ScanStatistics:
        successful = [o for o in outcomes if o.status == "OK"]
        failed = [o for o in outcomes if o.status == "ERROR"]
        buy_signals = [o for o in outcomes if o.final_signal == "BUY"]
        no_trade_signals = [o for o in outcomes if o.final_signal == "NO TRADE"]

        return ScanStatistics(
            symbols_requested=len(request.symbols),
            symbols_processed=len(outcomes),
            successful_symbols=len(successful),
            failed_symbols=len(failed),
            buy_signals=len(buy_signals),
            no_trade_signals=len(no_trade_signals),
            queued_trades=queued_count,
            elapsed_seconds=elapsed_seconds
        )
