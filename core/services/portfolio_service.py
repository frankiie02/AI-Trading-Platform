"""Reusable, read-only portfolio analytics workflow.

PortfolioService is the authoritative read/analytics layer for portfolio
state: valuation, exposure, allocation, performance, drawdown, completed-
trade statistics, snapshots, and reconciliation reporting. It never
creates, fills, or cancels an order, never mutates cash or position
quantities, and never submits a broker order - every state-changing paper-
trading action remains in PaperTradingService
(core/services/paper_trading_service.py).

PortfolioService reads directly from the same repository-level functions
PaperTradingService already uses
(core/execution/paper_orders_repository.py) rather than wrapping
PaperTradingService's own typed models, so it can expose richer analytics
fields (cost basis, portfolio weight, exposure, performance) without
PaperTradingService needing to grow them. The one exception is
reconciliation: PortfolioService surfaces, rather than duplicates,
PaperTradingService.reconcile() through an injected collaborator.

Portfolio equations (all division-by-zero-guarded via _safe_pct):

    cost_basis      = quantity x average_entry_price
    market_value    = quantity x current_price
    unrealised_pnl  = market_value - cost_basis
    equity          = cash + sum(market_value of open positions)
    total_pnl       = realised_pnl + unrealised_pnl
    total_return_pct  = total_pnl / starting_capital x 100
    gross_exposure_pct = sum(abs(market_value)) / equity x 100
    net_exposure_pct   = sum(signed market_value) / equity x 100
    position_weight_pct = position market_value / equity x 100

unrealised_pnl is never added into equity a second time - equity is
computed once, from cash + market_value only.

Performance metrics that need multiple time periods (volatility, Sharpe,
Sortino, drawdown) are built from portfolio_snapshots, which only grow via
an explicit create_snapshot() call - never written invisibly on a read.
Because snapshots are user/runtime-triggered rather than fixed daily bars
(unlike BacktestService's bar-by-bar equity curve), these statistics are
deliberately computed as unannualised, per-snapshot-period figures rather
than forcing BacktestService's 252-trading-day assumption onto them. When
fewer than two snapshots exist, those fields are None with a warning
rather than a fabricated number.
"""
import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from core.database.database import DB_PATH
from core.execution.paper_orders_repository import (
    get_account_row,
    get_all_position_rows,
    get_trade_rows,
)
from core.portfolio.portfolio_repository import get_snapshot_rows, insert_snapshot
from core.services.paper_trading_service import PaperTradingService, ReconciliationResult

_MIN_SNAPSHOTS_FOR_RETURNS = 2


# ----------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------

class PortfolioServiceError(Exception):
    """Base class for PortfolioService-level failures."""


class PortfolioDataError(PortfolioServiceError):
    """Raised when portfolio state cannot be read."""


class SnapshotPersistenceError(PortfolioServiceError):
    """Raised when a portfolio snapshot cannot be created or read."""


# ----------------------------------------------------------------------
# Typed models
# ----------------------------------------------------------------------

@dataclass
class PortfolioPosition:
    symbol: str
    quantity: int
    average_entry_price: float
    current_price: float
    cost_basis: float
    market_value: float
    unrealised_pnl: float
    unrealised_return_pct: Optional[float]
    realised_pnl: float
    portfolio_weight_pct: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    opened_at: Optional[str]
    strategy_name: Optional[str] = None
    strategy_mode: Optional[str] = None


@dataclass
class PortfolioSummary:
    starting_capital: float
    cash: float
    reserved_cash: float
    invested_capital: float
    market_value: float
    equity: float
    realised_pnl: float
    unrealised_pnl: float
    total_pnl: float
    total_return_pct: Optional[float]
    gross_exposure_pct: Optional[float]
    net_exposure_pct: Optional[float]
    cash_pct: Optional[float]
    position_count: int
    largest_position_pct: Optional[float]
    average_position_value: Optional[float]


@dataclass
class PortfolioPerformance:
    equity_curve: List[dict] = field(default_factory=list)
    returns: List[float] = field(default_factory=list)
    peak_equity: Optional[float] = None
    current_drawdown_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    volatility_pct: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    total_completed_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate_pct: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0
    average_win: float = 0.0
    average_loss: float = 0.0
    expectancy: float = 0.0
    total_fees: float = 0.0


@dataclass
class PortfolioSnapshot:
    snapshot_id: int
    timestamp: str
    cash: float
    market_value: float
    equity: float
    realised_pnl: float
    unrealised_pnl: float
    gross_exposure_pct: float
    position_count: int


@dataclass
class PortfolioAnalysis:
    summary: PortfolioSummary
    positions: List[PortfolioPosition] = field(default_factory=list)
    performance: PortfolioPerformance = field(default_factory=PortfolioPerformance)
    allocation: List[dict] = field(default_factory=list)
    snapshots: List[PortfolioSnapshot] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    reconciliation: Optional[ReconciliationResult] = None


# ----------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------

class PortfolioService:
    def __init__(
        self,
        db_path: str = DB_PATH,
        account_id: str = "default",
        starting_balance: float = 100000.0,
        get_account_fn: Callable = get_account_row,
        get_positions_fn: Callable = get_all_position_rows,
        get_trades_fn: Callable = get_trade_rows,
        get_snapshots_fn: Callable = get_snapshot_rows,
        insert_snapshot_fn: Callable = insert_snapshot,
        paper_trading_service: Optional[PaperTradingService] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._db_path = db_path
        self._account_id = account_id
        self._starting_balance = starting_balance
        self._get_account_fn = get_account_fn
        self._get_positions_fn = get_positions_fn
        self._get_trades_fn = get_trades_fn
        self._get_snapshots_fn = get_snapshots_fn
        self._insert_snapshot_fn = insert_snapshot_fn
        self._paper_trading_service = paper_trading_service
        self._logger = logger or logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def get_positions(self) -> List[PortfolioPosition]:
        account_row = self._read_account_row()
        position_rows = self._read_position_rows()

        equity = account_row["cash"] + sum(
            row["shares"] * row["current_price"] for row in position_rows
        )

        return [self._position_from_row(row, equity) for row in position_rows]

    def _position_from_row(self, row, equity: float) -> PortfolioPosition:
        quantity = row["shares"]
        average_entry_price = row["entry_price"]
        current_price = row["current_price"]

        cost_basis = quantity * average_entry_price
        market_value = quantity * current_price
        unrealised_pnl = market_value - cost_basis

        return PortfolioPosition(
            symbol=row["symbol"],
            quantity=quantity,
            average_entry_price=average_entry_price,
            current_price=current_price,
            cost_basis=cost_basis,
            market_value=market_value,
            unrealised_pnl=unrealised_pnl,
            unrealised_return_pct=self._safe_pct(unrealised_pnl, cost_basis),
            realised_pnl=row["realised_pnl"] or 0.0,
            portfolio_weight_pct=self._safe_pct(market_value, equity),
            stop_loss=row["stop_loss"],
            take_profit=row["take_profit"],
            opened_at=row["opened_at"],
            strategy_name=row["strategy_name"],
            strategy_mode=row["strategy_mode"],
        )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_summary(self) -> PortfolioSummary:
        account_row = self._read_account_row()
        positions = self.get_positions()

        cash = account_row["cash"]
        reserved_cash = account_row["reserved_cash"] or 0.0
        starting_capital = account_row["starting_balance"]
        realised_pnl = account_row["realised_pnl"] or 0.0

        cost_basis_total = sum(p.cost_basis for p in positions)
        market_value_total = sum(p.market_value for p in positions)
        unrealised_pnl_total = market_value_total - cost_basis_total

        equity = cash + market_value_total
        total_pnl = realised_pnl + unrealised_pnl_total

        gross_exposure_value = sum(abs(p.market_value) for p in positions)
        net_exposure_value = sum(p.market_value for p in positions)

        position_count = len(positions)
        market_values = [p.market_value for p in positions]

        return PortfolioSummary(
            starting_capital=starting_capital,
            cash=cash,
            reserved_cash=reserved_cash,
            invested_capital=cost_basis_total,
            market_value=market_value_total,
            equity=equity,
            realised_pnl=realised_pnl,
            unrealised_pnl=unrealised_pnl_total,
            total_pnl=total_pnl,
            total_return_pct=self._safe_pct(total_pnl, starting_capital),
            gross_exposure_pct=self._safe_pct(gross_exposure_value, equity),
            net_exposure_pct=self._safe_pct(net_exposure_value, equity),
            cash_pct=self._safe_pct(cash, equity),
            position_count=position_count,
            largest_position_pct=(
                self._safe_pct(max(market_values), equity) if market_values else None
            ),
            average_position_value=(
                (sum(market_values) / position_count) if position_count else None
            ),
        )

    # ------------------------------------------------------------------
    # Performance (completed trades + snapshot-derived equity curve)
    # ------------------------------------------------------------------

    def get_performance(self, snapshot_limit: Optional[int] = None) -> PortfolioPerformance:
        performance, _warning = self._build_performance(
            self._completed_trade_rows(), self._read_snapshot_rows(snapshot_limit)
        )
        return performance

    def _completed_trade_rows(self):
        return [row for row in self._read_trade_rows() if row["exit_reason"] is not None]

    def _build_performance(self, completed_trades, snapshot_rows):
        stats = self._trade_statistics(completed_trades)
        (
            equity_curve, returns, peak_equity, current_drawdown_pct, max_drawdown_pct,
            volatility_pct, sharpe_ratio, sortino_ratio, warning,
        ) = self._equity_curve_metrics(snapshot_rows)

        performance = PortfolioPerformance(
            equity_curve=equity_curve,
            returns=returns,
            peak_equity=peak_equity,
            current_drawdown_pct=current_drawdown_pct,
            max_drawdown_pct=max_drawdown_pct,
            volatility_pct=volatility_pct,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            total_completed_trades=stats["total"],
            winning_trades=stats["winners"],
            losing_trades=stats["losers"],
            win_rate_pct=stats["win_rate"],
            gross_profit=stats["gross_profit"],
            gross_loss=stats["gross_loss"],
            profit_factor=stats["profit_factor"],
            average_win=stats["average_win"],
            average_loss=stats["average_loss"],
            expectancy=stats["expectancy"],
            total_fees=stats["total_fees"],
        )

        return performance, warning

    @staticmethod
    def _trade_statistics(rows) -> dict:
        total = len(rows)

        if total == 0:
            return dict(
                total=0, winners=0, losers=0, win_rate=0.0, gross_profit=0.0,
                gross_loss=0.0, profit_factor=0.0, average_win=0.0, average_loss=0.0,
                expectancy=0.0, total_fees=0.0,
            )

        net_pnls = [row["net_pnl"] or 0.0 for row in rows]
        fees = [row["fees"] or 0.0 for row in rows]
        winners = [pnl for pnl in net_pnls if pnl > 0]
        losers = [pnl for pnl in net_pnls if pnl <= 0]

        gross_profit = sum(winners)
        gross_loss = abs(sum(losers))

        return dict(
            total=total,
            winners=len(winners),
            losers=len(losers),
            win_rate=(len(winners) / total) * 100,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            profit_factor=(gross_profit / gross_loss) if gross_loss != 0 else 0.0,
            average_win=(sum(winners) / len(winners)) if winners else 0.0,
            average_loss=(sum(losers) / len(losers)) if losers else 0.0,
            expectancy=sum(net_pnls) / total,
            total_fees=sum(fees),
        )

    @staticmethod
    def _equity_curve_metrics(snapshot_rows):
        """Returns (equity_curve, returns, peak_equity, current_drawdown_pct,
        max_drawdown_pct, volatility_pct, sharpe_ratio, sortino_ratio,
        warning). All statistics are unannualised, computed directly on
        the available snapshot-to-snapshot returns."""
        if not snapshot_rows:
            return (
                [], [], None, None, None, None, None, None,
                "No portfolio snapshots yet; equity curve, drawdown, and "
                "volatility/Sharpe/Sortino are unavailable. Use "
                "create_snapshot() to begin tracking history.",
            )

        equity_curve = [
            {"timestamp": row["timestamp"], "equity": row["equity"]} for row in snapshot_rows
        ]
        equities = [row["equity"] for row in snapshot_rows]

        running_peak = equities[0]
        drawdowns = []

        for value in equities:
            running_peak = max(running_peak, value)
            drawdowns.append(((value - running_peak) / running_peak * 100) if running_peak else 0.0)

        peak_equity = max(equities)
        max_drawdown_pct = min(drawdowns)
        current_drawdown_pct = drawdowns[-1]

        if len(equities) < _MIN_SNAPSHOTS_FOR_RETURNS:
            return (
                equity_curve, [], peak_equity, current_drawdown_pct, max_drawdown_pct,
                None, None, None,
                f"Only {len(equities)} snapshot(s) available; volatility/Sharpe/"
                f"Sortino require at least {_MIN_SNAPSHOTS_FOR_RETURNS} snapshots.",
            )

        returns = [
            ((equities[i] - equities[i - 1]) / equities[i - 1]) if equities[i - 1] else 0.0
            for i in range(1, len(equities))
        ]

        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        volatility = variance ** 0.5
        sharpe_ratio = (mean_return / volatility) if volatility != 0 else None

        downside_returns = [r for r in returns if r < 0]

        if downside_returns:
            downside_mean = sum(downside_returns) / len(downside_returns)
            downside_variance = sum((r - downside_mean) ** 2 for r in downside_returns) / len(downside_returns)
            downside_std = downside_variance ** 0.5
            sortino_ratio = (mean_return / downside_std) if downside_std != 0 else None
        else:
            sortino_ratio = None

        return (
            equity_curve, returns, peak_equity, current_drawdown_pct, max_drawdown_pct,
            volatility * 100, sharpe_ratio, sortino_ratio, None,
        )

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def create_snapshot(self) -> PortfolioSnapshot:
        summary = self.get_summary()

        try:
            self._insert_snapshot_fn(
                account_id=self._account_id,
                cash=summary.cash,
                market_value=summary.market_value,
                equity=summary.equity,
                realised_pnl=summary.realised_pnl,
                unrealised_pnl=summary.unrealised_pnl,
                gross_exposure=summary.gross_exposure_pct or 0.0,
                position_count=summary.position_count,
                db_path=self._db_path,
            )
            rows = self._get_snapshots_fn(account_id=self._account_id, db_path=self._db_path)
        except Exception as exc:
            self._logger.exception("Failed to create portfolio snapshot.")
            raise SnapshotPersistenceError("Failed to create portfolio snapshot.") from exc

        if not rows:
            raise SnapshotPersistenceError("Snapshot was written but could not be re-read.")

        return self._snapshot_from_row(rows[-1])

    def get_snapshots(self, limit: Optional[int] = None) -> List[PortfolioSnapshot]:
        return [self._snapshot_from_row(row) for row in self._read_snapshot_rows(limit)]

    @staticmethod
    def _snapshot_from_row(row) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            snapshot_id=row["id"],
            timestamp=row["timestamp"],
            cash=row["cash"],
            market_value=row["market_value"],
            equity=row["equity"],
            realised_pnl=row["realised_pnl"],
            unrealised_pnl=row["unrealised_pnl"],
            gross_exposure_pct=row["gross_exposure"],
            position_count=row["position_count"],
        )

    # ------------------------------------------------------------------
    # Reconciliation (surfaced, not duplicated)
    # ------------------------------------------------------------------

    def get_reconciliation(self) -> ReconciliationResult:
        service = self._paper_trading_service or PaperTradingService(
            db_path=self._db_path,
            account_id=self._account_id,
            starting_balance=self._starting_balance,
        )

        try:
            return service.reconcile()
        except Exception as exc:
            self._logger.exception("Failed to compute portfolio reconciliation.")
            raise PortfolioDataError("Failed to compute portfolio reconciliation.") from exc

    # ------------------------------------------------------------------
    # Full analysis
    # ------------------------------------------------------------------

    def get_analysis(self, snapshot_limit: Optional[int] = None) -> PortfolioAnalysis:
        summary = self.get_summary()
        positions = self.get_positions()

        snapshot_rows = self._read_snapshot_rows(snapshot_limit)
        performance, performance_warning = self._build_performance(
            self._completed_trade_rows(), snapshot_rows
        )
        snapshots = [self._snapshot_from_row(row) for row in snapshot_rows]

        allocation = [
            {
                "symbol": p.symbol,
                "market_value": p.market_value,
                "weight_pct": p.portfolio_weight_pct,
            }
            for p in positions
        ]

        warnings = []

        if performance_warning:
            warnings.append(performance_warning)

        reconciliation = None

        try:
            reconciliation = self.get_reconciliation()
        except PortfolioServiceError as exc:
            warnings.append(f"Reconciliation could not be computed: {exc}")

        return PortfolioAnalysis(
            summary=summary,
            positions=positions,
            performance=performance,
            allocation=allocation,
            snapshots=snapshots,
            warnings=warnings,
            reconciliation=reconciliation,
        )

    # ------------------------------------------------------------------
    # Read helpers (error translation only - no SQL here)
    # ------------------------------------------------------------------

    def _read_account_row(self):
        try:
            row = self._get_account_fn(self._db_path)
        except Exception as exc:
            self._logger.exception("Failed to read account state.")
            raise PortfolioDataError("Failed to read account state.") from exc

        if row is None:
            raise PortfolioDataError("Paper account state is missing.")

        return row

    def _read_position_rows(self):
        try:
            return self._get_positions_fn(self._db_path)
        except Exception as exc:
            self._logger.exception("Failed to read open positions.")
            raise PortfolioDataError("Failed to read open positions.") from exc

    def _read_trade_rows(self):
        try:
            return self._get_trades_fn(self._db_path)
        except Exception as exc:
            self._logger.exception("Failed to read trade history.")
            raise PortfolioDataError("Failed to read trade history.") from exc

    def _read_snapshot_rows(self, limit: Optional[int] = None):
        try:
            return self._get_snapshots_fn(account_id=self._account_id, limit=limit, db_path=self._db_path)
        except Exception as exc:
            self._logger.exception("Failed to read portfolio snapshots.")
            raise SnapshotPersistenceError("Failed to read portfolio snapshots.") from exc

    @staticmethod
    def _safe_pct(numerator: float, denominator: float) -> Optional[float]:
        if not denominator:
            return None

        return (numerator / denominator) * 100
