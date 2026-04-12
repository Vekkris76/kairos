"""Event bus — typed asyncio queues per event kind.

Strategies and actors subscribe to event *kinds* (bar, tick, order_filled, etc.).
The event bus owns one queue per kind plus a per-subscriber-pattern routing
map. Producers (adapters, actors emitting signals) call ``publish(kind, event)``;
consumers (the LiveEngine's consumer tasks) ``await subscribe(kinds).get()``.

This is intentionally simple — no broker, no persistence, single process. We
choose obviousness over flexibility; complex patterns can wrap this if needed.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger("kairos.event_bus")

# Built-in event kinds. Custom signals use the namespace 'signal:<name>'.
EventKind = Literal[
    "bar",
    "tick",
    "order_accepted",
    "order_rejected",
    "order_filled",
    "adapter_disconnected",
    "adapter_reconnected",
    "shutdown",
]

KNOWN_KINDS: frozenset[str] = frozenset({
    "bar",
    "tick",
    "order_accepted",
    "order_rejected",
    "order_filled",
    "adapter_disconnected",
    "adapter_reconnected",
    "shutdown",
})


def _validate_kind(kind: str) -> None:
    """Raise UnknownEventKindError for typos. Allow signal:<anything>."""
    if kind in KNOWN_KINDS:
        return
    if kind.startswith("signal:") and len(kind) > len("signal:"):
        return
    suggestions = [k for k in KNOWN_KINDS if k.startswith(kind[:3])]
    hint = f". Did you mean {suggestions[0]!r}?" if suggestions else ""
    raise UnknownEventKindError(f"Unknown event kind: {kind!r}{hint}")


class UnknownEventKindError(ValueError):
    """Raised when subscribing/publishing to an unknown kind (typo guard)."""


@dataclass
class _Subscriber:
    """A single subscription — one queue receiving events of declared kinds."""

    kinds: frozenset[str]
    queue: asyncio.Queue[tuple[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=10_000),
    )
    name: str = "anonymous"


class EventBus:
    """Pub/sub for engine events.

    Lifecycle:
        bus = EventBus()
        sub = bus.subscribe({"bar", "order_filled"}, name="my_actor")
        # producer
        await bus.publish("bar", bar_obj)
        # consumer
        kind, event = await sub.queue.get()
    """

    def __init__(self) -> None:
        self._subscribers: list[_Subscriber] = []
        # kind → list of subscribers (denormalized for fast publish)
        self._index: dict[str, list[_Subscriber]] = defaultdict(list)
        self._closed: bool = False

    def subscribe(self, kinds: Iterable[str], name: str = "anonymous") -> _Subscriber:
        """Register a subscriber for one or more event kinds.

        Returns a Subscriber; the consumer reads ``await sub.queue.get()``.
        """
        if self._closed:
            raise RuntimeError("EventBus is closed")
        kind_set = frozenset(kinds)
        if not kind_set:
            raise ValueError("Must subscribe to at least one kind")
        for k in kind_set:
            _validate_kind(k)

        sub = _Subscriber(kinds=kind_set, name=name)
        self._subscribers.append(sub)
        for k in kind_set:
            self._index[k].append(sub)
        logger.debug(f"Subscriber {name!r} registered for {sorted(kind_set)}")
        return sub

    def unsubscribe(self, subscriber: _Subscriber) -> None:
        """Remove a subscriber. The associated queue stops receiving events."""
        if subscriber not in self._subscribers:
            return
        self._subscribers.remove(subscriber)
        for k in subscriber.kinds:
            try:
                self._index[k].remove(subscriber)
            except ValueError:
                pass
        logger.debug(f"Subscriber {subscriber.name!r} unsubscribed")

    async def publish(self, kind: str, event: Any) -> int:
        """Deliver ``event`` to every subscriber of ``kind``.

        Returns the count of subscribers that received the event. Drops with
        a warning if any subscriber's queue is full (indicates back-pressure
        problem in that consumer — should not happen in normal operation).
        """
        _validate_kind(kind)
        if self._closed:
            return 0

        delivered = 0
        for sub in self._index.get(kind, []):
            try:
                sub.queue.put_nowait((kind, event))
                delivered += 1
            except asyncio.QueueFull:
                logger.warning(
                    f"Subscriber {sub.name!r} queue full (>10k events behind); "
                    f"dropped a {kind!r} event"
                )
        return delivered

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def close(self) -> None:
        """Stop accepting new subscriptions or events. Existing queues remain
        readable (drained by their consumers) but get nothing new."""
        self._closed = True
        logger.debug("EventBus closed")
