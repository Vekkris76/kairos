"""Reconnection wrapper — auto-reconnect on exchange disconnection.

Wraps any ExchangeAdapter with exponential backoff reconnection.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from kairos.exchanges.base import ExchangeAdapter

logger = logging.getLogger("autopilot.reconnect")


class ReconnectWrapper:
    """Wraps an exchange adapter with auto-reconnect logic."""

    def __init__(
        self,
        adapter: ExchangeAdapter,
        max_retries: int = 10,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
    ) -> None:
        self._adapter = adapter
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._connected = False
        self._retries = 0

    async def connect(self) -> None:
        """Connect with retry logic."""
        while self._retries < self._max_retries:
            try:
                await self._adapter.connect()
                self._connected = True
                self._retries = 0
                logger.info("Exchange connected")
                return
            except Exception as e:
                self._retries += 1
                delay = min(
                    self._base_delay * (2 ** self._retries),
                    self._max_delay,
                )
                logger.warning(
                    f"Connection failed ({self._retries}/{self._max_retries}): "
                    f"{e}. Retrying in {delay:.0f}s...",
                )
                await asyncio.sleep(delay)

        raise ConnectionError(
            f"Failed to connect after {self._max_retries} attempts",
        )

    async def reconnect(self) -> None:
        """Force reconnection."""
        logger.info("Reconnecting to exchange...")
        self._connected = False
        try:
            await self._adapter.disconnect()
        except Exception:
            pass
        self._retries = 0
        await self.connect()

    async def safe_call(self, coro: Any) -> Any:
        """Execute an async call with reconnection on failure."""
        try:
            return await coro
        except Exception as e:
            logger.warning(f"Exchange call failed: {e}. Reconnecting...")
            await self.reconnect()
            return await coro

    @property
    def connected(self) -> bool:
        return self._connected
