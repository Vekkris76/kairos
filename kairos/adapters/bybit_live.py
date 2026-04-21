"""BybitLive — production live adapter for Bybit Spot (v5 API).

Implements the ``LiveAdapter`` protocol against Bybit's v5 unified trading
API. Mirrors the shape of :mod:`kairos.adapters.binance_live` but without
a preexisting v0.1 ``kairos.exchanges.bybit`` client — REST is done
directly with ``httpx.AsyncClient`` and WebSocket with ``websockets``.

Key differences vs Binance:

- Auth is HMAC-SHA256 over ``timestamp + api_key + recv_window + params``
  for REST, and over ``GET/realtime<expires>`` for the private WS.
- No listenKey lifecycle. Private WS authenticates with an ``auth`` op
  frame then subscribes to ``"order"`` for fills and order updates.
- Kline WS frames carry a ``confirm`` flag — we only emit a :class:`Bar`
  when ``confirm == True`` (a bar is closed). Intermediate ticks are
  ignored.

Testing: unit tests exercise the WS parsers and pure helpers
(:func:`_bybit_interval`, :func:`_map_bybit_order_status`,
:func:`_map_bybit_order_type`). Network paths are covered by the manual
testnet smoke runbook.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
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

logger = logging.getLogger("kairos.adapter.bybit")

# REST + WS endpoints — testnet vs prod
_BYBIT_REST_PROD = "https://api.bybit.com"
_BYBIT_REST_TEST = "https://api-testnet.bybit.com"
_BYBIT_WS_PUB_PROD = "wss://stream.bybit.com/v5/public/spot"
_BYBIT_WS_PUB_TEST = "wss://stream-testnet.bybit.com/v5/public/spot"
_BYBIT_WS_PRIV_PROD = "wss://stream.bybit.com/v5/private"
_BYBIT_WS_PRIV_TEST = "wss://stream-testnet.bybit.com/v5/private"

_BYBIT_RECV_WINDOW = 5000
# Bybit requires a client-side ping every 20s on both public + private WS.
_BYBIT_PING_INTERVAL = 20.0
_BYBIT_REST_TIMEOUT = 10.0

# Canonical timeframe -> Bybit interval string.
_BYBIT_INTERVALS: dict[str, str] = {
    "1m": "1",
    "3m": "3",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "2h": "120",
    "4h": "240",
    "6h": "360",
    "12h": "720",
    "1d": "D",
    "1w": "W",
    "1M": "M",
}


def _bybit_interval(timeframe: str) -> str:
    """Translate a canonical timeframe (``"4h"``) to Bybit's ``"240"``."""
    iv = _BYBIT_INTERVALS.get(timeframe)
    if iv is None:
        raise ValueError(f"BybitLive: unsupported timeframe {timeframe!r}")
    return iv


def _map_bybit_order_status(status: str | None) -> OrderStatus:
    """Map Bybit's ``orderStatus`` string to our :class:`OrderStatus` enum."""
    m = {
        "New": OrderStatus.ACCEPTED,
        "PartiallyFilled": OrderStatus.PARTIALLY_FILLED,
        "Filled": OrderStatus.FILLED,
        "Cancelled": OrderStatus.CANCELLED,
        "PendingCancel": OrderStatus.CANCELLED,
        "Rejected": OrderStatus.REJECTED,
    }
    return m.get(status or "", OrderStatus.SUBMITTED)


def _map_bybit_order_type(otype: str | None) -> OrderType:
    """Map Bybit's ``orderType`` string to our :class:`OrderType` enum."""
    m = {
        "Market": OrderType.MARKET,
        "Limit": OrderType.LIMIT,
        "StopMarket": OrderType.STOP_MARKET,
        "StopLimit": OrderType.STOP_LIMIT,
    }
    return m.get(otype or "", OrderType.MARKET)


class BybitLive:
    """Live adapter for Bybit Spot (v5 unified API).

    Construction does NOT connect — call :meth:`connect` after creating
    the instance and registering callbacks::

        adapter = BybitLive(api_key=..., api_secret=..., testnet=False)
        adapter.set_fill_callback(engine_emits_fill)
        engine.register_adapter(adapter)
        await adapter.connect()
    """

    venue_id: str = "bybit"

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

        self._on_bar: BarCallback | None = None
        self._on_tick: TickCallback | None = None
        self._on_fill: FillCallback | None = None
        self._on_order_update: OrderUpdateCallback | None = None
        self._on_disconnect: DisconnectCallback | None = None
        self._on_reconnect: ReconnectCallback | None = None

        # Lazy: HTTP + WS clients constructed on connect()
        self._http: Any = None
        self._market_ws_task: asyncio.Task | None = None
        self._private_ws_task: asyncio.Task | None = None

        # topic -> (symbol, timeframe). Populated by subscribe_bars, consulted
        # by _process_market_ws_message to build Bar objects with the
        # canonical timeframe string instead of Bybit's "240" / "D".
        self._bar_subscriptions: dict[str, tuple[str, str]] = {}

        # Live sockets (set inside *_ws_session)
        self._market_ws: Any = None
        self._private_ws: Any = None

        self._reconnect_base_delay: float = 1.0
        self._reconnect_max_delay: float = 60.0

    # ── Endpoint resolution ───────────────────────────────────────

    def _rest_base(self) -> str:
        return _BYBIT_REST_TEST if self._testnet else _BYBIT_REST_PROD

    def _ws_public_url(self) -> str:
        return _BYBIT_WS_PUB_TEST if self._testnet else _BYBIT_WS_PUB_PROD

    def _ws_private_url(self) -> str:
        return _BYBIT_WS_PRIV_TEST if self._testnet else _BYBIT_WS_PRIV_PROD

    @property
    def connected(self) -> bool:
        return self._connected

    # ── Auth helpers ──────────────────────────────────────────────

    def _sign(self, timestamp: int, params_str: str) -> str:
        """HMAC-SHA256 over ``timestamp + api_key + recv_window + params``."""
        msg = f"{timestamp}{self._api_key}{_BYBIT_RECV_WINDOW}{params_str}"
        return hmac.new(
            self._api_secret.encode(),
            msg.encode(),
            hashlib.sha256,
        ).hexdigest()

    def _auth_headers(self, params_str: str) -> dict[str, str]:
        """Build the five ``X-BAPI-*`` headers Bybit expects on auth'd calls."""
        ts = int(time.time() * 1000)
        return {
            "X-BAPI-API-KEY": self._api_key,
            "X-BAPI-SIGN": self._sign(ts, params_str),
            "X-BAPI-TIMESTAMP": str(ts),
            "X-BAPI-RECV-WINDOW": str(_BYBIT_RECV_WINDOW),
            "Content-Type": "application/json",
        }

    # ── Lifecycle ─────────────────────────────────────────────────

    async def connect(self) -> None:
        """Establish HTTP client + public market WS + private WS."""
        if self._connected:
            return

        import httpx

        self._http = httpx.AsyncClient(
            base_url=self._rest_base(),
            timeout=_BYBIT_REST_TIMEOUT,
        )
        self._connected = True

        self._market_ws_task = asyncio.create_task(
            self._run_market_ws(), name="bybit-market-ws",
        )
        self._private_ws_task = asyncio.create_task(
            self._run_private_ws(), name="bybit-private-ws",
        )

        logger.info(f"BybitLive connected (testnet={self._testnet})")

    async def disconnect(self) -> None:
        """Close all WS streams and the REST session."""
        if not self._connected:
            return
        self._connected = False

        for task in (self._market_ws_task, self._private_ws_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        if self._http is not None:
            try:
                await self._http.aclose()
            except Exception:
                pass

        logger.info("BybitLive disconnected")

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
        """Subscribe to ``kline.<interval>.<symbol>`` on the market WS."""
        if not self._connected:
            raise RuntimeError("BybitLive: connect() before subscribe_bars")
        if self._on_bar is None:
            raise RuntimeError("BybitLive: set_bar_callback before subscribe_bars")

        iv = _bybit_interval(timeframe)
        topic = f"kline.{iv}.{symbol}"
        self._bar_subscriptions[topic] = (symbol, timeframe)

        # If the market WS is already connected, push the subscribe frame
        # now. Otherwise the session loop replays _bar_subscriptions on
        # (re)connect.
        if self._market_ws is not None:
            await self._market_ws.send(
                json.dumps({"op": "subscribe", "args": [topic]})
            )

    async def subscribe_ticks(self, symbol: str) -> None:
        """Bookticker subscription. v0.4: stub (same shape as BinanceLive)."""
        logger.debug(f"subscribe_ticks({symbol}): not yet implemented in v0.4")

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
        if self._http is None:
            raise RuntimeError("BybitLive: connect() before submit_order")

        body: dict[str, Any] = {
            "category": "spot",
            "symbol": symbol,
            "side": "Buy" if side == OrderSide.BUY else "Sell",
            "orderType": "Market" if order_type == OrderType.MARKET else "Limit",
            "qty": str(quantity),
            "timeInForce": time_in_force.value,
        }
        if order_type == OrderType.LIMIT and price is not None:
            body["price"] = str(price)
        if client_order_id is not None:
            body["orderLinkId"] = client_order_id

        body_str = json.dumps(body, separators=(",", ":"))
        headers = self._auth_headers(body_str)
        resp = await self._http.post("/v5/order/create", headers=headers, content=body_str)
        resp.raise_for_status()
        data = resp.json()
        if data.get("retCode") != 0:
            raise RuntimeError(
                f"BybitLive submit_order failed: {data.get('retMsg')} "
                f"(retCode={data.get('retCode')})"
            )
        result = data.get("result") or {}
        return Order(
            id=str(result.get("orderId", "")),
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            time_in_force=time_in_force,
            status=OrderStatus.SUBMITTED,
            post_only=post_only,
            reduce_only=reduce_only,
        )

    async def cancel_order(self, *, symbol: str, order_id: str) -> bool:
        if self._http is None:
            raise RuntimeError("BybitLive: connect() before cancel_order")
        body = {"category": "spot", "symbol": symbol, "orderId": order_id}
        body_str = json.dumps(body, separators=(",", ":"))
        headers = self._auth_headers(body_str)
        resp = await self._http.post("/v5/order/cancel", headers=headers, content=body_str)
        resp.raise_for_status()
        data = resp.json()
        return data.get("retCode") == 0

    # ── Queries ───────────────────────────────────────────────────

    async def get_open_orders(self, *, symbol: str | None = None) -> list[Order]:
        if self._http is None:
            raise RuntimeError("BybitLive: connect() before get_open_orders")
        params: dict[str, Any] = {"category": "spot", "openOnly": 1}
        if symbol is not None:
            params["symbol"] = symbol
        # GET params are signed as the querystring in key-sorted order.
        params_str = "&".join(f"{k}={params[k]}" for k in sorted(params))
        headers = self._auth_headers(params_str)
        resp = await self._http.get("/v5/order/realtime", headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        if data.get("retCode") != 0:
            raise RuntimeError(f"BybitLive get_open_orders: {data.get('retMsg')}")
        orders: list[Order] = []
        for item in (data.get("result") or {}).get("list") or []:
            orders.append(_order_from_bybit_item(item))
        return orders

    async def get_balances(self) -> dict[str, float]:
        if self._http is None:
            raise RuntimeError("BybitLive: connect() before get_balances")
        params = {"accountType": "UNIFIED"}
        params_str = "&".join(f"{k}={params[k]}" for k in sorted(params))
        headers = self._auth_headers(params_str)
        resp = await self._http.get(
            "/v5/account/wallet-balance", headers=headers, params=params,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("retCode") != 0:
            raise RuntimeError(f"BybitLive get_balances: {data.get('retMsg')}")
        out: dict[str, float] = {}
        lists = (data.get("result") or {}).get("list") or []
        if lists:
            for coin in lists[0].get("coin") or []:
                out[coin.get("coin", "")] = float(coin.get("availableToWithdraw") or 0)
        return out

    async def get_instrument(self, symbol: str) -> Instrument:
        if self._http is None:
            raise RuntimeError("BybitLive: connect() before get_instrument")
        params = {"category": "spot", "symbol": symbol}
        # instruments-info is a public endpoint — no auth needed.
        resp = await self._http.get("/v5/market/instruments-info", params=params)
        resp.raise_for_status()
        data = resp.json()
        lst = (data.get("result") or {}).get("list") or []
        if not lst:
            raise RuntimeError(f"BybitLive get_instrument: no such symbol {symbol}")
        item = lst[0]
        lot = item.get("lotSizeFilter") or {}
        pf = item.get("priceFilter") or {}
        base_prec = str(lot.get("basePrecision", "0.00000001"))
        tick = str(pf.get("tickSize", "0.01"))
        return Instrument(
            symbol=symbol,
            base=str(item.get("baseCoin", "")),
            quote=str(item.get("quoteCoin", "")),
            min_qty=float(lot.get("minOrderQty") or 0),
            max_qty=float(lot.get("maxOrderQty") or 0),
            qty_step=float(base_prec),
            min_notional=float(lot.get("minOrderAmt") or 0),
            price_precision=_decimals_of(tick),
            qty_precision=_decimals_of(base_prec),
        )

    # ── Market WS internals ───────────────────────────────────────

    async def _run_market_ws(self) -> None:
        """Long-running task: maintain the public market WS with backoff."""
        delay = self._reconnect_base_delay
        while self._connected:
            try:
                await self._market_ws_session()
                delay = self._reconnect_base_delay
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning(
                    f"BybitLive: market WS error: {exc}. "
                    f"Reconnecting in {delay:.0f}s..."
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._reconnect_max_delay)

    async def _market_ws_session(self) -> None:
        """One iteration of the market WS — connect, re-subscribe, drain."""
        import websockets

        url = self._ws_public_url()
        async with websockets.connect(
            url, ping_interval=_BYBIT_PING_INTERVAL, ping_timeout=10,
        ) as ws:
            self._market_ws = ws
            # Replay subscriptions (idempotent per topic on Bybit's side).
            for topic in list(self._bar_subscriptions):
                await ws.send(json.dumps({"op": "subscribe", "args": [topic]}))
            logger.info("BybitLive: market WS connected")
            async for raw in ws:
                if not self._connected:
                    break
                try:
                    await self._process_market_ws_message(raw)
                except Exception:
                    logger.exception("BybitLive: error processing market frame")
        self._market_ws = None

    async def _process_market_ws_message(self, raw: str | bytes) -> None:
        """Parse one public WS frame; emit :class:`Bar` on closed klines only.

        Bybit kline frames:
          ``{"topic": "kline.240.BTCUSDT", "data": [{
              "start": 1700000000000, "open": "...", "high": "...",
              "low": "...", "close": "...", "volume": "...",
              "confirm": true|false}, ...]}``

        We only emit a :class:`Bar` when ``confirm`` is ``True`` — an
        unconfirmed frame is the still-forming candle and would double-count.
        """
        data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        topic = data.get("topic", "")
        if not topic.startswith("kline."):
            return  # pong, subscription ack, unrelated topics
        if self._on_bar is None:
            return
        sub = self._bar_subscriptions.get(topic)
        if sub is None:
            return
        symbol, timeframe = sub
        for item in data.get("data") or []:
            if not item.get("confirm"):
                continue
            bar = Bar(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=int(item.get("start") or 0),
                open=float(item.get("open") or 0),
                high=float(item.get("high") or 0),
                low=float(item.get("low") or 0),
                close=float(item.get("close") or 0),
                volume=float(item.get("volume") or 0),
            )
            await self._on_bar(bar)

    # ── Private WS internals ──────────────────────────────────────

    async def _run_private_ws(self) -> None:
        """Long-running task: maintain the private WS with backoff."""
        delay = self._reconnect_base_delay
        while self._connected:
            try:
                await self._private_ws_session()
                delay = self._reconnect_base_delay
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning(
                    f"BybitLive: private WS error: {exc}. "
                    f"Reconnecting in {delay:.0f}s..."
                )
                if self._on_disconnect is not None:
                    await self._on_disconnect(self.venue_id)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._reconnect_max_delay)
                if self._on_reconnect is not None and self._connected:
                    await self._on_reconnect(self.venue_id)

    async def _private_ws_session(self) -> None:
        """Authenticate, subscribe to ``order``, drain frames."""
        import websockets

        url = self._ws_private_url()
        async with websockets.connect(
            url, ping_interval=_BYBIT_PING_INTERVAL, ping_timeout=10,
        ) as ws:
            self._private_ws = ws
            expires = int(time.time() * 1000) + 5000
            sig = hmac.new(
                self._api_secret.encode(),
                f"GET/realtime{expires}".encode(),
                hashlib.sha256,
            ).hexdigest()
            await ws.send(
                json.dumps({"op": "auth", "args": [self._api_key, expires, sig]})
            )
            # First frame after auth is the ack. Require success.
            ack = json.loads(await ws.recv())
            if not ack.get("success"):
                raise RuntimeError(f"BybitLive: private WS auth failed: {ack}")
            await ws.send(json.dumps({"op": "subscribe", "args": ["order"]}))

            logger.info("BybitLive: private WS connected")
            async for raw in ws:
                if not self._connected:
                    break
                try:
                    await self._process_private_ws_message(raw)
                except Exception:
                    logger.exception("BybitLive: error processing private frame")
        self._private_ws = None

    async def _process_private_ws_message(self, raw: str | bytes) -> None:
        """Parse one private WS frame; emit :class:`Fill` + :class:`Order` updates.

        Only the ``"order"`` topic is handled. A :class:`Fill` is emitted
        when ``orderStatus`` is ``Filled`` or ``PartiallyFilled``.
        :class:`Order` updates are emitted on every order frame regardless
        of status.
        """
        data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        if data.get("topic") != "order":
            return
        for item in data.get("data") or []:
            status = item.get("orderStatus")
            order_id = str(item.get("orderId", ""))
            symbol = str(item.get("symbol", ""))
            side = OrderSide.BUY if item.get("side") == "Buy" else OrderSide.SELL

            if status in ("Filled", "PartiallyFilled") and self._on_fill is not None:
                qty = float(item.get("cumExecQty") or 0)
                price = float(item.get("avgPrice") or 0)
                if qty > 0 and price > 0:
                    fill = Fill(
                        order_id=order_id,
                        # Bybit doesn't expose a separate trade_id on the
                        # "order" topic — reuse order_id so downstream
                        # dedupe keys still vary per order.
                        trade_id=order_id,
                        symbol=symbol,
                        side=side,
                        price=price,
                        quantity=qty,
                        commission=float(item.get("cumExecFee") or 0),
                        timestamp=int(item.get("createdTime") or 0),
                    )
                    await self._on_fill(fill)

            if self._on_order_update is not None:
                order = Order(
                    id=order_id,
                    symbol=symbol,
                    side=side,
                    type=_map_bybit_order_type(item.get("orderType")),
                    quantity=float(item.get("qty") or 0),
                    price=float(item.get("price") or 0) or None,
                    status=_map_bybit_order_status(status),
                )
                await self._on_order_update(order)


# ── Pure helpers ──────────────────────────────────────────────


def _decimals_of(step: str) -> int:
    """Count decimals in a Bybit ``"0.001"``-style step string."""
    if "." not in step:
        return 0
    return len(step.rstrip("0").split(".")[1])


def _order_from_bybit_item(item: dict[str, Any]) -> Order:
    side = OrderSide.BUY if item.get("side") == "Buy" else OrderSide.SELL
    return Order(
        id=str(item.get("orderId", "")),
        symbol=str(item.get("symbol", "")),
        side=side,
        type=_map_bybit_order_type(item.get("orderType")),
        quantity=float(item.get("qty") or 0),
        price=float(item.get("price") or 0) or None,
        status=_map_bybit_order_status(item.get("orderStatus")),
    )
