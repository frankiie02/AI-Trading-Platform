from typing import Any, Callable, Dict, Optional

from config.defaults import DEFAULT_SETTINGS
from core.runtime.context import RuntimeContext
from core.runtime.modes import RuntimeMode
from core.runtime.router import RuntimeResult
from core.services.paper_trading_service import PaperTradingService


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
) -> RuntimeResult:
    """Standalone paper-trading runtime coordinator.

    Builds a PaperTradingService from the existing settings system,
    optionally refreshes open-position prices/exits through an injected
    price source (no market data is downloaded implicitly - price_fetch_fn
    defaults to None, in which case position marking/exit-checking is
    skipped and only queue processing runs), and processes the trade
    queue only if PAPER_PROCESS_QUEUE is explicitly enabled (defaults to
    False). Contains no Streamlit, broker, or live-execution code.
    """
    built = build_paper_settings(context.settings)
    process_queue = built.pop("process_queue")

    service = service or PaperTradingService(logger=context.logger, **built)

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
    account = service.get_account()
    open_positions = len(service.get_positions())

    message = (
        f"Paper trading completed: cash ${account.cash:,.2f}, "
        f"equity ${account.equity:,.2f}, {open_positions} open position(s), "
        f"{len(result.orders_filled)} order(s) filled, "
        f"{len(result.orders_rejected)} rejected, "
        f"realised P&L ${account.realised_pnl:,.2f}, "
        f"unrealised P&L ${account.unrealised_pnl:,.2f}."
    )

    context.logger.info(message)

    return RuntimeResult(
        mode=RuntimeMode.PAPER,
        status="completed",
        message=message,
    )
