import ast
import os

import pytest

from core.pipeline.models import TradingDecision
from core.services.paper_trading_service import ExitReason, PaperTradingService
from core.services.portfolio_service import (
    PortfolioDataError,
    PortfolioService,
    SnapshotPersistenceError,
)

FORBIDDEN_IMPORT_PREFIXES = (
    "streamlit",
    "pages",
    "dashboard",
    "core.broker",
    "core.runtime",
    "ib_insync",
)

FORBIDDEN_DIRECT_COLLABORATOR_MODULES = (
    "core.strategy",
    "core.voting",
    "core.regime",
    "core.alpha",
    "core.risk",
    "core.indicators",
    "core.market_data",
    "core.pipeline.trading_pipeline",
)

MODULE_PATH = os.path.join("core", "services", "portfolio_service.py")


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "portfolio_test.db")


def make_paper_service(db_path, **overrides):
    kwargs = dict(
        db_path=db_path, starting_balance=10000.0, commission=0.0, slippage_percent=0.0,
        max_open_positions=10, max_position_percent=100.0,
    )
    kwargs.update(overrides)
    return PaperTradingService(**kwargs)


def make_portfolio_service(db_path, paper_service, **overrides):
    kwargs = dict(db_path=db_path, starting_balance=10000.0, paper_trading_service=paper_service)
    kwargs.update(overrides)
    return PortfolioService(**kwargs)


def buy(paper_service, symbol, price, shares, stop_loss=None, take_profit=None):
    return paper_service.create_order_from_decision(
        TradingDecision(
            symbol=symbol, final_signal="BUY", raw_signal="BUY", strategy_name="T",
            current_price=price, suggested_shares=shares, stop_loss=stop_loss, take_profit=take_profit,
        )
    )


# ----------------------------------------------------------------------
# Summary: empty / single / multiple positions
# ----------------------------------------------------------------------

def test_empty_portfolio_summary(db_path):
    paper = make_paper_service(db_path)
    portfolio = make_portfolio_service(db_path, paper)

    summary = portfolio.get_summary()

    assert summary.position_count == 0
    assert summary.equity == 10000.0
    assert summary.market_value == 0
    assert summary.cash == 10000.0
    assert summary.largest_position_pct is None
    assert summary.average_position_value is None


def test_summary_with_one_position(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)
    portfolio = make_portfolio_service(db_path, paper)

    summary = portfolio.get_summary()

    assert summary.position_count == 1
    assert summary.market_value == 1000.0
    assert summary.cash == 9000.0
    assert summary.equity == 10000.0


def test_summary_with_multiple_positions(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)
    buy(paper, "MSFT", 200.0, 5)
    portfolio = make_portfolio_service(db_path, paper)

    summary = portfolio.get_summary()

    assert summary.position_count == 2
    assert summary.market_value == 1000.0 + 1000.0
    assert summary.cash == 10000.0 - 1000.0 - 1000.0


# ----------------------------------------------------------------------
# Position-level equations
# ----------------------------------------------------------------------

def test_position_cost_basis(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)
    portfolio = make_portfolio_service(db_path, paper)

    position = portfolio.get_positions()[0]
    assert position.cost_basis == 1000.0


def test_position_market_value(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)
    paper.update_positions({"AAPL": 120.0})
    portfolio = make_portfolio_service(db_path, paper)

    position = portfolio.get_positions()[0]
    assert position.market_value == 1200.0


def test_position_unrealised_pnl(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)
    paper.update_positions({"AAPL": 120.0})
    portfolio = make_portfolio_service(db_path, paper)

    position = portfolio.get_positions()[0]
    assert position.unrealised_pnl == 200.0
    assert position.unrealised_return_pct == pytest.approx(20.0)


def test_position_realised_pnl_after_partial_close(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)
    paper.close_position("AAPL", quantity=4, price=110.0, reason=ExitReason.MANUAL)
    portfolio = make_portfolio_service(db_path, paper)

    position = portfolio.get_positions()[0]
    assert position.quantity == 6
    assert position.realised_pnl == pytest.approx(40.0)


def test_summary_realised_pnl_after_full_close(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)
    paper.close_position("AAPL", price=110.0, reason=ExitReason.MANUAL)
    portfolio = make_portfolio_service(db_path, paper)

    summary = portfolio.get_summary()
    assert summary.realised_pnl == pytest.approx(100.0)
    assert summary.position_count == 0


# ----------------------------------------------------------------------
# Equity / total P&L / total return
# ----------------------------------------------------------------------

def test_equity_equals_cash_plus_market_value(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)
    paper.update_positions({"AAPL": 130.0})
    portfolio = make_portfolio_service(db_path, paper)

    summary = portfolio.get_summary()
    assert summary.equity == pytest.approx(summary.cash + summary.market_value)


def test_total_pnl(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)
    paper.update_positions({"AAPL": 130.0})
    portfolio = make_portfolio_service(db_path, paper)

    summary = portfolio.get_summary()
    assert summary.total_pnl == pytest.approx(summary.realised_pnl + summary.unrealised_pnl)
    assert summary.total_pnl == pytest.approx(300.0)


def test_total_return_pct(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)
    paper.update_positions({"AAPL": 130.0})
    portfolio = make_portfolio_service(db_path, paper)

    summary = portfolio.get_summary()
    assert summary.total_return_pct == pytest.approx(3.0)


# ----------------------------------------------------------------------
# Exposure / cash % / weights
# ----------------------------------------------------------------------

def test_gross_exposure_pct(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)
    portfolio = make_portfolio_service(db_path, paper)

    summary = portfolio.get_summary()
    assert summary.gross_exposure_pct == pytest.approx((1000.0 / 10000.0) * 100)


def test_net_exposure_pct_matches_gross_when_long_only(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)
    buy(paper, "MSFT", 200.0, 5)
    portfolio = make_portfolio_service(db_path, paper)

    summary = portfolio.get_summary()
    assert summary.net_exposure_pct == pytest.approx(summary.gross_exposure_pct)


def test_cash_pct(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)
    portfolio = make_portfolio_service(db_path, paper)

    summary = portfolio.get_summary()
    assert summary.cash_pct == pytest.approx((9000.0 / 10000.0) * 100)


def test_position_portfolio_weight(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)
    portfolio = make_portfolio_service(db_path, paper)

    position = portfolio.get_positions()[0]
    assert position.portfolio_weight_pct == pytest.approx((1000.0 / 10000.0) * 100)


def test_largest_position_pct(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)  # 1000
    buy(paper, "MSFT", 200.0, 10)  # 2000, largest
    portfolio = make_portfolio_service(db_path, paper)

    summary = portfolio.get_summary()
    assert summary.largest_position_pct == pytest.approx((2000.0 / 10000.0) * 100)


def test_average_position_value(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)  # 1000
    buy(paper, "MSFT", 200.0, 10)  # 2000
    portfolio = make_portfolio_service(db_path, paper)

    summary = portfolio.get_summary()
    assert summary.average_position_value == pytest.approx(1500.0)


def test_zero_equity_safety():
    assert PortfolioService._safe_pct(5.0, 0) is None
    assert PortfolioService._safe_pct(5.0, None) is None
    assert PortfolioService._safe_pct(0, 100) == 0.0


# ----------------------------------------------------------------------
# Completed-trade statistics
# ----------------------------------------------------------------------

def test_completed_trade_count(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)
    paper.close_position("AAPL", price=110.0, reason=ExitReason.MANUAL)
    portfolio = make_portfolio_service(db_path, paper)

    performance = portfolio.get_performance()
    assert performance.total_completed_trades == 1


def test_winning_and_losing_trade_counts(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)
    paper.close_position("AAPL", price=110.0, reason=ExitReason.MANUAL)  # winner
    buy(paper, "MSFT", 100.0, 10)
    paper.close_position("MSFT", price=90.0, reason=ExitReason.MANUAL)  # loser
    portfolio = make_portfolio_service(db_path, paper)

    performance = portfolio.get_performance()
    assert performance.winning_trades == 1
    assert performance.losing_trades == 1


def test_win_rate_pct(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)
    paper.close_position("AAPL", price=110.0, reason=ExitReason.MANUAL)
    buy(paper, "MSFT", 100.0, 10)
    paper.close_position("MSFT", price=90.0, reason=ExitReason.MANUAL)
    portfolio = make_portfolio_service(db_path, paper)

    performance = portfolio.get_performance()
    assert performance.win_rate_pct == pytest.approx(50.0)


def test_gross_profit_and_loss(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)
    paper.close_position("AAPL", price=110.0, reason=ExitReason.MANUAL)  # +100
    buy(paper, "MSFT", 100.0, 10)
    paper.close_position("MSFT", price=90.0, reason=ExitReason.MANUAL)  # -100
    portfolio = make_portfolio_service(db_path, paper)

    performance = portfolio.get_performance()
    assert performance.gross_profit == pytest.approx(100.0)
    assert performance.gross_loss == pytest.approx(100.0)


def test_profit_factor(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)
    paper.close_position("AAPL", price=120.0, reason=ExitReason.MANUAL)  # +200
    buy(paper, "MSFT", 100.0, 10)
    paper.close_position("MSFT", price=90.0, reason=ExitReason.MANUAL)  # -100
    portfolio = make_portfolio_service(db_path, paper)

    performance = portfolio.get_performance()
    assert performance.profit_factor == pytest.approx(2.0)


def test_average_win_and_loss(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)
    paper.close_position("AAPL", price=110.0, reason=ExitReason.MANUAL)  # +100
    buy(paper, "MSFT", 100.0, 10)
    paper.close_position("MSFT", price=90.0, reason=ExitReason.MANUAL)  # -100
    portfolio = make_portfolio_service(db_path, paper)

    performance = portfolio.get_performance()
    assert performance.average_win == pytest.approx(100.0)
    assert performance.average_loss == pytest.approx(-100.0)


def test_expectancy(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)
    paper.close_position("AAPL", price=110.0, reason=ExitReason.MANUAL)  # +100
    buy(paper, "MSFT", 100.0, 10)
    paper.close_position("MSFT", price=90.0, reason=ExitReason.MANUAL)  # -100
    portfolio = make_portfolio_service(db_path, paper)

    performance = portfolio.get_performance()
    assert performance.expectancy == pytest.approx(0.0)


def test_total_fees(db_path):
    paper = make_paper_service(db_path, commission=2.5)
    buy(paper, "AAPL", 100.0, 10)
    paper.close_position("AAPL", price=110.0, reason=ExitReason.MANUAL)
    portfolio = make_portfolio_service(db_path, paper)

    performance = portfolio.get_performance()
    assert performance.total_fees == pytest.approx(2.5)  # exit fee only (entry commission=0 default override)


def test_zero_completed_trades_returns_safe_defaults(db_path):
    paper = make_paper_service(db_path)
    portfolio = make_portfolio_service(db_path, paper)

    performance = portfolio.get_performance()
    assert performance.total_completed_trades == 0
    assert performance.win_rate_pct == 0.0
    assert performance.profit_factor == 0.0


# ----------------------------------------------------------------------
# Snapshots
# ----------------------------------------------------------------------

def test_create_snapshot(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)
    portfolio = make_portfolio_service(db_path, paper)

    snapshot = portfolio.create_snapshot()

    assert snapshot.snapshot_id is not None
    assert snapshot.equity == 10000.0
    assert snapshot.position_count == 1


def test_get_snapshots_reload(db_path):
    paper = make_paper_service(db_path)
    portfolio = make_portfolio_service(db_path, paper)

    portfolio.create_snapshot()
    portfolio.create_snapshot()

    snapshots = portfolio.get_snapshots()
    assert len(snapshots) == 2


def test_snapshots_chronological_order(db_path):
    paper = make_paper_service(db_path)
    portfolio = make_portfolio_service(db_path, paper)

    first = portfolio.create_snapshot()
    buy(paper, "AAPL", 100.0, 10)
    second = portfolio.create_snapshot()

    snapshots = portfolio.get_snapshots()
    assert snapshots[0].snapshot_id == first.snapshot_id
    assert snapshots[1].snapshot_id == second.snapshot_id


def test_snapshot_creation_is_explicit_not_on_every_read(db_path):
    paper = make_paper_service(db_path)
    portfolio = make_portfolio_service(db_path, paper)

    portfolio.get_summary()
    portfolio.get_positions()
    portfolio.get_analysis()

    assert portfolio.get_snapshots() == []


# ----------------------------------------------------------------------
# Performance from snapshots: equity curve / drawdown / insufficient history
# ----------------------------------------------------------------------

def test_equity_curve_from_snapshots(db_path):
    paper = make_paper_service(db_path)
    portfolio = make_portfolio_service(db_path, paper)

    portfolio.create_snapshot()
    buy(paper, "AAPL", 100.0, 10)
    portfolio.create_snapshot()

    performance = portfolio.get_performance()
    assert len(performance.equity_curve) == 2


def test_drawdown_from_snapshots(db_path):
    paper = make_paper_service(db_path)
    portfolio = make_portfolio_service(db_path, paper)

    portfolio.create_snapshot()  # equity 10000
    buy(paper, "AAPL", 100.0, 10)
    paper.update_positions({"AAPL": 80.0})  # equity drops to 9800
    portfolio.create_snapshot()
    paper.update_positions({"AAPL": 100.0})  # equity back to 10000
    portfolio.create_snapshot()

    performance = portfolio.get_performance()
    assert performance.max_drawdown_pct < 0
    assert performance.current_drawdown_pct == pytest.approx(0.0, abs=0.01)


def test_insufficient_snapshot_history_zero_snapshots(db_path):
    paper = make_paper_service(db_path)
    portfolio = make_portfolio_service(db_path, paper)

    performance = portfolio.get_performance()
    assert performance.equity_curve == []
    assert performance.max_drawdown_pct is None
    assert performance.volatility_pct is None
    assert performance.sharpe_ratio is None

    analysis = portfolio.get_analysis()
    assert any("No portfolio snapshots yet" in w for w in analysis.warnings)


def test_insufficient_snapshot_history_one_snapshot(db_path):
    paper = make_paper_service(db_path)
    portfolio = make_portfolio_service(db_path, paper)

    portfolio.create_snapshot()

    performance = portfolio.get_performance()
    assert len(performance.equity_curve) == 1
    assert performance.max_drawdown_pct == 0.0
    assert performance.volatility_pct is None
    assert performance.sharpe_ratio is None

    analysis = portfolio.get_analysis()
    assert any("snapshot(s) available" in w for w in analysis.warnings)


def test_sufficient_snapshot_history_computes_volatility(db_path):
    paper = make_paper_service(db_path)
    portfolio = make_portfolio_service(db_path, paper)

    portfolio.create_snapshot()
    buy(paper, "AAPL", 100.0, 10)
    paper.update_positions({"AAPL": 120.0})
    portfolio.create_snapshot()
    paper.update_positions({"AAPL": 90.0})
    portfolio.create_snapshot()

    performance = portfolio.get_performance()
    assert performance.volatility_pct is not None
    assert performance.sharpe_ratio is not None


# ----------------------------------------------------------------------
# Reconciliation
# ----------------------------------------------------------------------

def test_reconciliation_balanced(db_path):
    paper = make_paper_service(db_path)
    buy(paper, "AAPL", 100.0, 10)
    paper.close_position("AAPL", price=110.0, reason=ExitReason.MANUAL)
    portfolio = make_portfolio_service(db_path, paper)

    result = portfolio.get_reconciliation()
    assert result.balanced is True


def test_reconciliation_mismatch(db_path):
    from core.database.database import get_connection

    paper = make_paper_service(db_path)
    portfolio = make_portfolio_service(db_path, paper)

    conn = get_connection(db_path)
    conn.execute("UPDATE account_state SET realised_pnl = realised_pnl + 999 WHERE id = 1")
    conn.commit()
    conn.close()

    result = portfolio.get_reconciliation()
    assert result.balanced is False


def test_get_analysis_includes_reconciliation(db_path):
    paper = make_paper_service(db_path)
    portfolio = make_portfolio_service(db_path, paper)

    analysis = portfolio.get_analysis()
    assert analysis.reconciliation is not None
    assert analysis.reconciliation.balanced is True


# ----------------------------------------------------------------------
# Data-read error translation
# ----------------------------------------------------------------------

def test_missing_account_row_raises_portfolio_data_error(db_path):
    portfolio = PortfolioService(
        db_path=db_path, starting_balance=10000.0,
        get_account_fn=lambda db_path: None,
    )

    with pytest.raises(PortfolioDataError):
        portfolio.get_summary()


def test_snapshot_read_failure_raises_snapshot_persistence_error(db_path):
    def failing_get_snapshots(account_id=None, limit=None, db_path=None):
        raise RuntimeError("disk error")

    paper = make_paper_service(db_path)
    portfolio = make_portfolio_service(db_path, paper, get_snapshots_fn=failing_get_snapshots)

    with pytest.raises(SnapshotPersistenceError):
        portfolio.get_snapshots()


# ----------------------------------------------------------------------
# Import-boundary / no-broker / no-live guards
# ----------------------------------------------------------------------

def _module_imports():
    with open(MODULE_PATH) as f:
        tree = ast.parse(f.read(), filename=MODULE_PATH)

    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)

    return imports


def test_portfolio_service_has_no_forbidden_imports():
    imports = _module_imports()

    for module in imports:
        for forbidden in FORBIDDEN_IMPORT_PREFIXES:
            assert not module.startswith(forbidden), (
                f"portfolio_service.py imports forbidden module: {module}"
            )


def test_portfolio_service_does_not_import_domain_collaborators_directly():
    imports = _module_imports()

    for module in imports:
        for forbidden in FORBIDDEN_DIRECT_COLLABORATOR_MODULES:
            assert not module.startswith(forbidden), (
                f"portfolio_service.py imports domain collaborator directly: {module}"
            )


def test_portfolio_service_makes_no_streamlit_import():
    with open(MODULE_PATH) as f:
        source = f.read()

    assert "streamlit" not in source
    assert "ib_insync" not in source


def test_portfolio_service_has_no_direct_sql():
    with open(MODULE_PATH) as f:
        source = f.read()

    assert "sqlite3" not in source
    assert "cursor.execute(" not in source
    assert "conn.execute(" not in source
    assert "get_connection(" not in source


def test_no_real_project_database_touched(db_path):
    """Every test in this file passes an explicit tmp_path db_path."""
    assert db_path.endswith("portfolio_test.db")
