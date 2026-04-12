"""Tests for the LiveAdapter protocol shape + BinanceLive interface checks.

We do NOT test BinanceLive against the real Binance API here — that requires
testnet keys and network access. We DO verify:

- The protocol shape is what the engine expects
- BinanceLive implements every Protocol method
- Construction without connecting works
- Methods raise sensible errors before connect()
"""

from __future__ import annotations

import pytest

from kairos.adapters import BinanceLive, LiveAdapter


# ── Protocol shape ─────────────────────────────────────────────


def test_binance_live_implements_live_adapter_protocol() -> None:
    """BinanceLive must structurally satisfy the LiveAdapter Protocol."""
    adapter = BinanceLive(api_key="dummy", api_secret="dummy", testnet=True)
    # runtime_checkable Protocol — check class method presence
    assert isinstance(adapter, LiveAdapter)


def test_binance_live_venue_id_is_binance() -> None:
    adapter = BinanceLive(api_key="dummy", api_secret="dummy", testnet=True)
    assert adapter.venue_id == "binance"


def test_binance_live_starts_disconnected() -> None:
    adapter = BinanceLive(api_key="dummy", api_secret="dummy", testnet=True)
    assert adapter.connected is False


# ── Pre-connect guards ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_order_before_connect_raises() -> None:
    adapter = BinanceLive(api_key="x", api_secret="x", testnet=True)
    from kairos.types import OrderSide, OrderType

    with pytest.raises(RuntimeError, match="connect"):
        await adapter.submit_order(
            symbol="BTCUSDC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
        )


@pytest.mark.asyncio
async def test_cancel_order_before_connect_raises() -> None:
    adapter = BinanceLive(api_key="x", api_secret="x", testnet=True)
    with pytest.raises(RuntimeError, match="connect"):
        await adapter.cancel_order(symbol="BTCUSDC", order_id="o1")


@pytest.mark.asyncio
async def test_get_open_orders_before_connect_raises() -> None:
    adapter = BinanceLive(api_key="x", api_secret="x", testnet=True)
    with pytest.raises(RuntimeError, match="connect"):
        await adapter.get_open_orders()


@pytest.mark.asyncio
async def test_subscribe_bars_before_connect_raises() -> None:
    adapter = BinanceLive(api_key="x", api_secret="x", testnet=True)
    with pytest.raises(RuntimeError, match="connect"):
        await adapter.subscribe_bars("BTCUSDC", "15m")


@pytest.mark.asyncio
async def test_disconnect_when_not_connected_is_noop() -> None:
    """Idempotent: disconnect on a fresh adapter must not raise."""
    adapter = BinanceLive(api_key="x", api_secret="x", testnet=True)
    await adapter.disconnect()  # should silently succeed


# ── Callbacks can be set without connecting ────────────────────


def test_set_callbacks_without_connect() -> None:
    adapter = BinanceLive(api_key="x", api_secret="x", testnet=True)

    async def noop_bar(bar):
        pass

    async def noop_tick(symbol, price):
        pass

    async def noop_fill(fill):
        pass

    async def noop_order(order):
        pass

    async def noop_event(venue):
        pass

    adapter.set_bar_callback(noop_bar)
    adapter.set_tick_callback(noop_tick)
    adapter.set_fill_callback(noop_fill)
    adapter.set_order_update_callback(noop_order)
    adapter.set_disconnect_callback(noop_event)
    adapter.set_reconnect_callback(noop_event)
    # No assertion needed — must just not raise


# ── Subscribe_ticks is a documented stub in v0.2 ───────────────


@pytest.mark.asyncio
async def test_subscribe_ticks_stub_does_not_crash() -> None:
    """v0.2 documents subscribe_ticks as a stub. Should log + no-op."""
    adapter = BinanceLive(api_key="x", api_secret="x", testnet=True)
    # Note: this calls before connect, but since it's a stub it logs and returns
    await adapter.subscribe_ticks("BTCUSDC")
