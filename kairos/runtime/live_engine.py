"""LiveEngine — orchestrates the live trading lifecycle.

This is the v0.2 runtime. It owns the event loop, the scheduler, the
event bus, the registered actors and strategies, and (in v0.2 final) the
market cache + adapters. This skeleton ships in v0.2.0a1 and is fleshed
out in subsequent v0.2 alphas.

What this module DOES today:
- Scaffolds LiveEngine class with add_actor / add_strategy / run / stop
- Wires actors to the EventBus and Scheduler
- Routes incoming events to the correct actor hooks
- Catches exceptions per-actor (engine survives, actor marked degraded)
- Provides graceful shutdown via SIGTERM/SIGINT or .stop()

What this module does NOT do yet (coming in next alphas):
- Adapter registration (depends on Phase 1 §6 — Binance live)
- MarketCache integration (depends on Phase 1 §4)
- Bracket order OCO (depends on Phase 1 §5)
- Reconciliation (depends on Phase 1 §5.3)

The shape is locked, however: future PRs add functionality without
breaking the signature contract here.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Iterable
from typing import Any

from kairos.actors.base import Actor
from kairos.runtime.clock import Clock, SystemClock
from kairos.runtime.event_bus import EventBus, _validate_kind
from kairos.runtime.scheduler import Scheduler

logger = logging.getLogger("kairos.live_engine")


class LiveEngine:
    """The Kairos live runtime.

    Typical usage::

        engine = LiveEngine()
        engine.add_actor(ProtectionActor(cfg), events={"bar", "order_filled"})
        engine.register_adapter(BinanceLiveAdapter(...))   # Phase 1 §6
        await engine.run()
    """

    def __init__(self, *, clock: Clock | None = None) -> None:
        self.clock: Clock = clock or SystemClock()
        self.event_bus: EventBus = EventBus()
        self.scheduler: Scheduler = Scheduler(clock=self.clock)

        self._actors: list[Actor] = []
        self._strategies: list[Any] = []  # Strategy will be wired in next phase
        self._consumer_tasks: list[asyncio.Task[None]] = []
        self._scheduler_task: asyncio.Task[None] | None = None
        self._shutdown_event: asyncio.Event = asyncio.Event()
        self._running: bool = False

    # ── Registration ────────────────────────────────────────────────

    def add_actor(
        self,
        actor: Actor,
        *,
        events: Iterable[str],
        name: str | None = None,
    ) -> None:
        """Register an actor with the events it cares about.

        ``events`` is a set of event-kind strings ("bar", "tick",
        "order_filled", "signal:my_signal", etc.). Unknown kinds raise
        UnknownEventKindError immediately (typo guard).
        """
        if self._running:
            raise RuntimeError("Cannot add_actor while engine is running")

        actor_name = name or f"{type(actor).__name__}#{len(self._actors)}"
        events_set = frozenset(events)
        if not events_set:
            raise ValueError(f"Actor {actor_name!r} must subscribe to at least one event")
        for kind in events_set:
            _validate_kind(kind)

        actor._bind(
            name=actor_name,
            clock=self.clock,
            scheduler=self.scheduler,
            event_bus=self.event_bus,
        )

        # Each actor gets its own subscriber on the bus
        actor.__kairos_subscriber__ = self.event_bus.subscribe(  # type: ignore[attr-defined]
            events_set, name=actor_name,
        )
        self._actors.append(actor)
        logger.info(f"Actor {actor_name!r} registered for {sorted(events_set)}")

    def add_strategy(self, strategy: Any) -> None:
        """Register a strategy. (Strategy class wiring lands next phase.)"""
        if self._running:
            raise RuntimeError("Cannot add_strategy while engine is running")
        self._strategies.append(strategy)
        logger.info(f"Strategy {type(strategy).__name__} registered")

    # ── Lifecycle ───────────────────────────────────────────────────

    async def run(self) -> None:
        """Start the engine: invoke on_start on actors, run the loops.

        Returns when ``stop()`` is called (or SIGTERM/SIGINT received).
        """
        if self._running:
            raise RuntimeError("Engine already running")
        self._running = True
        self._install_signal_handlers()

        logger.info(
            f"LiveEngine starting "
            f"(actors={len(self._actors)} strategies={len(self._strategies)})"
        )

        # Lifecycle: on_start
        for actor in self._actors:
            await self._invoke(actor, actor.on_start, ())

        # Spawn one consumer task per actor + the scheduler
        for actor in self._actors:
            sub = actor.__kairos_subscriber__  # type: ignore[attr-defined]
            self._consumer_tasks.append(
                asyncio.create_task(self._consume(actor, sub), name=f"consume-{actor._name}"),
            )
        self._scheduler_task = asyncio.create_task(self.scheduler.run(), name="scheduler")

        # Wait for shutdown signal
        try:
            await self._shutdown_event.wait()
        finally:
            await self._shutdown(timeout=10.0)

    def stop(self) -> None:
        """Signal the engine to shut down. ``run()`` returns shortly after."""
        logger.info("Stop requested")
        self._shutdown_event.set()

    # ── Event consumption ──────────────────────────────────────────

    async def _consume(self, actor: Actor, sub: Any) -> None:
        """Drain a subscriber's queue and route events to the actor's hooks."""
        while not self._shutdown_event.is_set():
            try:
                kind, event = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            await self._route(actor, kind, event)

    async def _route(self, actor: Actor, kind: str, event: Any) -> None:
        """Dispatch ``event`` to the appropriate actor hook based on ``kind``."""
        if not actor.healthy:
            return  # actor is degraded; skip silently

        try:
            if kind == "bar":
                actor.on_bar(event)
            elif kind == "tick":
                actor.on_tick(event)
            elif kind == "order_filled":
                actor.on_order_filled(event)
            elif kind == "order_rejected":
                actor.on_order_rejected(event)
            elif kind == "order_accepted":
                actor.on_order_accepted(event)
            elif kind == "adapter_disconnected":
                actor.on_adapter_disconnected(event)
            elif kind == "adapter_reconnected":
                actor.on_adapter_reconnected(event)
            elif kind.startswith("signal:"):
                signal_name = kind[len("signal:"):]
                actor.on_signal(signal_name, event)
            elif kind == "shutdown":
                pass  # handled by main shutdown path
            else:
                logger.debug(f"Actor {actor._name!r} received unhandled kind {kind!r}")
        except Exception as exc:
            await self._mark_degraded(actor, exc, hook=kind)

    async def _invoke(self, actor: Actor, fn: Any, args: tuple) -> None:
        """Call a hook (sync or async), trapping exceptions."""
        try:
            result = fn(*args)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            await self._mark_degraded(actor, exc, hook=fn.__name__)

    async def _mark_degraded(self, actor: Actor, exc: Exception, *, hook: str) -> None:
        """Log + flag + publish degraded signal. Actor stops receiving events."""
        actor.healthy = False
        logger.error(
            f"Actor {actor._name!r} raised in {hook}: {exc} — marking degraded",
            exc_info=exc,
        )
        await self.event_bus.publish(
            "signal:actor_degraded",
            {"actor": actor._name, "hook": hook, "error": str(exc)},
        )

    # ── Shutdown ────────────────────────────────────────────────────

    async def _shutdown(self, *, timeout: float) -> None:
        """Drain queues, call on_stop, cancel tasks. Best-effort within ``timeout``."""
        logger.info("LiveEngine shutting down…")

        # Stop the scheduler (no new timer fires)
        self.scheduler.stop()

        # Cancel consumer tasks
        for task in self._consumer_tasks:
            task.cancel()
        if self._scheduler_task is not None:
            self._scheduler_task.cancel()

        await asyncio.gather(
            *self._consumer_tasks,
            *([self._scheduler_task] if self._scheduler_task else []),
            return_exceptions=True,
        )

        # on_stop with per-actor budget (5s each — matches spec §autopilot-actors)
        for actor in reversed(self._actors):  # LIFO: last registered, first stopped
            try:
                await asyncio.wait_for(
                    self._invoke(actor, actor.on_stop, ()),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"Actor {actor._name!r}.on_stop() exceeded 5s, continuing shutdown"
                )

        self.event_bus.close()
        self._running = False
        logger.info("LiveEngine stopped")

    def _install_signal_handlers(self) -> None:
        """Register SIGTERM/SIGINT to call self.stop().

        Best-effort: in environments without an event loop signal API
        (Windows, embedded), this silently no-ops. Tests can call .stop()
        directly.
        """
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, self.stop)
        except (NotImplementedError, RuntimeError):
            pass

    # ── Introspection ──────────────────────────────────────────────

    @property
    def actor_count(self) -> int:
        return len(self._actors)

    @property
    def healthy_actor_count(self) -> int:
        return sum(1 for a in self._actors if a.healthy)
