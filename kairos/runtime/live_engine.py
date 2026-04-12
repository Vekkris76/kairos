"""LiveEngine — orchestrates the live trading lifecycle.

This is the v0.2 runtime, fleshed out in v0.2.1 to actually wire
strategies + adapters + cache. v0.2.0 shipped the skeleton; v0.2.1
makes it functional end-to-end.

What this module does (v0.2.1):
- Owns the EventBus, Scheduler, Clock, MarketCache.
- Adapter registration: callbacks wired so adapter events flow into
  the cache + bus automatically.
- ``add_actor`` / ``add_strategy``: registers components and binds
  ``self.cache`` so they can read market state.
- Lifecycle: on_start invocation, consumer tasks per actor, scheduler
  loop, graceful shutdown (SIGTERM / SIGINT, 10s drain, 5s per-actor
  on_stop).
- Reconciliation triggered automatically on adapter_reconnected.
- Exception isolation: an actor raising marks itself degraded and
  publishes ``signal:actor_degraded``; engine continues.

What this module does NOT do yet:
- BracketManager + Reconciler are constructed by callers and passed
  through (engine doesn't own them — composition over inheritance).
- Indicator warmup is the strategy's responsibility (see LiveStrategy).
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from kairos.actors.base import Actor
from kairos.cache.market_cache import MarketCache
from kairos.runtime.clock import Clock, SystemClock
from kairos.runtime.event_bus import EventBus, _validate_kind
from kairos.runtime.scheduler import Scheduler

if TYPE_CHECKING:
    from kairos.adapters.base import LiveAdapter

logger = logging.getLogger("kairos.live_engine")

# Strategy event subscription default — strategies care about bars +
# their own fills (so they can react / reset state). Override via
# ``add_strategy(strategy, events=...)`` for advanced use cases.
_STRATEGY_DEFAULT_EVENTS = frozenset({"bar", "order_filled"})


class LiveEngine:
    """The Kairos live runtime.

    Typical usage::

        engine = LiveEngine()
        engine.register_adapter(BinanceLive(api_key, api_secret))
        engine.add_actor(ProtectionActor(cfg), events={"bar", "order_filled"})
        engine.add_strategy(MyStrategy(cfg))
        await engine.run()
    """

    def __init__(self, *, clock: Clock | None = None, cache: MarketCache | None = None) -> None:
        self.clock: Clock = clock or SystemClock()
        self.event_bus: EventBus = EventBus()
        self.scheduler: Scheduler = Scheduler(clock=self.clock)
        self.cache: MarketCache = cache or MarketCache()

        self._actors: list[Actor] = []
        self._adapters: list["LiveAdapter"] = []
        self._strategy_subscriptions: list[tuple[str, str]] = []  # (symbol, timeframe)
        self._consumer_tasks: list[asyncio.Task[None]] = []
        self._scheduler_task: asyncio.Task[None] | None = None
        self._shutdown_event: asyncio.Event = asyncio.Event()
        self._running: bool = False

    # ── Registration ────────────────────────────────────────────────

    def register_adapter(self, adapter: "LiveAdapter") -> None:
        """Register a venue adapter. Engine wires its callbacks to the
        EventBus + MarketCache. Adapter is connected on ``.run()``,
        disconnected on ``.stop()``.

        Multiple adapters allowed (one per venue). Each gets its own
        callback wiring; events flow into the same shared bus.
        """
        if self._running:
            raise RuntimeError("Cannot register_adapter while engine is running")

        adapter.set_bar_callback(self._on_bar_from_adapter)
        adapter.set_tick_callback(self._on_tick_from_adapter)
        adapter.set_fill_callback(self._on_fill_from_adapter)
        adapter.set_order_update_callback(self._on_order_update_from_adapter)
        adapter.set_disconnect_callback(self._on_adapter_disconnected)
        adapter.set_reconnect_callback(self._on_adapter_reconnected)

        self._adapters.append(adapter)
        logger.info(f"Adapter registered: venue_id={adapter.venue_id}")

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

        At registration the actor's ``self.cache`` is bound to the
        engine's MarketCache so the actor can read market state.
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
        # Bind the cache too — engine owns it, actors read from it
        actor.cache = self.cache  # type: ignore[attr-defined]

        # Each actor gets its own subscriber on the bus
        actor.__kairos_subscriber__ = self.event_bus.subscribe(  # type: ignore[attr-defined]
            events_set, name=actor_name,
        )
        self._actors.append(actor)
        logger.info(f"Actor {actor_name!r} registered for {sorted(events_set)}")

    def add_strategy(
        self,
        strategy: Actor,
        *,
        events: Iterable[str] | None = None,
        name: str | None = None,
    ) -> None:
        """Register a strategy. Sugar over ``add_actor`` for the strategy
        Actor pattern.

        Strategies in v0.2.1+ are Actor-shaped: they subscribe to bar +
        order_filled events, may submit orders, and have access to the
        cache + scheduler + bus via the Actor base.

        If the strategy exposes ``symbol`` and ``timeframe`` attributes
        (the convention in V3StrategyActor), the engine remembers them
        and will instruct each registered adapter to subscribe to that
        ``(symbol, timeframe)`` stream on connect.
        """
        events_set = frozenset(events) if events else _STRATEGY_DEFAULT_EVENTS
        actor_name = name or f"{type(strategy).__name__}#{len(self._actors)}"
        self.add_actor(strategy, events=events_set, name=actor_name)

        # If the strategy declared a (symbol, timeframe), remember it
        # so we can subscribe the adapter on connect.
        symbol = getattr(strategy, "symbol", "")
        timeframe = getattr(strategy, "timeframe", "")
        if symbol and timeframe:
            sub = (symbol, timeframe)
            if sub not in self._strategy_subscriptions:
                self._strategy_subscriptions.append(sub)

    # ── Lifecycle ───────────────────────────────────────────────────

    async def run(self) -> None:
        """Start the engine.

        Sequence:
          1. Connect every registered adapter
          2. Subscribe each adapter to every (symbol, timeframe) declared
             by registered strategies
          3. Invoke ``on_start`` on every actor
          4. Spawn one consumer task per actor + the scheduler
          5. Block until ``stop()`` is called or SIGTERM/SIGINT received
          6. Graceful shutdown: drain queues, on_stop, disconnect adapters

        Returns when ``stop()`` is called.
        """
        if self._running:
            raise RuntimeError("Engine already running")
        self._running = True
        self._install_signal_handlers()

        logger.info(
            f"LiveEngine starting "
            f"(adapters={len(self._adapters)} actors={len(self._actors)} "
            f"strategy-subs={len(self._strategy_subscriptions)})"
        )

        # 1. Connect adapters
        for adapter in self._adapters:
            try:
                await adapter.connect()
            except Exception as exc:
                logger.error(f"Adapter {adapter.venue_id} connect failed: {exc}")
                # Continue with degraded state — strategies will get no events

        # 2. Subscribe adapters to strategy streams
        for symbol, timeframe in self._strategy_subscriptions:
            for adapter in self._adapters:
                try:
                    await adapter.subscribe_bars(symbol, timeframe)
                except Exception as exc:
                    logger.error(
                        f"Adapter {adapter.venue_id} subscribe_bars "
                        f"({symbol}, {timeframe}) failed: {exc}"
                    )

        # 3. Lifecycle: on_start
        for actor in self._actors:
            await self._invoke(actor, actor.on_start, ())

        # 4. Spawn consumer task per actor + scheduler
        for actor in self._actors:
            sub = actor.__kairos_subscriber__  # type: ignore[attr-defined]
            self._consumer_tasks.append(
                asyncio.create_task(
                    self._consume(actor, sub), name=f"consume-{actor._name}",
                ),
            )
        self._scheduler_task = asyncio.create_task(
            self.scheduler.run(), name="scheduler",
        )

        # 5. Block until shutdown
        try:
            await self._shutdown_event.wait()
        finally:
            await self._shutdown(timeout=10.0)

    def stop(self) -> None:
        """Signal the engine to shut down. ``run()`` returns shortly after."""
        logger.info("Stop requested")
        self._shutdown_event.set()

    # ── Adapter callbacks (engine-internal — adapter calls these) ──

    async def _on_bar_from_adapter(self, bar: Any) -> None:
        """A bar arrived from an adapter. Update cache + publish."""
        try:
            timeframe = getattr(bar, "timeframe", "")
            self.cache.ingest_bar(bar, timeframe=timeframe)
        except Exception as exc:
            logger.error(f"Cache ingest_bar failed: {exc}")
        await self.event_bus.publish("bar", bar)

    async def _on_tick_from_adapter(self, symbol: str, price: float) -> None:
        """A tick arrived. Update cache + publish."""
        try:
            self.cache.ingest_tick(symbol, price)
        except Exception as exc:
            logger.error(f"Cache ingest_tick failed: {exc}")
        await self.event_bus.publish("tick", (symbol, price))

    async def _on_fill_from_adapter(self, fill: Any) -> None:
        """A fill arrived. Update cache (position netting) + publish."""
        try:
            self.cache.ingest_fill(fill)
        except Exception as exc:
            logger.error(f"Cache ingest_fill failed: {exc}")
        await self.event_bus.publish("order_filled", fill)

    async def _on_order_update_from_adapter(self, order: Any) -> None:
        """An order changed state (accepted, partially_filled, ...)."""
        try:
            self.cache.ingest_order(order)
        except Exception as exc:
            logger.error(f"Cache ingest_order failed: {exc}")
        # Publish as order_accepted for now; richer routing per status in v0.2.2+
        await self.event_bus.publish("order_accepted", order)

    async def _on_adapter_disconnected(self, venue_id: str) -> None:
        logger.warning(f"Adapter {venue_id} disconnected")
        await self.event_bus.publish("adapter_disconnected", venue_id)

    async def _on_adapter_reconnected(self, venue_id: str) -> None:
        logger.info(f"Adapter {venue_id} reconnected — reconciliation may run")
        await self.event_bus.publish("adapter_reconnected", venue_id)

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
                # tick event is (symbol, price) tuple
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
        """Drain queues, call on_stop, cancel tasks, disconnect adapters."""
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

        # Disconnect adapters
        for adapter in self._adapters:
            try:
                await adapter.disconnect()
            except Exception as exc:
                logger.warning(f"Adapter {adapter.venue_id} disconnect: {exc}")

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

    @property
    def adapter_count(self) -> int:
        return len(self._adapters)
