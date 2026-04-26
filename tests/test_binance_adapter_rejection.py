"""RC3 regression tests for BinanceAdapter.submit_order failure handling.

Bug history: `BinanceAdapter.submit_order` previously caught every
exception during `ccxt.create_order` and returned a sentinel
`Order(id="", status=REJECTED)` instead of raising. Callers that did
not inspect `.status` (notably `BracketManager.submit_bracket_two_phase`)
blindly persisted `entry_order_id=""` as if the order had succeeded —
the bracket then sat in `pending_fill` forever because no real order
existed at the venue to ever fill.

The post-fix contract: every ccxt exception during submission is
re-raised as `OrderSubmissionError` with the original exception
chained via `__cause__`, so callers cannot accidentally treat a
failed submission as a successful one.
"""

from __future__ import annotations

import pytest

from kairos.exchanges.binance import BinanceAdapter
from kairos.exchanges.exceptions import OrderSubmissionError
from kairos.types import OrderSide, OrderType


pytestmark = pytest.mark.asyncio


async def test_submit_order_raises_on_ccxt_insufficient_funds() -> None:
    """ccxt.InsufficientFunds → OrderSubmissionError, not sentinel Order."""
    import ccxt

    adapter = BinanceAdapter(api_key="k", api_secret="s")

    async def fake_create_order(*args, **kwargs):
        raise ccxt.InsufficientFunds("Account has insufficient balance for requested action.")

    adapter._exchange.create_order = fake_create_order

    with pytest.raises(OrderSubmissionError) as exc_info:
        await adapter.submit_order(
            symbol="BTCUSDC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.001,
        )

    assert isinstance(exc_info.value.__cause__, ccxt.InsufficientFunds)
    assert "insufficient balance" in str(exc_info.value).lower()


async def test_submit_order_raises_on_ccxt_invalid_order() -> None:
    """ccxt.InvalidOrder (e.g. min notional) → OrderSubmissionError."""
    import ccxt

    adapter = BinanceAdapter(api_key="k", api_secret="s")

    async def fake_create_order(*args, **kwargs):
        raise ccxt.InvalidOrder("Filter failure: MIN_NOTIONAL")

    adapter._exchange.create_order = fake_create_order

    with pytest.raises(OrderSubmissionError) as exc_info:
        await adapter.submit_order(
            symbol="BTCUSDC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=0.0001,
            price=50_000,
        )

    assert isinstance(exc_info.value.__cause__, ccxt.InvalidOrder)


async def test_submit_order_raises_on_generic_exchange_error() -> None:
    """ccxt.ExchangeError (catch-all) → OrderSubmissionError."""
    import ccxt

    adapter = BinanceAdapter(api_key="k", api_secret="s")

    async def fake_create_order(*args, **kwargs):
        raise ccxt.ExchangeError("Generic exchange error from venue")

    adapter._exchange.create_order = fake_create_order

    with pytest.raises(OrderSubmissionError):
        await adapter.submit_order(
            symbol="BTCUSDC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.001,
        )


async def test_submit_order_does_not_return_empty_id_on_failure() -> None:
    """Defensive contract: even if a future regression catches the exception
    silently, callers must not see an Order with an empty id. The post-fix
    behaviour raises before constructing any Order at all.
    """
    import ccxt

    adapter = BinanceAdapter(api_key="k", api_secret="s")

    async def fake_create_order(*args, **kwargs):
        raise ccxt.NetworkError("Connection reset")

    adapter._exchange.create_order = fake_create_order

    # Either raises or — if a regression silently catches — must NOT return
    # an Order with id="". Express this as "not (returned an Order with id='')".
    try:
        order = await adapter.submit_order(
            symbol="BTCUSDC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.001,
        )
    except (OrderSubmissionError, ccxt.NetworkError):
        return  # expected
    else:
        # If we ever stop raising, at the very least the id must not be empty.
        assert order.id != "", (
            "RC3 regression: submit_order returned a sentinel Order(id='') "
            "instead of raising."
        )
