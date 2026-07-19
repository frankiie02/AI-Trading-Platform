"""Small broker factory. Supports BrokerEnvironment.PAPER only; any other
environment raises BrokerUnsupportedOperationError rather than silently
falling back to paper. No plugin/registry framework - one explicit branch,
extended with one line per future broker adapter.
"""
from typing import Optional

from core.broker.base import BrokerInterface
from core.broker.errors import BrokerUnsupportedOperationError
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
