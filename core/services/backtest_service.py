import logging
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import numpy as np
import pandas as pd

from core.market_data.yahoo_data import download_price_data
from core.pipeline.models import ScanStrategyMode, TradingPipelineRequest
from core.pipeline.trading_pipeline import (
    InsufficientDataError,
    TradingPipeline,
    TradingPipelineError
)

VOTING_STRATEGY_LABEL = "Strategy Voting"

# Minimum number of bars downloaded market data must contain before a
# backtest can produce even one entry opportunity (one bar to decide on,
# one following bar to enter on). Per-bar indicator warm-up (e.g. a 50-day
# EMA) is handled separately, bar by bar, by treating TradingPipeline's
# InsufficientDataError as "no signal yet" rather than a hard failure.
MINIMUM_BACKTEST_BARS = 3

TRADING_DAYS_PER_YEAR = 252


class BacktestServiceError(Exception):
    """Base class for BacktestService-level failures."""


class InvalidBacktestRequestError(BacktestServiceError):
    """Raised when a BacktestRequest cannot be run as configured."""


class BacktestDataError(BacktestServiceError):
    """Raised when historical market data cannot be retrieved or is unusable."""


class BacktestSimulationError(BacktestServiceError):
    """Raised when the bar-by-bar simulation fails unexpectedly."""


@dataclass
class BacktestRequest:
    """User-facing backtest configuration. Mirrors the fields already
    exposed by the Backtesting page plus the decision parameters
    TradingPipeline requires (regime filter, risk/ATR/reward settings,
    minimum alpha score) and the transaction-cost settings needed to
    produce discrete BacktestTrade records."""

    symbol: str
    strategy_mode: ScanStrategyMode = ScanStrategyMode.SINGLE
    strategy_name: str = "EMA Trend"
    period: str = "2y"
    interval: str = "1d"
    initial_capital: float = 100000.0
    short_ema: int = 20
    long_ema: int = 50
    rsi_threshold: int = 55
    use_volume_filter: bool = True
    use_regime_filter: bool = True
    risk_percent: float = 1.0
    atr_multiplier: float = 2.0
    reward_risk_ratio: float = 2.0
    minimum_alpha_score: int = 70
    commission: float = 0.0
    slippage: float = 0.0

    def __post_init__(self):
        self.symbol = self.symbol.strip().upper() if self.symbol else ""

        if not isinstance(self.strategy_mode, ScanStrategyMode):
            self.strategy_mode = ScanStrategyMode(self.strategy_mode)


@dataclass
class BacktestTrade:
    symbol: str
    entry_timestamp: pd.Timestamp
    exit_timestamp: pd.Timestamp
    entry_price: float
    exit_price: float
    quantity: int
    side: str = "LONG"
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    gross_pnl: float = 0.0
    fees: float = 0.0
    net_pnl: float = 0.0
    exit_reason: str = ""
    strategy_mode: ScanStrategyMode = ScanStrategyMode.SINGLE
    strategy_name: str = ""
    signal_confidence: int = 0
    alpha_score: int = 0


@dataclass
class BacktestResult:
    request: BacktestRequest
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: pd.DataFrame = field(default_factory=pd.DataFrame)
    metrics: dict = field(default_factory=dict)
    benchmark_metrics: dict = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass
class _OpenPosition:
    entry_timestamp: pd.Timestamp
    entry_price: float
    quantity: int
    stop_loss: float
    take_profit: float
    strategy_name: str
    signal_confidence: int
    alpha_score: int
    entry_commission: float


class BacktestService:
    """Reusable, Streamlit-free historical backtesting workflow.

    Reuses TradingPipeline.evaluate() for every historical decision point
    (single-strategy and voting), exactly as ScannerService does, so
    indicators, strategy/voting, regime, alpha, and risk logic are
    implemented exactly once. BacktestService owns only backtest-specific
    orchestration: market-data retrieval, chronological anti-lookahead
    iteration, simulated entries/exits, cash/equity/position state,
    transaction costs, trade recording, and performance calculation.

    Execution convention (used because the pre-existing Backtesting page
    never defined stop-loss/take-profit/position-sizing behaviour):
      - A decision is made at bar t using only data through bar t
        (`data.loc[:t]`, i.e. no lookahead).
      - A BUY decision is entered at the next bar's Open.
      - Stop-loss/take-profit (as computed by TradingPipeline's existing
        ATR-based risk engine) are checked every bar from the entry bar
        onward using that bar's High/Low. If both are touched in the same
        bar, the stop-loss is assumed to trigger first (adverse-first).
      - Position sizing uses currently available cash (no leverage), and
        stop-loss/take-profit/suggested-share values are taken as-is from
        TradingPipeline's decision (computed relative to the signal bar's
        close) rather than recomputed relative to the actual next-bar-open
        fill price, since BacktestService must not duplicate risk formulas.
      - Only one long position per symbol at a time; no short selling.
      - Any position still open at the final bar is force-closed at the
        final available close.
    """

    def __init__(
        self,
        market_data_fn: Callable = download_price_data,
        pipeline: Optional[TradingPipeline] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._market_data_fn = market_data_fn
        self._pipeline = pipeline or TradingPipeline()
        self._logger = logger or logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, request: BacktestRequest) -> BacktestResult:
        self._validate_request(request)

        data = self._download_data(request)

        return self._simulate(request, data)

    # ------------------------------------------------------------------
    # Validation / data retrieval
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_request(request: BacktestRequest) -> None:
        if not request.symbol:
            raise InvalidBacktestRequestError("A symbol is required.")

        if request.initial_capital <= 0:
            raise InvalidBacktestRequestError(
                "initial_capital must be a positive number."
            )

        if request.short_ema <= 0 or request.long_ema <= 0:
            raise InvalidBacktestRequestError(
                "short_ema and long_ema must be positive integers."
            )

    def _download_data(self, request: BacktestRequest) -> pd.DataFrame:
        try:
            data = self._market_data_fn(
                symbol=request.symbol,
                period=request.period,
                interval=request.interval,
                auto_adjust=True
            )
        except Exception as exc:
            self._logger.exception(
                "Market data download failed for %s", request.symbol
            )
            raise BacktestDataError(
                f"Market data download failed for {request.symbol}."
            ) from exc

        if data is None or data.empty:
            raise BacktestDataError(
                f"No market data returned for {request.symbol}."
            )

        if len(data) < MINIMUM_BACKTEST_BARS:
            raise BacktestDataError(
                f"Insufficient historical data for {request.symbol}: "
                f"at least {MINIMUM_BACKTEST_BARS} bars are required."
            )

        return data

    # ------------------------------------------------------------------
    # Simulation
    # ------------------------------------------------------------------

    def _simulate(self, request: BacktestRequest, data: pd.DataFrame) -> BacktestResult:
        try:
            return self._run_simulation(request, data)
        except BacktestServiceError:
            raise
        except Exception as exc:
            self._logger.exception(
                "Backtest simulation failed unexpectedly for %s", request.symbol
            )
            raise BacktestSimulationError(
                f"Backtest simulation failed for {request.symbol}."
            ) from exc

    def _run_simulation(self, request: BacktestRequest, data: pd.DataFrame) -> BacktestResult:
        display_strategy = self._display_strategy_name(request)

        cash = float(request.initial_capital)
        position: Optional[_OpenPosition] = None
        pending_entry = None

        trades: List[BacktestTrade] = []
        equity_rows = []
        warnings: List[str] = []
        skipped_bars = 0

        n = len(data)

        for i in range(1, n):
            current_ts = data.index[i]
            bar = data.loc[current_ts]

            if pending_entry is not None and position is None:
                position = self._open_position(
                    request=request,
                    bar=bar,
                    entry_timestamp=current_ts,
                    decision=pending_entry,
                    cash=cash
                )
                if position is not None:
                    cash -= (
                        position.entry_price * position.quantity
                        + position.entry_commission
                    )
                pending_entry = None

            if position is not None:
                exit_price, exit_reason = self._check_stop_target(position, bar)

                if exit_price is not None:
                    trade, proceeds = self._close_position(
                        request=request,
                        position=position,
                        exit_price=exit_price,
                        exit_reason=exit_reason,
                        exit_timestamp=current_ts
                    )
                    trades.append(trade)
                    cash += proceeds
                    position = None

            if position is None and pending_entry is None and i < n - 1:
                historical_slice = data.iloc[: i + 1]

                try:
                    decision = self._pipeline.evaluate(
                        TradingPipelineRequest(
                            symbol=request.symbol,
                            data=historical_slice,
                            strategy_mode=request.strategy_mode,
                            strategy_name=request.strategy_name,
                            short_ema=request.short_ema,
                            long_ema=request.long_ema,
                            rsi_threshold=request.rsi_threshold,
                            use_volume_filter=request.use_volume_filter,
                            use_regime_filter=request.use_regime_filter,
                            account_balance=cash,
                            risk_percent=request.risk_percent,
                            atr_multiplier=request.atr_multiplier,
                            reward_risk_ratio=request.reward_risk_ratio,
                            minimum_alpha_score=request.minimum_alpha_score,
                        )
                    )
                except InsufficientDataError:
                    skipped_bars += 1
                    decision = None
                except TradingPipelineError as exc:
                    warnings.append(f"{current_ts}: {exc}")
                    decision = None

                if (
                    decision is not None
                    and decision.final_signal == "BUY"
                    and decision.suggested_shares > 0
                ):
                    pending_entry = decision

            mark_price = float(bar["Close"])
            equity = cash + (position.quantity * mark_price if position else 0.0)
            equity_rows.append({"Date": current_ts, "Equity": equity})

        if position is not None:
            final_ts = data.index[-1]
            final_close = float(data.iloc[-1]["Close"])

            trade, proceeds = self._close_position(
                request=request,
                position=position,
                exit_price=final_close,
                exit_reason="End of backtest period",
                exit_timestamp=final_ts
            )
            trades.append(trade)
            cash += proceeds

            if equity_rows:
                equity_rows[-1]["Equity"] = cash

        if skipped_bars:
            warnings.append(
                f"Skipped {skipped_bars} bar(s) with insufficient indicator "
                "history (strategy warm-up period)."
            )

        equity_curve = pd.DataFrame(equity_rows)

        metrics = self._build_metrics(
            equity_curve=equity_curve,
            trades=trades,
            initial_capital=request.initial_capital
        )

        benchmark_metrics = self._build_benchmark_metrics(
            data=data,
            initial_capital=request.initial_capital
        )

        return BacktestResult(
            request=request,
            trades=trades,
            equity_curve=equity_curve,
            metrics=metrics,
            benchmark_metrics=benchmark_metrics,
            warnings=warnings,
            errors=[]
        )

    @staticmethod
    def _display_strategy_name(request: BacktestRequest) -> str:
        if request.strategy_mode is ScanStrategyMode.VOTING:
            return VOTING_STRATEGY_LABEL
        return request.strategy_name

    def _open_position(
        self,
        request: BacktestRequest,
        bar: pd.Series,
        entry_timestamp: pd.Timestamp,
        decision,
        cash: float
    ) -> Optional[_OpenPosition]:
        entry_price = float(bar["Open"]) * (1 + request.slippage / 100)

        quantity = min(decision.suggested_shares, int(cash // entry_price) if entry_price > 0 else 0)

        if quantity <= 0:
            return None

        return _OpenPosition(
            entry_timestamp=entry_timestamp,
            entry_price=entry_price,
            quantity=quantity,
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
            strategy_name=self._display_strategy_name(request),
            signal_confidence=decision.confidence,
            alpha_score=decision.alpha_score,
            entry_commission=request.commission,
        )

    @staticmethod
    def _check_stop_target(position: _OpenPosition, bar: pd.Series):
        """Adverse-first same-bar collision assumption: if both the stop
        and the target are touched within the same bar's High/Low range,
        the stop-loss is assumed to have triggered first."""
        low = float(bar["Low"])
        high = float(bar["High"])

        stop_hit = position.stop_loss is not None and low <= position.stop_loss
        target_hit = position.take_profit is not None and high >= position.take_profit

        if stop_hit:
            return position.stop_loss, "STOP_LOSS"

        if target_hit:
            return position.take_profit, "TAKE_PROFIT"

        return None, None

    def _close_position(
        self,
        request: BacktestRequest,
        position: _OpenPosition,
        exit_price: float,
        exit_reason: str,
        exit_timestamp: pd.Timestamp
    ):
        adjusted_exit_price = exit_price * (1 - request.slippage / 100)

        gross_pnl = (adjusted_exit_price - position.entry_price) * position.quantity
        fees = position.entry_commission + request.commission
        net_pnl = gross_pnl - fees

        proceeds = adjusted_exit_price * position.quantity - request.commission

        trade = BacktestTrade(
            symbol=request.symbol,
            entry_timestamp=position.entry_timestamp,
            exit_timestamp=exit_timestamp,
            entry_price=round(position.entry_price, 2),
            exit_price=round(adjusted_exit_price, 2),
            quantity=position.quantity,
            side="LONG",
            stop_loss=position.stop_loss,
            take_profit=position.take_profit,
            gross_pnl=round(gross_pnl, 2),
            fees=round(fees, 2),
            net_pnl=round(net_pnl, 2),
            exit_reason=exit_reason,
            strategy_mode=request.strategy_mode,
            strategy_name=position.strategy_name,
            signal_confidence=position.signal_confidence,
            alpha_score=position.alpha_score,
        )

        return trade, proceeds

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def _build_metrics(
        self,
        equity_curve: pd.DataFrame,
        trades: List[BacktestTrade],
        initial_capital: float
    ) -> dict:
        if equity_curve.empty:
            final_equity = initial_capital
            equity_series = pd.Series([initial_capital], dtype=float)
        else:
            equity_series = equity_curve["Equity"].astype(float)
            final_equity = float(equity_series.iloc[-1])

        total_return_pct = (
            (final_equity - initial_capital) / initial_capital
        ) * 100

        daily_returns = equity_series.pct_change().dropna()

        annualised_return_pct = self._annualised_return(
            final_equity, initial_capital, len(equity_series)
        )
        volatility_pct = self._annualised_volatility(daily_returns)
        sharpe_ratio = self._sharpe_ratio(daily_returns)
        sortino_ratio = self._sortino_ratio(daily_returns)
        max_drawdown_pct = self._max_drawdown(equity_series)

        trade_stats = self._trade_statistics(trades)
        exposure_pct = self._exposure_percent(equity_curve, trades)

        return {
            "Initial Capital": round(initial_capital, 2),
            "Final Equity": round(final_equity, 2),
            "Total Return %": round(total_return_pct, 2),
            "Annualised Return %": round(annualised_return_pct, 2),
            "Volatility %": round(volatility_pct, 2),
            "Sharpe Ratio": round(sharpe_ratio, 2),
            "Sortino Ratio": round(sortino_ratio, 2),
            "Max Drawdown %": round(max_drawdown_pct, 2),
            "Win Rate %": round(trade_stats["win_rate"], 2),
            "Profit Factor": round(trade_stats["profit_factor"], 2),
            "Expectancy": round(trade_stats["expectancy"], 2),
            "Total Trades": trade_stats["total_trades"],
            "Average Win": round(trade_stats["average_win"], 2),
            "Average Loss": round(trade_stats["average_loss"], 2),
            "Exposure %": round(exposure_pct, 2),
            "Total Fees": round(trade_stats["total_fees"], 2),
        }

    def _build_benchmark_metrics(
        self,
        data: pd.DataFrame,
        initial_capital: float
    ) -> dict:
        first_close = float(data.iloc[0]["Close"])

        if first_close <= 0:
            return {}

        shares = initial_capital / first_close
        benchmark_equity = data["Close"].astype(float) * shares

        final_equity = float(benchmark_equity.iloc[-1])
        total_return_pct = (
            (final_equity - initial_capital) / initial_capital
        ) * 100
        max_drawdown_pct = self._max_drawdown(benchmark_equity)
        annualised_return_pct = self._annualised_return(
            final_equity, initial_capital, len(benchmark_equity)
        )

        return {
            "Final Equity": round(final_equity, 2),
            "Total Return %": round(total_return_pct, 2),
            "Annualised Return %": round(annualised_return_pct, 2),
            "Max Drawdown %": round(max_drawdown_pct, 2),
        }

    @staticmethod
    def _annualised_return(final_equity, initial_capital, total_bars) -> float:
        years = total_bars / TRADING_DAYS_PER_YEAR

        if years <= 0 or initial_capital <= 0:
            return 0.0

        base = final_equity / initial_capital

        if base <= 0:
            return -100.0

        return ((base ** (1 / years)) - 1) * 100

    @staticmethod
    def _annualised_volatility(daily_returns: pd.Series) -> float:
        if daily_returns.empty or daily_returns.std() == 0:
            return 0.0

        return daily_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR) * 100

    @staticmethod
    def _sharpe_ratio(daily_returns: pd.Series) -> float:
        if daily_returns.empty or daily_returns.std() == 0:
            return 0.0

        return (
            daily_returns.mean() / daily_returns.std()
        ) * np.sqrt(TRADING_DAYS_PER_YEAR)

    @staticmethod
    def _sortino_ratio(daily_returns: pd.Series) -> float:
        if daily_returns.empty:
            return 0.0

        downside_returns = daily_returns[daily_returns < 0]

        if downside_returns.empty or downside_returns.std() == 0:
            return 0.0

        return (
            daily_returns.mean() / downside_returns.std()
        ) * np.sqrt(TRADING_DAYS_PER_YEAR)

    @staticmethod
    def _max_drawdown(equity_series: pd.Series) -> float:
        if equity_series.empty:
            return 0.0

        running_max = equity_series.cummax()
        drawdown = (equity_series - running_max) / running_max

        return float(drawdown.min()) * 100

    @staticmethod
    def _trade_statistics(trades: List[BacktestTrade]) -> dict:
        total_trades = len(trades)

        if total_trades == 0:
            return {
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "expectancy": 0.0,
                "total_trades": 0,
                "average_win": 0.0,
                "average_loss": 0.0,
                "total_fees": 0.0,
            }

        net_pnls = [trade.net_pnl for trade in trades]
        winners = [pnl for pnl in net_pnls if pnl > 0]
        losers = [pnl for pnl in net_pnls if pnl <= 0]

        win_rate = (len(winners) / total_trades) * 100
        average_win = (sum(winners) / len(winners)) if winners else 0.0
        average_loss = (sum(losers) / len(losers)) if losers else 0.0

        gross_profit = sum(winners)
        gross_loss = abs(sum(losers))
        profit_factor = (gross_profit / gross_loss) if gross_loss != 0 else 0.0

        expectancy = sum(net_pnls) / total_trades
        total_fees = sum(trade.fees for trade in trades)

        return {
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "total_trades": total_trades,
            "average_win": average_win,
            "average_loss": average_loss,
            "total_fees": total_fees,
        }

    @staticmethod
    def _exposure_percent(equity_curve: pd.DataFrame, trades: List[BacktestTrade]) -> float:
        if equity_curve.empty:
            return 0.0

        total_bars = len(equity_curve)
        dates = equity_curve["Date"]

        bars_in_position = 0

        for trade in trades:
            bars_in_position += int(
                ((dates >= trade.entry_timestamp) & (dates <= trade.exit_timestamp)).sum()
            )

        return (bars_in_position / total_bars) * 100 if total_bars else 0.0
