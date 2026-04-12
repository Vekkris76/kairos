"""Integration tests for LiveEngine + adapter wiring (v0.2.1)."""

from __future__ import annotations

import asyncio

import pytest

from kairos import LiveEngine, LiveStrategy, MarketCache, TestClock
from kairos.actors import ActorConfig
from kairos.adapters.base import LiveAdapter
from kairos.types import (
    Bar,
    Fill,
    Instrument,
    Order,
    OrderSide,
    OrderStatus,
)


pytestmark = pytest.mark.asyncio


def _bar(symbol: str = "BTCUSDC", tf: str = "15m", close: float = 50_000.0) -> Bar:
    return Bar(
        symbol=symbol, timeframe=tf, timestamp=0,
        open=close - 10, high=close + 20, low=close - 30, close=close, volume=100.0,
    )


def _fill(symbol: str = "BTCUSDC", side: OrderSide = OrderSide.BUY, qty: float = 0.1) -> Fill:
    return Fill(
        order_id="o1", trade_id="t1", symbol=symbol, side=side,
        price=50_000.0, quantity=qty, commission=0.0, timestamp=0,
    )


class MockAdapter:
    """Fully wired LiveAdapter Protocol implementation for tests.

    The engine's ``register_adapter`` calls ``set_*_callback`` on this mock
    once. Tests then use ``await self.emit_bar(...)`` etc. to inject events
    that flow through the engine just like real adapter events would.
    """

    venue_id: str = "mock"

    def __init__(self) -> None:
        self._connected: bool = False
        self.bar_cb = None
        self.tick_cb = None
        self.fill_cb = None
        self.order_cb = None
        self.disconnect_cb = None
        self.reconnect_cb = None
        self.subscriptions: list[tuple[str, str]] = []
        self.submitted_orders: list[dict] = []

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    def set_bar_callback(self, cb): self.bar_cb = cb
    def set_tick_callback(self, cb): self.tick_cb = cb
    def set_fill_callback(self, cb): self.fill_cb = cb
    def set_order_update_callback(self, cb): self.order_cb = cb
    def set_disconnect_callback(self, cb): self.disconnect_cb = cb
    def set_reconnect_callback(self, cb): self.reconnect_cb = cb

    async def subscribe_bars(self, symbol: str, timeframe: str) -> None:
        self.subscriptions.append((symbol, timeframe))

    async def subscribe_ticks(self, symbol: str) -> None:
        pass

    async def submit_order(self, **kwargs) -> Order:
        self.submitted_orders.append(kwargs)
        return Order(
            id=f"mock-{len(self.submitted_orders)}",
            symbol=kwargs["symbol"],
            side=kwargs["side"],
            type=kwargs["order_type"],
            quantity=kwargs["quantity"],
            price=kwargs.get("price"),
            stop_price=kwargs.get("stop_price"),
            status=OrderStatus.ACCEPTED,
        )

    async def cancel_order(self, *, symbol: str, order_id: str) -> bool:
        return True

    async def get_open_orders(self, *, symbol: str | None = None) -> list[Order]:
        return []

    async def get_balances(self) -> dict[str, float]:
        return {"USDC": 1000.0}

    async def get_instrument(self, symbol: str) -> Instrument:
        return Instrument(
            symbol=symbol, base="BTC", quote="USDC",
            min_qty=0.00001, max_qty=9000, qty_step=0.00001,
            min_notional=10.0, price_precision=2, qty_precision=5,
        )

    # ── Test helpers ──────────────────────────────────────────

    async def emit_bar(self, bar: Bar) -> None:
        if self.bar_cb is not None:
            await self.bar_cb(bar)

    async def emit_tick(self, symbol: str, price: float) -> None:
        if self.tick_cb is not None:
            await self.tick_cb(symbol, price)

    async def emit_fill(self, fill: Fill) -> None:
        if self.fill_cb is not None:
            await self.fill_cb(fill)

    async def emit_disconnect(self) -> None:
        if self.disconnect_cb is not None:
            await self.disconnect_cb(self.venue_id)

    async def emit_reconnect(self) -> None:
        if self.reconnect_cb is not None:
            await self.reconnect_cb(self.venue_id)


class _RecordingStrategy(LiveStrategy):
    def __init__(self, config: ActorConfig) -> None:
        super().__init__(config)
        self.add_ema(2, "fast")
        self.bars: list = []
        self.fills: list = []

    def on_bar_ready(self, bar) -> None:  # noqa: ANN001
        self.bars.append(bar)

    def on_order_filled(self, fill) -> None:  # noqa: ANN001
        self.fills.append(fill)


# ── Adapter satisfies LiveAdapter Protocol ──────────────────


def test_mock_adapter_satisfies_protocol() -> None:
    adapter = MockAdapter()
    assert isinstance(adapter, LiveAdapter)


# ── Adapter → Cache wiring ──────────────────────────────────


async def test_bars_from_adapter_flow_into_cache_and_bus() -> None:
    cache = MarketCache()
    engine = LiveEngine(clock=TestClock(), cache=cache)
    adapter = MockAdapter()
    engine.register_adapter(adapter)

    strategy = _RecordingStrategy(ActorConfig())
    strategy.symbol = "BTCUSDC"
    strategy.timeframe = "15m"
    engine.add_strategy(strategy)

    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.05)

    # Adapter should have been subscribed to (BTCUSDC, 15m)
    assert ("BTCUSDC", "15m") in adapter.subscriptions

    # Emit 3 bars through the adapter — they flow into cache + bus
    for close in (100, 101, 102):
        await adapter.emit_bar(_bar(close=close))
    await asyncio.sleep(0.05)

    # Cache populated
    assert cache.bar_count("BTCUSDC", "15m") == 3
    assert cache.last_bar("BTCUSDC", "15m").close == 102

    # Strategy received the warm-up + 1 ready call (EMA(2) needs 2 bars)
    assert len(strategy.bars) >= 2

    engine.stop()
    await task


async def test_fills_from_adapter_flow_into_cache_and_bus() -> None:
    cache = MarketCache()
    engine = LiveEngine(clock=TestClock(), cache=cache)
    adapter = MockAdapter()
    engine.register_adapter(adapter)

    strategy = _RecordingStrategy(ActorConfig())
    strategy.symbol = "BTCUSDC"
    strategy.timeframe = "15m"
    engine.add_strategy(strategy)

    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.05)

    await adapter.emit_fill(_fill(qty=0.1))
    await asyncio.sleep(0.05)

    # Cache: position recorded
    pos = cache.position("BTCUSDC")
    assert pos is not None
    assert pos.quantity == 0.1
    # Strategy received the fill
    assert len(strategy.fills) == 1

    engine.stop()
    await task


async def test_ticks_from_adapter_update_cache() -> None:
    cache = MarketCache()
    engine = LiveEngine(clock=TestClock(), cache=cache)
    adapter = MockAdapter()
    engine.register_adapter(adapter)

    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.02)

    await adapter.emit_tick("BTCUSDC", 50_500.0)
    await asyncio.sleep(0.02)

    assert cache.last_tick("BTCUSDC") == 50_500.0
    assert cache.last_price("BTCUSDC") == 50_500.0

    engine.stop()
    await task


async def test_adapter_disconnect_reconnect_publishes_signals() -> None:
    """Engine should re-publish adapter lifecycle events to the bus
    so actors (e.g. ProtectionActor) can react."""
    cache = MarketCache()
    engine = LiveEngine(clock=TestClock(), cache=cache)
    adapter = MockAdapter()
    engine.register_adapter(adapter)

    # An actor that records adapter events
    received_disconnect: list[str] = []
    received_reconnect: list[str] = []

    from kairos.actors import Actor

    class _LifecycleActor(Actor):
        def on_adapter_disconnected(self, venue_id):
            received_disconnect.append(venue_id)

        def on_adapter_reconnected(self, venue_id):
            received_reconnect.append(venue_id)

    listener = _LifecycleActor(ActorConfig())
    engine.add_actor(
        listener, events={"adapter_disconnected", "adapter_reconnected"},
    )

    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.05)

    await adapter.emit_disconnect()
    await asyncio.sleep(0.05)
    await adapter.emit_reconnect()
    await asyncio.sleep(0.05)

    assert received_disconnect == ["mock"]
    assert received_reconnect == ["mock"]

    engine.stop()
    await task


# ── Multiple adapters / multiple strategies ──────────────────


async def test_multiple_adapters_share_bus_and_cache() -> None:
    cache = MarketCache()
    engine = LiveEngine(clock=TestClock(), cache=cache)
    adapter_a = MockAdapter()
    adapter_b = MockAdapter()
    adapter_b.venue_id = "mock-b"
    engine.register_adapter(adapter_a)
    engine.register_adapter(adapter_b)

    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.05)

    await adapter_a.emit_bar(_bar(symbol="BTCUSDC", close=100))
    await adapter_b.emit_bar(_bar(symbol="ETHUSDC", close=3000))
    await asyncio.sleep(0.05)

    assert cache.bar_count("BTCUSDC", "15m") == 1
    assert cache.bar_count("ETHUSDC", "15m") == 1

    engine.stop()
    await task


# ── Adapter registration safety ──────────────────────────────


async def test_cannot_register_adapter_when_running() -> None:
    engine = LiveEngine(clock=TestClock())
    adapter = MockAdapter()

    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.02)
    with pytest.raises(RuntimeError, match="while engine is running"):
        engine.register_adapter(adapter)
    engine.stop()
    await task
