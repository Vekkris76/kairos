"""Actor base class — receives engine events, optionally publishes signals.

An Actor is a long-lived object registered with a LiveEngine. It receives
events (bars, ticks, fills, signals) for which it has subscribed, can
publish its own signals to other actors, and can install timers via the
shared Scheduler.

The class is small by design — most actor logic is in subclasses.
Lifecycle hooks default to no-ops; override only what you need.

Exception isolation: if an actor's hook raises, the engine catches the
exception, logs it, marks the actor degraded, and continues. The actor's
``healthy`` flag becomes False and a ``signal:actor_degraded`` is
published so other components can react.
"""

from __future__ import annotations

import logging
from abc import ABC
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from kairos.runtime.clock import Clock
    from kairos.runtime.event_bus import EventBus
    from kairos.runtime.scheduler import Scheduler


@dataclass(frozen=True)
class ActorConfig:
    """Base config for actors. Subclasses extend with their own frozen fields.

    Frozen because configs should never mutate after construction —
    immutability simplifies reasoning about an actor's behavior.
    """


class Actor(ABC):
    """Base class for all Kairos actors.

    Subclasses override the hooks they care about:
      - on_start(): called once after registration, before events flow
      - on_stop(): called on engine shutdown (5s timeout per actor)
      - on_bar(bar): a bar arrived (subscribers of "bar")
      - on_tick(tick): a tick arrived (subscribers of "tick")
      - on_order_filled(event): an order was filled
      - on_order_rejected(event): an order was rejected
      - on_order_accepted(event): an order was accepted by the venue
      - on_signal(name, value): an actor-published signal arrived
        (subscribers of "signal:<name>")
      - on_adapter_disconnected(adapter_id): a venue adapter dropped
      - on_adapter_reconnected(adapter_id): adapter recovered

    Bound by the engine at registration time (do NOT touch in __init__):
      - self.log: logger named "kairos.actor.<ClassName>"
      - self.clock: the engine's Clock
      - self.cache: the engine's MarketCache (TODO Phase 2)
      - self.healthy: True until an exception fires; False afterwards
    """

    # Bound at registration — do not access in __init__
    log: logging.Logger
    clock: "Clock"
    healthy: bool = True

    # Internal — set by engine
    _scheduler: "Scheduler | None" = None
    _event_bus: "EventBus | None" = None
    _name: str = ""

    def __init__(self, config: ActorConfig) -> None:
        self.config = config

    # ── Lifecycle hooks (subclasses override what they need) ─────────

    def on_start(self) -> None:
        """Called once after the engine starts and the actor is wired up."""

    def on_stop(self) -> None:
        """Called on engine shutdown. Use to flush state, send final alerts."""

    def on_bar(self, bar: Any) -> None:
        """A bar arrived for an instrument this actor subscribes to."""

    def on_tick(self, tick: Any) -> None:
        """A tick arrived. Higher frequency than bars; only subscribe if needed."""

    def on_order_filled(self, event: Any) -> None:
        """An order belonging to any strategy was filled by the venue."""

    def on_order_rejected(self, event: Any) -> None:
        """A submission was rejected (insufficient balance, lot size, etc.)."""

    def on_order_accepted(self, event: Any) -> None:
        """The venue accepted an order (it is now resting or being worked)."""

    def on_signal(self, name: str, value: Any) -> None:
        """A signal published by another actor arrived.

        ``name`` is the part after ``signal:`` (e.g. published as
        ``signal:risk_state`` arrives here as ``name="risk_state"``).
        """

    def on_adapter_disconnected(self, adapter_id: str) -> None:
        """A venue adapter lost its WebSocket connection."""

    def on_adapter_reconnected(self, adapter_id: str) -> None:
        """A venue adapter recovered. Reconciliation will follow."""

    # ── Helpers actors call ──────────────────────────────────────────

    def publish_signal(self, name: str, value: Any) -> None:
        """Emit a signal that other actors subscribed to ``signal:<name>``
        will receive. Synchronous from caller's perspective; the bus
        handles async delivery internally (queue put_nowait).
        """
        if self._event_bus is None:
            raise ActorNotRegisteredError(
                f"Actor {self._name!r} cannot publish signals before registration"
            )
        # publish is async; we schedule it without awaiting (fire-and-forget
        # is fine — the bus uses put_nowait internally)
        import asyncio

        asyncio.create_task(self._event_bus.publish(f"signal:{name}", value))

    def set_timer(
        self,
        name: str,
        interval: timedelta | float,
        callback: Callable,
    ) -> None:
        """Install a recurring timer. Idempotent: same name replaces."""
        if self._scheduler is None:
            raise ActorNotRegisteredError(
                f"Actor {self._name!r} cannot set timers before registration"
            )
        # Namespace by actor so two actors can both have a "heartbeat" timer
        full_name = f"{self._name}:{name}"
        self._scheduler.set_timer(full_name, interval, callback)

    def cancel_timer(self, name: str) -> None:
        """Cancel a timer this actor previously set. No-op if unknown."""
        if self._scheduler is None:
            return
        self._scheduler.cancel_timer(f"{self._name}:{name}")

    # ── Engine internals (called by LiveEngine, not subclasses) ──────

    def _bind(
        self,
        *,
        name: str,
        clock: "Clock",
        scheduler: "Scheduler",
        event_bus: "EventBus",
    ) -> None:
        """Engine-only: wire the actor into the runtime.

        Sets log, clock, scheduler, event_bus. Subclasses must NOT call
        this.
        """
        self._name = name
        cls_name = type(self).__name__
        self.log = logging.getLogger(f"kairos.actor.{cls_name}")
        self.clock = clock
        self._scheduler = scheduler
        self._event_bus = event_bus
        self.healthy = True


class ActorNotRegisteredError(RuntimeError):
    """Raised when an actor calls a runtime helper before being registered."""
