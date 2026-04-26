"""Lock-in test for BybitLive submission-failure handling.

Bybit's adapter does not have the RC1/RC3 bug shape that Binance had:

- RC1 (callback non-propagation): N/A. BybitLive performs its REST
  submission directly via `httpx.AsyncClient` (no separate inner
  adapter with its own `_fill_callback` slot).
- RC3 (silent sentinel on failure): N/A today. BybitLive.submit_order
  calls `resp.raise_for_status()` for HTTP errors and explicitly
  `raise RuntimeError(...)` when the Bybit response carries a
  non-zero `retCode`.

This test pins that behaviour so a future regression that swallows
errors and returns a sentinel `Order` would break CI.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from kairos.adapters.bybit_live import BybitLive
from kairos.types import OrderSide, OrderType


pytestmark = pytest.mark.asyncio


async def test_submit_order_raises_on_nonzero_retcode() -> None:
    """A Bybit response with retCode != 0 must raise, not return a sentinel."""
    adapter = BybitLive(api_key="k", api_secret="s")

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock(return_value=None)
    fake_response.json = MagicMock(
        return_value={
            "retCode": 110007,
            "retMsg": "Insufficient available balance",
            "result": {},
        },
    )

    fake_http = MagicMock()
    fake_http.post = AsyncMock(return_value=fake_response)
    adapter._http = fake_http

    with pytest.raises(RuntimeError, match="Insufficient available balance"):
        await adapter.submit_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.001,
        )


async def test_submit_order_raises_on_http_error() -> None:
    """An HTTP-level error (raise_for_status) must propagate."""
    import httpx

    adapter = BybitLive(api_key="k", api_secret="s")

    fake_request = httpx.Request("POST", "https://example/v5/order/create")
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "429 Too Many Requests",
            request=fake_request,
            response=MagicMock(),
        ),
    )

    fake_http = MagicMock()
    fake_http.post = AsyncMock(return_value=fake_response)
    adapter._http = fake_http

    with pytest.raises(httpx.HTTPStatusError):
        await adapter.submit_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.001,
        )
