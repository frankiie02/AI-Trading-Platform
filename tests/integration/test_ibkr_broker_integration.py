"""Opt-in IBKRBroker integration test against a real IB Gateway/TWS instance.

Skipped by default and NOT part of `pytest tests/unit`. To run it
deliberately against your own paper-trading IB Gateway/TWS:

    RUN_IBKR_INTEGRATION_TESTS=1 \\
    IBKR_HOST=127.0.0.1 IBKR_PORT=7497 IBKR_CLIENT_ID=1 \\
    pytest tests/integration/test_ibkr_broker_integration.py -v

All four env vars above are required; IBKR_ACCOUNT_ID is optional (only
needed to disambiguate a multi-account login). If RUN_IBKR_INTEGRATION_TESTS
is unset, every test in this file is skipped before any network activity
happens. This file is never invoked automatically by CI or by any other
test in this repository, and is not required to pass for this milestone to
be considered complete.

These tests only read: get_account()/get_positions()/get_open_orders()/
get_fills(), plus proving submit_order()/cancel_order() still raise
BrokerUnsupportedOperationError (which happens before any call reaches the
injected client, so it is safe against a real connection too). Nothing here
ever submits, cancels, or modifies an order.
"""
import os

import pytest

from core.broker.errors import BrokerUnsupportedOperationError
from core.broker.ibkr_broker import IBKRBroker, IBKRConnectionConfig

_RUN_FLAG = os.environ.get("RUN_IBKR_INTEGRATION_TESTS") == "1"

pytestmark = pytest.mark.skipif(
    not _RUN_FLAG,
    reason=(
        "Opt-in only: set RUN_IBKR_INTEGRATION_TESTS=1 (plus IBKR_HOST/"
        "IBKR_PORT/IBKR_CLIENT_ID) to run this against a real IB Gateway/"
        "TWS instance. Skipped by default."
    ),
)


def _config_from_env() -> IBKRConnectionConfig:
    host = os.environ.get("IBKR_HOST")
    port = os.environ.get("IBKR_PORT")
    client_id = os.environ.get("IBKR_CLIENT_ID")

    if not host or not port or not client_id:
        pytest.skip(
            "RUN_IBKR_INTEGRATION_TESTS=1 was set but IBKR_HOST/IBKR_PORT/"
            "IBKR_CLIENT_ID were not all provided; skipping rather than "
            "guessing connection details."
        )

    return IBKRConnectionConfig(
        host=host,
        port=int(port),
        client_id=int(client_id),
        account_id=os.environ.get("IBKR_ACCOUNT_ID"),
        read_only=True,
    )


@pytest.fixture
def connected_broker():
    broker = IBKRBroker(_config_from_env())
    broker.connect()
    try:
        yield broker
    finally:
        broker.disconnect()


def test_connect_reports_read_only_status(connected_broker):
    status = connected_broker.get_connection_status()
    assert status.is_connected
    assert status.metadata["read_only"] is True


def test_read_account_summary(connected_broker):
    account = connected_broker.get_account()
    assert account.account_id


def test_read_positions(connected_broker):
    positions = connected_broker.get_positions()
    assert isinstance(positions, list)


def test_read_open_orders(connected_broker):
    orders = connected_broker.get_open_orders()
    assert isinstance(orders, list)


def test_read_fills(connected_broker):
    fills = connected_broker.get_fills(limit=10)
    assert isinstance(fills, list)


def test_submit_order_is_rejected_even_when_connected(connected_broker):
    with pytest.raises(BrokerUnsupportedOperationError):
        connected_broker.submit_order(None)


def test_cancel_order_is_rejected_even_when_connected(connected_broker):
    with pytest.raises(BrokerUnsupportedOperationError):
        connected_broker.cancel_order("1")
