"""Event system — async pub/sub for component communication."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger("autopilot.events")


@dataclass
class Event:
    """Base event."""
    type: str
    data: Any = None


class EventBus:
    """Simple async event bus for inter-component communication."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._queue: asyncio.Queue[Event] = asyncio.Queue()

    def subscribe(self, event_type: str, handler: Callable) -> None:
        """Register a handler for an event type."""
        self._handlers[event_type].append(handler)

    def publish(self, event_type: str, data: Any = None) -> None:
        """Publish an event (non-blocking)."""
        self._queue.put_nowait(Event(type=event_type, data=data))

    async def process(self) -> None:
        """Process one event from the queue."""
        event = await self._queue.get()
        handlers = self._handlers.get(event.type, [])
        for handler in handlers:
            try:
                result = handler(event.data)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Event handler error [{event.type}]: {e}")

    async def drain(self) -> None:
        """Process all pending events."""
        while not self._queue.empty():
            await self.process()
