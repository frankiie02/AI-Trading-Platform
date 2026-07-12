import logging
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import pandas as pd

from config.settings import settings
from core.alpha.filters import should_queue_trade
from core.alpha.ranking import rank_opportunities
from core.alpha.scoring import calculate_alpha_score, classify_alpha_grade
from core.execution.trade_queue import save_buy_signals_to_queue
from core.market_data.yahoo_data import download_price_data
from core.regime.detector import detect_market_regime
from core.regime.filters import strategy_allowed
from core.risk.risk_engine import (
    calculate_atr_stop_loss,
    calculate_position_size,
    calculate_take_profit
)
from core.scanner.scanner_repository import save_scanner_results
from core.strategy.strategy_engine import generate_strategy_signals


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

    def to_legacy_dict(self) -> dict:
        """Reproduces the exact dict shape consumed by save_scanner_results,
        save_buy_signals_to_queue, rank_opportunities and the Streamlit table."""
        return {
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
        strategy_fn: Callable = generate_strategy_signals,
        regime_detector: Callable = detect_market_regime,
        regime_allowance_fn: Callable = strategy_allowed,
        alpha_score_fn: Callable = calculate_alpha_score,
        alpha_grade_fn: Callable = classify_alpha_grade,
        queue_eligibility_fn: Callable = should_queue_trade,
        stop_loss_fn: Callable = calculate_atr_stop_loss,
        take_profit_fn: Callable = calculate_take_profit,
        position_size_fn: Callable = calculate_position_size,
        save_results_fn: Callable = save_scanner_results,
        save_queue_fn: Callable = save_buy_signals_to_queue,
        ranking_fn: Callable = rank_opportunities,
        account_balance: Optional[float] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._market_data_fn = market_data_fn
        self._strategy_fn = strategy_fn
        self._regime_detector = regime_detector
        self._regime_allowance_fn = regime_allowance_fn
        self._alpha_score_fn = alpha_score_fn
        self._alpha_grade_fn = alpha_grade_fn
        self._queue_eligibility_fn = queue_eligibility_fn
        self._stop_loss_fn = stop_loss_fn
        self._take_profit_fn = take_profit_fn
        self._position_size_fn = position_size_fn
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

    def _scan_symbol(
        self,
        symbol: str,
        request: ScanRequest
    ) -> SymbolScanOutcome:
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
                strategy=request.strategy_name,
                signal_label="SCAN ERROR",
                reason="Market data download failed."
            )

        if data.empty:
            return self._error_outcome(
                symbol=symbol,
                strategy=request.strategy_name,
                signal_label="NO DATA",
                reason="No data returned",
                regime_reason="No data available"
            )

        try:
            data = self._strategy_fn(
                df=data,
                strategy_name=request.strategy_name,
                short_ema=request.short_ema,
                long_ema=request.long_ema,
                rsi_threshold=request.rsi_threshold,
                use_volume_filter=request.use_volume_filter
            )
        except Exception:
            self._logger.exception(
                "Strategy signal generation failed for %s", symbol
            )
            return self._error_outcome(
                symbol=symbol,
                strategy=request.strategy_name,
                signal_label="SCAN ERROR",
                reason="Strategy signal generation failed."
            )

        clean_data = data.dropna()

        if clean_data.empty:
            return self._error_outcome(
                symbol=symbol,
                strategy=request.strategy_name,
                signal_label="NOT ENOUGH DATA",
                reason="Not enough indicator history"
            )

        try:
            return self._build_success_outcome(symbol, clean_data, request)
        except Exception:
            self._logger.exception(
                "Unexpected error while scanning %s", symbol
            )
            return self._error_outcome(
                symbol=symbol,
                strategy=request.strategy_name,
                signal_label="SCAN ERROR",
                reason="Unexpected error during scan."
            )

    def _build_success_outcome(
        self,
        symbol: str,
        clean_data: pd.DataFrame,
        request: ScanRequest
    ) -> SymbolScanOutcome:
        market_regime = self._regime_detector(clean_data)
        is_strategy_allowed = self._regime_allowance_fn(
            request.strategy_name, market_regime
        )

        if is_strategy_allowed:
            regime_reason = (
                f"{request.strategy_name} is allowed in "
                f"{market_regime.value} market."
            )
        else:
            regime_reason = (
                f"{request.strategy_name} is blocked in "
                f"{market_regime.value} market."
            )

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
            account_balance=self._account_balance,
            entry_price=price,
            stop_loss_price=stop_loss,
            risk_percent=request.risk_percent
        )

        raw_signal = "BUY" if latest["Signal"] == 1 else "NO TRADE"
        confidence = int(latest.get("Signal Confidence", 0))
        reason = latest.get("Signal Reason", "No reason available")

        alpha_score, alpha_reasons = self._alpha_score_fn(latest)
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

        return SymbolScanOutcome(
            symbol=symbol,
            status="OK",
            strategy=request.strategy_name,
            price=round(price, 2),
            raw_signal=raw_signal,
            final_signal=final_signal,
            confidence=confidence,
            signal_reason=reason,
            regime=market_regime.value,
            regime_reason=regime_reason,
            alpha_score=alpha_score,
            alpha_grade=alpha_grade,
            alpha_reasons=alpha_reasons,
            rsi=round(float(latest["RSI"]), 2),
            atr=round(atr, 2),
            trend_pass=bool(latest["Trend Filter"]),
            momentum_pass=bool(latest["Momentum Filter"]),
            volume_pass=bool(latest["Volume Filter"]),
            regime_allows_strategy=is_strategy_allowed,
            stop_loss=round(stop_loss, 2),
            take_profit=round(take_profit, 2),
            suggested_shares=shares,
            dollar_risk=round(risk_amount, 2),
            queue_eligible=(final_signal == "BUY")
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
