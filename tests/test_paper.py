"""Tests for paper exchange adapter."""

import pytest
from autopilot.exchanges.paper import PaperAdapter
from autopilot.types import Bar, OrderSide, OrderStatus, OrderType


@pytest.fixture
def paper():
    return PaperAdapter(
        initial_balances={"USDC": 1000, "BTC": 0},
        fee_rate=0.001,
    )


@pytest.mark.asyncio
async def test_connect(paper):
    await paper.connect()
    await paper.disconnect()


@pytest.mark.asyncio
async def test_initial_balance(paper):
    await paper.connect()
    bal = await paper.get_balances()
    assert bal["USDC"].free == 1000


@pytest.mark.asyncio
async def test_market_buy(paper):
    await paper.connect()
    # Set last price
    paper._last_prices["BTCUSDC"] = 70000

    fills = []
    paper.on_fill(lambda f: fills.append(f))

    order = await paper.submit_order(
        "BTCUSDC", OrderSide.BUY, OrderType.MARKET, 0.01,
    )
    assert order.status == OrderStatus.FILLED
    assert len(fills) == 1
    assert fills[0].price == 70000
    assert fills[0].quantity == 0.01

    # Check balance updated
    bal = await paper.get_balances()
    assert bal["BTC"].free == 0.01
    assert bal["USDC"].free < 1000  # Deducted cost + fee


@pytest.mark.asyncio
async def test_limit_order_fills_on_bar(paper):
    await paper.connect()
    paper._last_prices["BTCUSDC"] = 70000

    fills = []
    paper.on_fill(lambda f: fills.append(f))

    # Subscribe so instrument is created
    await paper.subscribe_bars("BTCUSDC", "1h", lambda b: None)

    # Place limit buy below current price
    order = await paper.submit_order(
        "BTCUSDC", OrderSide.BUY, OrderType.LIMIT, 0.01,
        price=69000,
    )
    assert order.status == OrderStatus.ACCEPTED
    assert len(fills) == 0

    # Feed a bar that touches the limit price
    paper.feed_bar(Bar(
        "BTCUSDC", "1h", 0, 70000, 70500, 68500, 69500, 100,
    ))
    assert len(fills) == 1
    assert fills[0].price == 69000


@pytest.mark.asyncio
async def test_cancel_order(paper):
    await paper.connect()
    paper._last_prices["BTCUSDC"] = 70000
    await paper.subscribe_bars("BTCUSDC", "1h", lambda b: None)

    order = await paper.submit_order(
        "BTCUSDC", OrderSide.BUY, OrderType.LIMIT, 0.01, price=60000,
    )
    assert order.status == OrderStatus.ACCEPTED

    ok = await paper.cancel_order("BTCUSDC", order.id)
    assert ok

    orders = await paper.get_open_orders()
    assert len(orders) == 0
