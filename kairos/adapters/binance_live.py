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
import json
import logging
from typing import Any

from kairos.adapters.base import (
    BarCallback,
    DisconnectCallback,
    FillCallback,
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

# REST + WS endpoints — testnet vs prod
_BINANCE_REST_PROD = "https://api.binance.com"
_BINANCE_REST_TEST = "https://testnet.binance.vision"
_BINANCE_WS_PROD = "wss://stream.binance.com:9443/ws"
_BINANCE_WS_TEST = "wss://stream.testnet.binance.vision/ws"

# Binance WS-API — used for listenKey lifecycle (userDataStream.start /
# .ping / .stop). The legacy REST endpoint `POST /api/v3/userDataStream`
# was retired by Binance (returns 410 Gone from nginx); WS-API is the
# only supported path today and works for both HMAC + Ed25519 keys.
_BINANCE_WS_API_PROD = "wss://ws-api.binance.com:443/ws-api/v3"
_BINANCE_WS_API_TEST = "wss://ws-api.testnet.binance.vision/ws-api/v3"

# Binance sends a listenKey that expires 60 min after its last keepalive.
# We refresh every 30 min per Binance's own recommendation.
_LISTEN_KEY_KEEPALIVE_SECONDS = 30 * 60

# WS-API request/response timeout for listenKey ops. Generous — we only
# hit this on connect, reconnect, or keepalive (every 30 min).
_WS_API_TIMEOUT = 15.0


def _map_binance_order_status(status: str | None) -> OrderStatus:
    """Map Binance's order-status string to our OrderStatus enum."""
    m = {
        "NEW": OrderStatus.ACCEPTED,
        "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
        "FILLED": OrderStatus.FILLED,
        "CANCELED": OrderStatus.CANCELLED,
        "PENDING_CANCEL": OrderStatus.CANCELLED,
        "REJECTED": OrderStatus.REJECTED,
        "EXPIRED": OrderStatus.CANCELLED,
    }
    return m.get(status or "", OrderStatus.SUBMITTED)


def _map_binance_order_type(otype: str | None) -> OrderType:
    """Map Binance's order-type string to our OrderType enum."""
    m = {
        "MARKET": OrderType.MARKET,
        "LIMIT": OrderType.LIMIT,
        "LIMIT_MAKER": OrderType.LIMIT,
        "STOP_LOSS": OrderType.STOP_MARKET,
        "STOP_LOSS_LIMIT": OrderType.STOP_LIMIT,
        "TAKE_PROFIT": OrderType.STOP_MARKET,
        "TAKE_PROFIT_LIMIT": OrderType.STOP_LIMIT,
    }
    return m.get(otype or "", OrderType.MARKET)


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
        self._keepalive_task: asyncio.Task | None = None

        # Reconnect with backoff (pattern adapted from hummingbot v1.25,
        # see CREDITS.md → "WebSocket reconnect with backoff")
        self._reconnect_base_delay: float = 1.0
        self._reconnect_max_delay: float = 60.0

    # ── Endpoint resolution ───────────────────────────────────────

    def _rest_base(self) -> str:
        return _BINANCE_REST_TEST if self._testnet else _BINANCE_REST_PROD

    def _ws_base(self) -> str:
        return _BINANCE_WS_TEST if self._testnet else _BINANCE_WS_PROD

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
        # Propagate any callback registered before connect() so the
        # freshly-constructed inner adapter shares the same slot. RC1.
        if self._on_fill is not None:
            self._rest._fill_callback = self._on_fill
        await self._rest.connect()

        self._market_ws = BinanceWebSocket()
        # Market WS subscriptions are added on demand in subscribe_bars

        # User-data WS — fills + order updates. Set up the listenKey then
        # start the dedicated stream task + keepalive task.
        try:
            self._user_ws_listen_key = await self._fetch_listen_key()
            self._user_ws_task = asyncio.create_task(
                self._run_user_ws(), name="binance-user-ws",
            )
            self._keepalive_task = asyncio.create_task(
                self._keepalive_listen_key(),
                name="binance-listenkey-keepalive",
            )
        except Exception as exc:
            # Testnet historically had issues with listenKey (returns 410).
            # Warn but continue: market data still works, fills will be
            # discovered by reconciliation polling.
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

        if self._keepalive_task is not None:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except (asyncio.CancelledError, Exception):
                pass

        if self._user_ws_task is not None:
            self._user_ws_task.cancel()
            try:
                await self._user_ws_task
            except (asyncio.CancelledError, Exception):
                pass

        # Politely release listenKey if we have one
        if self._user_ws_listen_key is not None:
            try:
                await self._close_listen_key(self._user_ws_listen_key)
            except Exception:
                pass
            self._user_ws_listen_key = None

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
        # Propagate to the inner REST adapter so MARKET orders that fill
        # instantly at submit time (BinanceAdapter.submit_order returning
        # status="closed") still surface a Fill via this callback. RC1
        # regression fix — see openspec/changes/archive/...
        if self._rest is not None:
            self._rest._fill_callback = callback

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

    def _ws_api_url(self) -> str:
        return _BINANCE_WS_API_TEST if self._testnet else _BINANCE_WS_API_PROD

    async def _ws_api_call(self, method: str, params: dict) -> dict:
        """Send one request to the Binance WS-API and return the result.

        Opens a short-lived connection, sends one message, reads one
        reply, closes. Used for listenKey lifecycle (start / ping /
        stop). Raises on non-200 Binance statuses or transport errors.
        """
        import uuid

        import websockets

        request_id = uuid.uuid4().hex
        payload = json.dumps({
            "id": request_id,
            "method": method,
            "params": params,
        })
        async with websockets.connect(
            self._ws_api_url(),
            open_timeout=_WS_API_TIMEOUT,
            close_timeout=_WS_API_TIMEOUT,
            ping_interval=None,  # short-lived, no need
        ) as ws:
            await asyncio.wait_for(ws.send(payload), timeout=_WS_API_TIMEOUT)
            raw = await asyncio.wait_for(ws.recv(), timeout=_WS_API_TIMEOUT)
        msg = json.loads(raw)
        status = msg.get("status")
        if status != 200:
            err = msg.get("error") or {}
            raise RuntimeError(
                f"BinanceLive WS-API {method} failed: status={status} "
                f"code={err.get('code')} msg={err.get('msg')}"
            )
        return msg.get("result") or {}

    async def _fetch_listen_key(self) -> str:
        """Request a Binance listenKey via the WS-API (modern endpoint).

        Replaces the legacy REST ``POST /api/v3/userDataStream`` which
        Binance retired in 2024 (returns 410 Gone from nginx). Works
        for both HMAC and Ed25519 keys.
        """
        result = await self._ws_api_call(
            "userDataStream.start", {"apiKey": self._api_key},
        )
        key = result.get("listenKey")
        if not key:
            raise RuntimeError(
                f"BinanceLive: listenKey missing from WS-API response: {result}"
            )
        logger.debug(f"BinanceLive: fetched listenKey ({len(key)} chars) via WS-API")
        return key

    async def _keepalive_listen_key(self) -> None:
        """Ping Binance every 30 min to keep the listenKey alive."""
        while self._connected and self._user_ws_listen_key is not None:
            try:
                await asyncio.sleep(_LISTEN_KEY_KEEPALIVE_SECONDS)
            except asyncio.CancelledError:
                return
            if not self._connected or self._user_ws_listen_key is None:
                return
            try:
                await self._ws_api_call(
                    "userDataStream.ping",
                    {
                        "apiKey": self._api_key,
                        "listenKey": self._user_ws_listen_key,
                    },
                )
                logger.debug("BinanceLive: listenKey keepalive OK")
            except Exception as exc:
                # Don't kill the task — keep trying. If the key is truly
                # dead, _user_ws_session will reconnect with a fresh one.
                logger.warning(f"BinanceLive: listenKey keepalive failed: {exc}")

    async def _close_listen_key(self, listen_key: str) -> None:
        """Stop the listenKey (polite cleanup on disconnect)."""
        try:
            await self._ws_api_call(
                "userDataStream.stop",
                {"apiKey": self._api_key, "listenKey": listen_key},
            )
        except Exception as exc:
            logger.debug(f"BinanceLive: listenKey stop failed (ignored): {exc}")

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
        """One iteration of the user-data WS — open, drain, exit on close.

        Connects to ``wss://.../ws/{listenKey}``, reads frames until the
        socket closes, and dispatches each ``executionReport`` event to
        the fill + order-update callbacks. Returning from this coroutine
        signals ``_run_user_ws`` to reconnect with a fresh listenKey.
        """
        import websockets

        # Ensure we have a fresh listenKey on every session (after reconnect
        # the old key may be invalidated). No-op if one already exists.
        if self._user_ws_listen_key is None:
            self._user_ws_listen_key = await self._fetch_listen_key()

        url = f"{self._ws_base()}/{self._user_ws_listen_key}"
        logger.info(
            f"BinanceLive: user-data WS connecting (testnet={self._testnet})"
        )

        async with websockets.connect(
            url, ping_interval=30, ping_timeout=10,
        ) as ws:
            logger.info("BinanceLive: user-data WS connected")
            async for raw in ws:
                if not self._connected:
                    break
                try:
                    await self._process_user_ws_message(raw)
                except Exception:
                    # Log + continue — one bad frame shouldn't tear down WS
                    logger.exception(
                        "BinanceLive: error processing user-data frame"
                    )

        # WS closed — let the caller reconnect. Invalidate our listenKey
        # so the next session fetches a fresh one.
        self._user_ws_listen_key = None

    async def _process_user_ws_message(self, raw: str | bytes) -> None:
        """Parse one user-data WS frame; emit Fill + Order updates.

        Binance ``executionReport`` fields (spot stream) — keys we care about:
        ``e`` event type, ``s`` symbol, ``S`` side, ``o`` order type,
        ``X`` current order status, ``x`` current execution type,
        ``i`` order id, ``t`` trade id, ``L`` last executed price,
        ``l`` last executed qty, ``n`` commission, ``T`` transaction time,
        ``q`` original qty, ``p`` original price.

        Spec: https://developers.binance.com/docs/binance-spot-api-docs/user-data-stream
        """
        data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        if data.get("e") != "executionReport":
            # Ignore outboundAccountPosition, balanceUpdate, listStatus etc.
            return

        symbol = data.get("s", "")
        side = OrderSide.BUY if data.get("S") == "BUY" else OrderSide.SELL
        exec_type = data.get("x")       # NEW, TRADE, CANCELED, EXPIRED, REJECTED
        order_status = data.get("X")    # NEW, PARTIALLY_FILLED, FILLED, ...

        # A fill arrives when exec_type == "TRADE". Binance emits one frame
        # per execution, including partial fills.
        if exec_type == "TRADE" and self._on_fill is not None:
            last_qty = float(data.get("l", 0) or 0)
            last_price = float(data.get("L", 0) or 0)
            if last_qty > 0 and last_price > 0:
                fill = Fill(
                    order_id=str(data.get("i", "")),
                    trade_id=str(data.get("t", "")),
                    symbol=symbol,
                    side=side,
                    price=last_price,
                    quantity=last_qty,
                    commission=float(data.get("n", 0) or 0),
                    timestamp=int(data.get("T", 0) or 0),
                )
                await self._on_fill(fill)

        # Emit an order-state update on every frame (NEW → ACCEPTED,
        # TRADE → PARTIALLY_FILLED / FILLED, CANCELED → CANCELLED, etc).
        if self._on_order_update is not None:
            order = Order(
                id=str(data.get("i", "")),
                symbol=symbol,
                side=side,
                type=_map_binance_order_type(data.get("o")),
                quantity=float(data.get("q", 0) or 0),
                price=float(data.get("p", 0) or 0) or None,
                status=_map_binance_order_status(order_status),
            )
            await self._on_order_update(order)
