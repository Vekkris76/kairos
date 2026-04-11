"""Binance Spot adapter — real exchange via CCXT.

Handles REST API + WebSocket for live trading.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

import ccxt.async_support as ccxt

from autopilot.exchanges.base import ExchangeAdapter
from autopilot.types import (
    Balance, Bar, Fill, Instrument, Order,
    OrderSide, OrderStatus, OrderType, TimeInForce,
)

logger = logging.getLogger("autopilot.binance")

TIMEFRAME_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m",
    "1h": "1h", "4h": "4h", "1d": "1d",
}


class BinanceAdapter(ExchangeAdapter):
    """Live Binance Spot exchange adapter."""

    def __init__(self, api_key: str, api_secret: str) -> None:
        self._exchange = ccxt.binance({
            "apiKey": api_key,
            "secret": api_secret,
            "options": {"defaultType": "spot"},
            "enableRateLimit": True,
        })
        self._bar_callbacks: dict[str, list[Callable]] = {}
        self._fill_callback: Callable | None = None
        self._order_callback: Callable | None = None
        self._instruments: dict[str, Instrument] = {}
        self._ws_tasks: list[asyncio.Task] = []
        self._running = False
        self._ws_stream = None
        self._use_websocket = True  # Use WS instead of polling

    async def connect(self) -> None:
        await self._exchange.load_markets()
        self._running = True

        # Initialize WebSocket stream
        if self._use_websocket:
            from autopilot.exchanges.binance_ws import BinanceWebSocket
            self._ws_stream = BinanceWebSocket()

        logger.info(
            f"Binance connected — "
            f"{len(self._exchange.markets)} markets loaded"
            f" (WebSocket: {'enabled' if self._use_websocket else 'polling'})",
        )

    async def disconnect(self) -> None:
        self._running = False
        if self._ws_stream:
            await self._ws_stream.close()
        for task in self._ws_tasks:
            task.cancel()
        await self._exchange.close()
        logger.info("Binance disconnected")

    # ── Market Data ───────────────────────────────────

    async def subscribe_bars(
        self, symbol: str, timeframe: str, callback: Callable[[Bar], None],
    ) -> None:
        key = f"{symbol}:{timeframe}"
        if key not in self._bar_callbacks:
            self._bar_callbacks[key] = []
        self._bar_callbacks[key].append(callback)

        if self._use_websocket and self._ws_stream:
            # Real-time WebSocket streaming
            await self._ws_stream.subscribe(symbol, timeframe, callback)
            logger.info(f"Subscribed to {symbol} @ {timeframe} (WebSocket)")
        else:
            # Fallback to REST polling
            task = asyncio.create_task(
                self._poll_bars(symbol, timeframe),
            )
            self._ws_tasks.append(task)
            logger.info(f"Subscribed to {symbol} @ {timeframe} (polling)")

    async def _poll_bars(self, symbol: str, timeframe: str) -> None:
        """Poll for new bars (CCXT watch_ohlcv or fallback to REST)."""
        ccxt_symbol = symbol.replace("USDC", "/USDC")
        ccxt_tf = TIMEFRAME_MAP.get(timeframe, timeframe)
        key = f"{symbol}:{timeframe}"
        last_ts = 0

        while self._running:
            try:
                ohlcv = await self._exchange.fetch_ohlcv(
                    ccxt_symbol, ccxt_tf, limit=2,
                )
                if ohlcv and len(ohlcv) >= 2:
                    # Use the completed bar (second to last)
                    candle = ohlcv[-2]
                    ts = candle[0]
                    if ts > last_ts:
                        bar = Bar(
                            symbol=symbol,
                            timeframe=timeframe,
                            timestamp=ts,
                            open=candle[1],
                            high=candle[2],
                            low=candle[3],
                            close=candle[4],
                            volume=candle[5],
                        )
                        for cb in self._bar_callbacks.get(key, []):
                            cb(bar)
                        last_ts = ts

                # Poll interval based on timeframe
                intervals = {
                    "1m": 10, "5m": 30, "15m": 60,
                    "1h": 120, "4h": 300, "1d": 600,
                }
                await asyncio.sleep(intervals.get(timeframe, 60))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Bar poll error {symbol}: {e}")
                await asyncio.sleep(5)

    async def get_historical_bars(
        self, symbol: str, timeframe: str,
        start_ms: int, end_ms: int,
    ) -> list[Bar]:
        ccxt_symbol = symbol.replace("USDC", "/USDC")
        ccxt_tf = TIMEFRAME_MAP.get(timeframe, timeframe)
        all_bars = []
        since = start_ms

        while since < end_ms:
            ohlcv = await self._exchange.fetch_ohlcv(
                ccxt_symbol, ccxt_tf, since=since, limit=1000,
            )
            if not ohlcv:
                break
            for candle in ohlcv:
                if candle[0] >= end_ms:
                    break
                all_bars.append(Bar(
                    symbol=symbol, timeframe=timeframe,
                    timestamp=candle[0],
                    open=candle[1], high=candle[2],
                    low=candle[3], close=candle[4],
                    volume=candle[5],
                ))
            since = ohlcv[-1][0] + 1
            await asyncio.sleep(0.2)  # Rate limit

        return all_bars

    # ── Orders ────────────────────────────────────────

    async def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: float | None = None,
        stop_price: float | None = None,
        time_in_force: TimeInForce = TimeInForce.GTC,
        post_only: bool = False,
        reduce_only: bool = False,
    ) -> Order:
        ccxt_symbol = symbol.replace("USDC", "/USDC")
        ccxt_side = side.value.lower()
        ccxt_type = "market" if order_type == OrderType.MARKET else "limit"

        params = {}
        if post_only:
            params["postOnly"] = True
        if stop_price and order_type in (OrderType.STOP_MARKET, OrderType.STOP_LIMIT):
            ccxt_type = "STOP_LOSS_LIMIT" if price else "STOP_LOSS"
            params["stopPrice"] = stop_price

        try:
            result = await self._exchange.create_order(
                ccxt_symbol, ccxt_type, ccxt_side, quantity,
                price, params,
            )

            order = Order(
                id=result["id"],
                symbol=symbol,
                side=side,
                type=order_type,
                quantity=quantity,
                price=price,
                stop_price=stop_price,
                status=OrderStatus.SUBMITTED,
            )

            # Check if already filled (market orders)
            if result.get("status") == "closed":
                order.status = OrderStatus.FILLED
                avg_price = result.get("average", price or 0)
                fee = result.get("fee", {}).get("cost", 0) or 0

                fill = Fill(
                    order_id=order.id,
                    trade_id=result.get("id", ""),
                    symbol=symbol,
                    side=side,
                    price=avg_price,
                    quantity=quantity,
                    commission=fee,
                    timestamp=int(time.time() * 1000),
                )
                if self._fill_callback:
                    self._fill_callback(fill)

            logger.info(
                f"Order submitted: {side.value} {quantity} "
                f"{symbol} @ {price or 'MARKET'} → {order.status.value}",
            )
            return order

        except Exception as e:
            logger.error(f"Order failed: {e}")
            return Order(
                id="", symbol=symbol, side=side, type=order_type,
                quantity=quantity, status=OrderStatus.REJECTED,
            )

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        try:
            ccxt_symbol = symbol.replace("USDC", "/USDC")
            await self._exchange.cancel_order(order_id, ccxt_symbol)
            return True
        except Exception as e:
            logger.error(f"Cancel failed: {e}")
            return False

    async def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        try:
            ccxt_symbol = symbol.replace("USDC", "/USDC") if symbol else None
            orders = await self._exchange.fetch_open_orders(ccxt_symbol)
            return [
                Order(
                    id=o["id"], symbol=symbol or o["symbol"],
                    side=OrderSide(o["side"].upper()),
                    type=OrderType.LIMIT, quantity=o["amount"],
                    price=o.get("price"), status=OrderStatus.ACCEPTED,
                )
                for o in orders
            ]
        except Exception as e:
            logger.error(f"Fetch orders failed: {e}")
            return []

    # ── Account ───────────────────────────────────────

    async def get_balances(self) -> dict[str, Balance]:
        try:
            data = await self._exchange.fetch_balance()
            result = {}
            for currency, info in data.get("total", {}).items():
                total = float(info) if info else 0
                if total > 0:
                    free = float(data.get("free", {}).get(currency, 0))
                    locked = total - free
                    result[currency] = Balance(
                        currency=currency, free=free, locked=locked,
                    )
            return result
        except Exception as e:
            logger.error(f"Fetch balances failed: {e}")
            return {}

    async def get_instrument(self, symbol: str) -> Instrument:
        if symbol in self._instruments:
            return self._instruments[symbol]

        ccxt_symbol = symbol.replace("USDC", "/USDC")
        market = self._exchange.market(ccxt_symbol)
        limits = market.get("limits", {})
        precision = market.get("precision", {})

        inst = Instrument(
            symbol=symbol,
            base=market.get("base", ""),
            quote=market.get("quote", "USDC"),
            min_qty=limits.get("amount", {}).get("min", 0.00001),
            max_qty=limits.get("amount", {}).get("max", 1000000),
            qty_step=10 ** (-precision.get("amount", 5)),
            min_notional=limits.get("cost", {}).get("min", 5.0),
            price_precision=precision.get("price", 2),
            qty_precision=precision.get("amount", 5),
        )
        self._instruments[symbol] = inst
        return inst
