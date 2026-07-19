"""Small broker factory. No plugin/registry framework.

create_broker(environment) supports BrokerEnvironment.PAPER only (local
PaperBroker); any other environment raises BrokerUnsupportedOperationError
rather than silently falling back to paper. It is left completely
unchanged by the IBKR milestone.

create_ibkr_broker(config) is a separate, sibling entry point - deliberately
not folded into create_broker(), since BrokerEnvironment.PAPER already means
"local PaperBroker" there, and reusing the same enum value to also mean
"IBKR read-only paper connection" would make broker-type selection
ambiguous. IBKR creation always requires an explicit IBKRConnectionConfig
(which itself fails closed on read_only=False or environment=LIVE - see
ibkr_broker.py); a missing optional ib_insync dependency only surfaces when
IBKR is actually requested, never for the paper path. Neither factory
function connects during construction.
"""
from typing import Optional

from core.broker.base import BrokerInterface
from core.broker.errors import BrokerUnsupportedOperationError
from core.broker.ibkr_broker import IBKRBroker, IBKRConnectionConfig
from core.broker.ibkr_client import IBKRClientProtocol
from core.broker.models import BrokerEnvironment
from core.broker.paper_broker import PaperBroker
from core.services.paper_trading_service import PaperTradingService
from core.services.portfolio_service import PortfolioService


def create_broker(
    environment: BrokerEnvironment,
    *,
    paper_service: Optional[PaperTradingService] = None,
    portfolio_service: Optional[PortfolioService] = None,
) -> BrokerInterface:
    if environment is not BrokerEnvironment.PAPER:
        raise BrokerUnsupportedOperationError(
            f"No broker adapter is available for environment={environment.value}; "
            "only BrokerEnvironment.PAPER is supported in this milestone."
        )

    paper_service = paper_service or PaperTradingService()
    portfolio_service = portfolio_service or PortfolioService(
        db_path=paper_service.db_path, paper_trading_service=paper_service,
    )

    return PaperBroker(paper_service, portfolio_service)


def create_ibkr_broker(
    config: IBKRConnectionConfig,
    *,
    client: Optional[IBKRClientProtocol] = None,
) -> BrokerInterface:
    """Constructs a read-only IBKRBroker. config.__post_init__ already fails
    closed (BrokerValidationError/BrokerUnsupportedOperationError) if
    read_only is False or environment is LIVE, so no additional check is
    needed here. If `client` is omitted, a real ib_insync-backed client is
    only constructed lazily inside IBKRBroker - so a missing optional
    dependency raises BrokerConnectionError right here, not at import time,
    and never affects create_broker()/PaperBroker."""
    return IBKRBroker(config, client=client)
