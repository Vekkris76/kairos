"""LiveAdapter — protocol for venue adapters that integrate with LiveEngine.

A LiveAdapter is the bridge between an exchange (Binance, Kraken, etc.) and
the Kairos LiveEngine. It does three things:

1. **Connect & authenticate**: REST + WebSocket sessions to the venue
2. **Stream events into the engine's event bus**: bars, ticks, fills,
   order updates, account changes — pushed via callbacks the engine wires
3. **Execute orders & queries**: submit, cancel, query open orders, fetch
   instrument metadata, fetch balances

This module defines the *protocol*. Concrete implementations live in
``kairos.adapters.binance_live`` (Binance Spot) and follow-ups for other
venues. A LiveEngine can register multiple adapters (multi-venue), though
v0.2.0 ships with just Binance.

The protocol is async throughout — adapters must not block.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Protocol, runtime_checkable

from kairos.types import (
    Bar,
    Fill,
    Instrument,
    Order,
    OrderSide,
    OrderType,
    TimeInForce,
)

# Callback shapes the engine provides to the adapter.
# All are async — adapters await them after wiring an event from the venue.
BarCallback = Callable[[Bar], Awaitable[None]]
TickCallback = Callable[[str, float], Awaitable[None]]   # (symbol, price)
FillCallback = Callable[[Fill], Awaitable[None]]
OrderUpdateCallback = Callable[[Order], Awaitable[None]]
DisconnectCallback = Callable[[str], Awaitable[None]]      # (venue_id,)
ReconnectCallback = Callable[[str], Awaitable[None]]


@runtime_checkable
class LiveAdapter(Protocol):
    """Live-trading adapter contract.

    Implementors expose the venue's market data and execution surface to
    the LiveEngine. The engine owns the lifecycle: it calls ``connect``,
    wires its callbacks via the ``set_*_callback`` methods, then drives
    ``subscribe_bars``/``subscribe_ticks`` based on registered strategies.
    """

    @property
    def venue_id(self) -> str:
        """Stable identifier for this adapter (e.g. 'binance', 'kraken')."""
        ...

    # ── Lifecycle ─────────────────────────────────────────────────

    async def connect(self) -> None:
        """Establish REST + WebSocket sessions. Idempotent."""
        ...

    async def disconnect(self) -> None:
        """Close all sessions. Safe to call before connect or twice."""
        ...

    @property
    def connected(self) -> bool: ...

    # ── Callbacks (engine sets these once, before connect) ────────

    def set_bar_callback(self, callback: BarCallback) -> None: ...
    def set_tick_callback(self, callback: TickCallback) -> None: ...
    def set_fill_callback(self, callback: FillCallback) -> None: ...
    def set_order_update_callback(self, callback: OrderUpdateCallback) -> None: ...
    def set_disconnect_callback(self, callback: DisconnectCallback) -> None: ...
    def set_reconnect_callback(self, callback: ReconnectCallback) -> None: ...

    # ── Subscriptions ─────────────────────────────────────────────

    async def subscribe_bars(self, symbol: str, timeframe: str) -> None: ...
    async def subscribe_ticks(self, symbol: str) -> None: ...

    # ── Execution ─────────────────────────────────────────────────

    async def submit_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: float | None = None,
        stop_price: float | None = None,
        time_in_force: TimeInForce = TimeInForce.GTC,
        post_only: bool = False,
        reduce_only: bool = False,
        client_order_id: str | None = None,
    ) -> Order: ...

    async def cancel_order(self, *, symbol: str, order_id: str) -> bool: ...

    # ── Queries ───────────────────────────────────────────────────

    async def get_open_orders(self, *, symbol: str | None = None) -> list[Order]: ...
    async def get_balances(self) -> dict[str, float]: ...
    async def get_instrument(self, symbol: str) -> Instrument: ...
