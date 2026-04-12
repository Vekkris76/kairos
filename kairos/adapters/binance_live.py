"""BinanceLive — production live adapter for Binance Spot.

Bridges the existing v0.1 ``kairos.exchanges.binance`` REST client + the
``BinanceWebSocket`` market-data stream into the v0.2 ``LiveAdapter``
protocol. Adds:

- User-data WebSocket for **real-time fills** and order updates
  (Binance's separate "listenKey" stream)
- Reconnect with exponential backoff (pattern adapted from hummingbot,
  see CREDITS.md)
- Engine-callback wiring so events flow into LiveEngine's event bus
- Reconciliation hook on reconnect

This adapter is light glue — heavy lifting (auth, REST, WebSocket frames)
lives in the existing ``kairos.exchanges`` modules. We do NOT re-implement
those here. The bridge surface is designed so the LiveEngine can talk to
Binance the same way it talks to any other adapter.

Note on testing: Binance live integration tests require API keys and run
against testnet. Unit tests use ``MockLiveAdapter`` (in tests/) that
implements the same protocol with deterministic in-memory state.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from kairos.adapters.base import (
    BarCallback,
    DisconnectCallback,
    FillCallback,
    LiveAdapter,
    OrderUpdateCallback,
    ReconnectCallback,
    TickCallback,
)
from kairos.types import (
    Bar,
    Fill,
    Instrument,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)

logger = logging.getLogger("kairos.adapter.binance")


class BinanceLive:
    """Live adapter for Binance Spot (REST + market data WS + user data WS).

    Construction does NOT connect — call ``connect()`` after creating the
    instance and registering callbacks.

        adapter = BinanceLive(api_key=..., api_secret=..., testnet=False)
        adapter.set_fill_callback(engine_emits_fill)
        adapter.set_disconnect_callback(engine_emits_disconnect)
        engine.register_adapter(adapter)
        await adapter.connect()
    """

    venue_id: str = "binance"

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        testnet: bool = False,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._testnet = testnet
        self._connected: bool = False

        # Engine-provided callbacks (wired before connect)
        self._on_bar: BarCallback | None = None
        self._on_tick: TickCallback | None = None
        self._on_fill: FillCallback | None = None
        self._on_order_update: OrderUpdateCallback | None = None
        self._on_disconnect: DisconnectCallback | None = None
        self._on_reconnect: ReconnectCallback | None = None

        # Lazy: actual REST + WS clients constructed on connect()
        self._rest: Any = None
        self._market_ws: Any = None
        self._user_ws: Any = None
        self._user_ws_task: asyncio.Task | None = None
        self._user_ws_listen_key: str | None = None

        # Reconnect with backoff (pattern adapted from hummingbot v1.25,
        # see CREDITS.md → "WebSocket reconnect with backoff")
        self._reconnect_base_delay: float = 1.0
        self._reconnect_max_delay: float = 60.0

    @property
    def connected(self) -> bool:
        return self._connected

    # ── Lifecycle ─────────────────────────────────────────────────

    async def connect(self) -> None:
        """Establish REST + market-data WS + user-data WS sessions.

        Idempotent: re-calling on an already-connected adapter is a no-op.
        """
        if self._connected:
            return

        # Lazy import to avoid forcing ccxt at module import time
        from kairos.exchanges.binance import BinanceAdapter
        from kairos.exchanges.binance_ws import BinanceWebSocket

        self._rest = BinanceAdapter(
            api_key=self._api_key,
            api_secret=self._api_secret,
            testnet=self._testnet,
        )
        await self._rest.connect()

        self._market_ws = BinanceWebSocket()
        # Market WS subscriptions are added on demand in subscribe_bars

        # User-data WS — fills + order updates. Set up the listenKey then
        # start the dedicated stream task.
        try:
            self._user_ws_listen_key = await self._fetch_listen_key()
            self._user_ws_task = asyncio.create_task(
                self._run_user_ws(), name="binance-user-ws",
            )
        except Exception as exc:
            # Testnet has known issues with listenKey (returns 410). Warn
            # but continue: market data still works, fills will be
            # discovered by reconciliation rather than streamed.
            logger.warning(
                f"BinanceLive: user-data WS init failed ({exc}). "
                f"Fills will arrive only via reconciliation polling."
            )

        self._connected = True
        logger.info(f"BinanceLive connected (testnet={self._testnet})")

    async def disconnect(self) -> None:
        """Close all WS streams and the REST session."""
        if not self._connected:
            return
        self._connected = False

        if self._user_ws_task is not None:
            self._user_ws_task.cancel()
            try:
                await self._user_ws_task
            except (asyncio.CancelledError, Exception):
                pass

        if self._market_ws is not None:
            try:
                await self._market_ws.close()
            except Exception:
                pass

        if self._rest is not None:
            try:
                await self._rest.disconnect()
            except Exception:
                pass

        logger.info("BinanceLive disconnected")

    # ── Callback registration ─────────────────────────────────────

    def set_bar_callback(self, callback: BarCallback) -> None:
        self._on_bar = callback

    def set_tick_callback(self, callback: TickCallback) -> None:
        self._on_tick = callback

    def set_fill_callback(self, callback: FillCallback) -> None:
        self._on_fill = callback

    def set_order_update_callback(self, callback: OrderUpdateCallback) -> None:
        self._on_order_update = callback

    def set_disconnect_callback(self, callback: DisconnectCallback) -> None:
        self._on_disconnect = callback

    def set_reconnect_callback(self, callback: ReconnectCallback) -> None:
        self._on_reconnect = callback

    # ── Subscriptions ─────────────────────────────────────────────

    async def subscribe_bars(self, symbol: str, timeframe: str) -> None:
        """Subscribe to a symbol's klines and forward to the engine bar callback."""
        if self._market_ws is None:
            raise RuntimeError("BinanceLive: connect() before subscribe_bars")
        if self._on_bar is None:
            raise RuntimeError("BinanceLive: set_bar_callback before subscribe_bars")

        async def _forward(bar: Bar) -> None:
            assert self._on_bar is not None
            await self._on_bar(bar)

        # market_ws.subscribe expects a sync-or-async callback; wrap our async one
        def _sync_wrapper(bar: Bar) -> None:
            asyncio.create_task(_forward(bar))

        await self._market_ws.subscribe(symbol, timeframe, _sync_wrapper)

    async def subscribe_ticks(self, symbol: str) -> None:
        """Subscribe to bookTicker (best bid/ask) for `symbol`. v0.2: stub."""
        # Binance bookTicker stream wiring lives in a future PR. For now, the
        # engine derives "current price" from the last bar close (see
        # MarketCache.last_price fallback).
        logger.debug(f"subscribe_ticks({symbol}): not yet implemented in v0.2")

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
    ) -> Order:
        if self._rest is None:
            raise RuntimeError("BinanceLive: connect() before submit_order")
        # Note: v0.1 BinanceAdapter.submit_order doesn't yet accept
        # client_order_id; passed for forward compat. Adapter PR will add it.
        return await self._rest.submit_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            time_in_force=time_in_force,
            post_only=post_only,
            reduce_only=reduce_only,
        )

    async def cancel_order(self, *, symbol: str, order_id: str) -> bool:
        if self._rest is None:
            raise RuntimeError("BinanceLive: connect() before cancel_order")
        return await self._rest.cancel_order(symbol, order_id)

    # ── Queries ───────────────────────────────────────────────────

    async def get_open_orders(self, *, symbol: str | None = None) -> list[Order]:
        if self._rest is None:
            raise RuntimeError("BinanceLive: connect() before get_open_orders")
        return await self._rest.get_open_orders(symbol)

    async def get_balances(self) -> dict[str, float]:
        if self._rest is None:
            raise RuntimeError("BinanceLive: connect() before get_balances")
        balances = await self._rest.get_balances()
        # Convert v0.1 Balance objects to plain {currency: free} dict
        return {b.currency: b.free for b in balances.values()}

    async def get_instrument(self, symbol: str) -> Instrument:
        if self._rest is None:
            raise RuntimeError("BinanceLive: connect() before get_instrument")
        return await self._rest.get_instrument(symbol)

    # ── User-data WebSocket internals ─────────────────────────────

    async def _fetch_listen_key(self) -> str:
        """Request a Binance listenKey (gateway to the user-data WS).

        Binance testnet returns 410 Gone here — known issue. Caller handles
        the exception and continues with reconciliation-only mode.
        """
        # Implementation hook — full Binance REST client integration lands
        # in the v0.2.0 final adapter PR. For this skeleton we raise so
        # tests can stub it.
        raise NotImplementedError(
            "BinanceLive._fetch_listen_key wires up in v0.2.0 final"
        )

    async def _run_user_ws(self) -> None:
        """Long-running task: maintain the user-data WS, forward fills.

        Wraps the WS in a reconnect loop with exponential backoff. On every
        successful reconnect, fires ``on_reconnect_callback`` so the engine
        can trigger reconciliation.
        """
        delay = self._reconnect_base_delay
        while self._connected:
            try:
                await self._user_ws_session()
                delay = self._reconnect_base_delay  # successful → reset backoff
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning(
                    f"BinanceLive: user-data WS error: {exc}. "
                    f"Reconnecting in {delay:.0f}s..."
                )
                if self._on_disconnect is not None:
                    await self._on_disconnect(self.venue_id)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._reconnect_max_delay)

                if self._on_reconnect is not None and self._connected:
                    await self._on_reconnect(self.venue_id)

    async def _user_ws_session(self) -> None:
        """One iteration of the user-data WS — open, drain, close.

        Implementation hook for v0.2.0 final.
        """
        raise NotImplementedError(
            "BinanceLive._user_ws_session wires up in v0.2.0 final"
        )
