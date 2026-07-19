from typing import Any, Callable, Dict, Optional

from config.defaults import DEFAULT_SETTINGS
from core.runtime.context import RuntimeContext
from core.runtime.modes import RuntimeMode
from core.runtime.router import RuntimeResult
from core.services.paper_trading_service import PaperTradingService
from core.services.portfolio_service import PortfolioService


def _setting(settings: Dict[str, Any], key: str):
    return settings.get(key, DEFAULT_SETTINGS[key])


def build_paper_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Builds PaperTradingService constructor kwargs (plus a standalone
    'process_queue' flag) from the existing settings system, using the
    PAPER_* defaults (config/defaults.py) whenever a key is absent."""
    return {
        "account_id": _setting(settings, "PAPER_ACCOUNT_ID"),
        "starting_balance": _setting(settings, "PAPER_STARTING_BALANCE"),
        "commission": _setting(settings, "PAPER_COMMISSION"),
        "slippage_percent": _setting(settings, "PAPER_SLIPPAGE"),
        "max_open_positions": _setting(settings, "PAPER_MAX_OPEN_POSITIONS"),
        "max_position_percent": _setting(settings, "PAPER_MAX_POSITION_PERCENT"),
        "require_stop_loss": _setting(settings, "PAPER_REQUIRE_STOP_LOSS"),
        "require_take_profit": _setting(settings, "PAPER_REQUIRE_TAKE_PROFIT"),
        "process_queue": _setting(settings, "PAPER_PROCESS_QUEUE"),
    }


def run_paper_trading(
    context: RuntimeContext,
    service: Optional[PaperTradingService] = None,
    price_fetch_fn: Optional[Callable[[str], float]] = None,
    portfolio_service: Optional[PortfolioService] = None,
) -> RuntimeResult:
    """Standalone paper-trading runtime coordinator.

    Builds a PaperTradingService from the existing settings system,
    optionally refreshes open-position prices/exits through an injected
    price source (no market data is downloaded implicitly - price_fetch_fn
    defaults to None, in which case position marking/exit-checking is
    skipped and only queue processing runs), and processes the trade
    queue only if PAPER_PROCESS_QUEUE is explicitly enabled (defaults to
    False). Contains no Streamlit, broker, or live-execution code.

    The terminal summary (cash, equity, position count, realised/
    unrealised P&L) is sourced from PortfolioService rather than
    re-deriving those figures here, so the runtime never duplicates
    portfolio equations - PortfolioService is the single authoritative
    source for them.
    """
    built = build_paper_settings(context.settings)
    process_queue = built.pop("process_queue")

    service = service or PaperTradingService(logger=context.logger, **built)
    portfolio_service = portfolio_service or PortfolioService(
        db_path=service.db_path,
        account_id=built["account_id"],
        starting_balance=built["starting_balance"],
        paper_trading_service=service,
        logger=context.logger,
    )

    if price_fetch_fn is not None:
        positions = service.get_positions()
        price_map = {}

        for position in positions:
            try:
                price_map[position.symbol] = price_fetch_fn(position.symbol)
            except Exception:
                context.logger.exception(
                    "Failed to fetch current price for %s; skipping.", position.symbol
                )

        if price_map:
            service.update_positions(price_map)
            service.check_exits(price_map)

    result = service.process_queue(enabled=process_queue)
    summary = portfolio_service.get_summary()

    message = (
        f"Paper trading completed: cash ${summary.cash:,.2f}, "
        f"equity ${summary.equity:,.2f}, {summary.position_count} open position(s), "
        f"{len(result.orders_filled)} order(s) filled, "
        f"{len(result.orders_rejected)} rejected, "
        f"realised P&L ${summary.realised_pnl:,.2f}, "
        f"unrealised P&L ${summary.unrealised_pnl:,.2f}."
    )

    context.logger.info(message)

    return RuntimeResult(
        mode=RuntimeMode.PAPER,
        status="completed",
        message=message,
    )
