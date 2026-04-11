"""Binance WebSocket streaming — real-time bar data without polling.

Uses Binance WebSocket API for kline/candlestick streams.
Much more efficient than REST polling.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable

import websockets

from autopilot.types import Bar

logger = logging.getLogger("autopilot.binance_ws")

BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"

TIMEFRAME_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m",
    "1h": "1h", "4h": "4h", "1d": "1d",
}


class BinanceWebSocket:
    """Real-time bar streaming via Binance WebSocket."""

    def __init__(self) -> None:
        self._callbacks: dict[str, list[Callable[[Bar], None]]] = {}
        self._ws = None
        self._running = False
        self._task: asyncio.Task | None = None

    async def subscribe(
        self, symbol: str, timeframe: str, callback: Callable[[Bar], None],
    ) -> None:
        """Subscribe to real-time kline/bar data."""
        key = f"{symbol}:{timeframe}"
        if key not in self._callbacks:
            self._callbacks[key] = []
        self._callbacks[key].append(callback)

        # Start WebSocket if not running
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._run())
        else:
            # Resubscribe with updated streams
            await self._resubscribe()

    async def close(self) -> None:
        """Close WebSocket connection."""
        self._running = False
        if self._ws:
            await self._ws.close()
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        """Main WebSocket loop with auto-reconnect."""
        while self._running:
            try:
                streams = self._build_streams()
                if not streams:
                    await asyncio.sleep(1)
                    continue

                url = f"{BINANCE_WS_URL}/{'/'.join(streams)}"
                logger.info(f"Connecting to Binance WS: {len(streams)} streams")

                async with websockets.connect(url) as ws:
                    self._ws = ws
                    logger.info("Binance WebSocket connected")

                    async for message in ws:
                        if not self._running:
                            break
                        self._process_message(message)

            except websockets.ConnectionClosed:
                logger.warning("WebSocket disconnected — reconnecting in 5s...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"WebSocket error: {e} — reconnecting in 10s...")
                await asyncio.sleep(10)

    def _build_streams(self) -> list[str]:
        """Build Binance stream names from subscriptions."""
        streams = []
        for key in self._callbacks:
            symbol, timeframe = key.split(":")
            binance_symbol = symbol.lower()
            binance_tf = TIMEFRAME_MAP.get(timeframe, timeframe)
            streams.append(f"{binance_symbol}@kline_{binance_tf}")
        return streams

    async def _resubscribe(self) -> None:
        """Reconnect with updated stream list."""
        if self._ws:
            await self._ws.close()
            # _run loop will reconnect with new streams

    def _process_message(self, raw: str) -> None:
        """Parse Binance kline message and dispatch to callbacks."""
        try:
            data = json.loads(raw)
            if "k" not in data:
                return

            kline = data["k"]
            symbol = kline["s"]  # e.g., "BTCUSDC"
            timeframe = kline["i"]  # e.g., "1h"
            is_closed = kline["x"]  # True when candle is complete

            if not is_closed:
                return  # Only process completed candles

            bar = Bar(
                symbol=symbol.upper(),
                timeframe=timeframe,
                timestamp=kline["t"],
                open=float(kline["o"]),
                high=float(kline["h"]),
                low=float(kline["l"]),
                close=float(kline["c"]),
                volume=float(kline["v"]),
            )

            key = f"{symbol.upper()}:{timeframe}"
            for callback in self._callbacks.get(key, []):
                try:
                    callback(bar)
                except Exception as e:
                    logger.error(f"Callback error: {e}")

        except (json.JSONDecodeError, KeyError) as e:
            logger.debug(f"Ignoring message: {e}")
