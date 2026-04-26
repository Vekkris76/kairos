"""RC1 regression tests for fill-callback propagation in BinanceLive.

Bug history: `BinanceLive.set_fill_callback` only set `self._on_fill`,
but `BinanceLive.submit_order` delegates to `self._rest.submit_order`
(an inner `BinanceAdapter`) which has its own `_fill_callback` slot.
The slot was never set, so MARKET orders that ccxt reported as instantly
filled at submit time silently dropped the synthesized Fill on the floor.
The bracket manager's `on_order_filled` was never invoked → brackets
stuck in `pending_fill` despite filled positions at the venue.

These tests lock in the post-fix contract: the registered callback lands
on `_rest._fill_callback` whether the registration happens before or
after `connect()`, and instant-fill MARKET orders surface a Fill through
that callback.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kairos.adapters.binance_live import BinanceLive
from kairos.exchanges.binance import BinanceAdapter
from kairos.types import Fill, OrderSide, OrderStatus, OrderType


pytestmark = pytest.mark.asyncio


# ── Propagation: post-connect path (rest already constructed) ──────


async def test_set_fill_callback_after_rest_present_propagates_to_inner() -> None:
    """When _rest already exists, set_fill_callback writes both slots."""
    adapter = BinanceLive(api_key="k", api_secret="s")
    rest_stub = SimpleNamespace(_fill_callback=None)
    adapter._rest = rest_stub  # simulate post-connect state

    cb = AsyncMock()
    adapter.set_fill_callback(cb)

    assert adapter._on_fill is cb
    assert adapter._rest._fill_callback is cb


async def test_set_fill_callback_before_rest_only_sets_outer() -> None:
    """Before connect, _rest is None — propagation must no-op gracefully."""
    adapter = BinanceLive(api_key="k", api_secret="s")
    cb = AsyncMock()

    adapter.set_fill_callback(cb)

    assert adapter._on_fill is cb
    assert adapter._rest is None


async def test_re_register_callback_replaces_inner_slot() -> None:
    """Second registration replaces the first on both slots — no double-emission."""
    adapter = BinanceLive(api_key="k", api_secret="s")
    rest_stub = SimpleNamespace(_fill_callback=None)
    adapter._rest = rest_stub

    cb_a = AsyncMock()
    cb_b = AsyncMock()

    adapter.set_fill_callback(cb_a)
    assert rest_stub._fill_callback is cb_a

    adapter.set_fill_callback(cb_b)
    assert adapter._on_fill is cb_b
    assert rest_stub._fill_callback is cb_b


# ── Propagation: pre-connect path (callback set, then connect runs) ─


async def test_connect_propagates_pre_registered_callback(monkeypatch) -> None:
    """A callback registered BEFORE connect must land on the freshly-constructed _rest."""
    rest_stubs: list[SimpleNamespace] = []

    class StubBinanceAdapter:
        def __init__(self, **kw) -> None:
            self._fill_callback = None
            rest_stubs.append(self)

        async def connect(self) -> None:
            return None

    class StubBinanceWebSocket:
        async def close(self) -> None:
            return None

    # connect() does lazy imports — patch at the source module path.
    monkeypatch.setattr(
        "kairos.exchanges.binance.BinanceAdapter", StubBinanceAdapter
    )
    monkeypatch.setattr(
        "kairos.exchanges.binance_ws.BinanceWebSocket", StubBinanceWebSocket
    )

    adapter = BinanceLive(api_key="k", api_secret="s")
    cb = AsyncMock()
    adapter.set_fill_callback(cb)

    # connect()'s WS-init block is wrapped in try/except, so the listen-key
    # fetch failure (no network in tests) is swallowed harmlessly. We only
    # care that _rest is constructed and the callback propagates.
    await adapter.connect()

    assert len(rest_stubs) == 1
    assert rest_stubs[0]._fill_callback is cb


# ── Instant-fill MARKET order surfaces a Fill via the callback ─────


async def test_instant_fill_market_invokes_registered_callback() -> None:
    """RC1 end-to-end: BinanceAdapter.submit_order with status='closed'
    must invoke the registered _fill_callback exactly once with a Fill
    matching the venue response."""
    adapter = BinanceAdapter(api_key="k", api_secret="s")

    captured: list[Fill] = []

    def sync_cb(fill: Fill) -> None:
        captured.append(fill)

    adapter._fill_callback = sync_cb

    # Stub the inner ccxt exchange to return an instant-fill response
    async def fake_create_order(*args, **kwargs):
        return {
            "id": "order-instant-123",
            "status": "closed",
            "average": 50_000.0,
            "fee": {"cost": 0.05, "currency": "USDC"},
        }

    adapter._exchange.create_order = fake_create_order

    order = await adapter.submit_order(
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.001,
    )

    assert order.id == "order-instant-123"
    assert order.status == OrderStatus.FILLED
    assert len(captured) == 1
    fill = captured[0]
    assert fill.order_id == "order-instant-123"
    assert fill.symbol == "BTCUSDC"
    assert fill.side == OrderSide.BUY
    assert fill.price == 50_000.0
    assert fill.quantity == 0.001
    assert fill.commission == 0.05


async def test_instant_fill_without_callback_does_not_crash() -> None:
    """Same path as above but no callback registered — must not raise."""
    adapter = BinanceAdapter(api_key="k", api_secret="s")
    assert adapter._fill_callback is None

    async def fake_create_order(*args, **kwargs):
        return {"id": "order-X", "status": "closed", "average": 50_000.0}

    adapter._exchange.create_order = fake_create_order

    order = await adapter.submit_order(
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.001,
    )
    assert order.id == "order-X"
    assert order.status == OrderStatus.FILLED
