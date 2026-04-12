"""Scheduler — async timer registry with idempotent set/cancel and TestClock-driven mode.

Used by actors via ``self.set_timer(name, interval, callback)``. Two run modes:

- **System mode** (``Scheduler.run()``): drives timers from real `asyncio` sleeps.
  Used in production with ``SystemClock``.
- **Test mode** (``Scheduler.tick(clock)``): manually invoked from tests after
  advancing a ``TestClock``. Fires every callback whose next-fire time has
  arrived.

The scheduler is *cooperative*: callbacks are awaited if coroutines, called
otherwise. Slow callbacks delay subsequent timers (this is intentional — a
trading engine should not have surprise concurrency).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Awaitable, Callable

from kairos.runtime.clock import Clock, SystemClock

logger = logging.getLogger("kairos.scheduler")

TimerCallback = Callable[[], None | Awaitable[None]]


@dataclass
class _Timer:
    name: str
    interval_seconds: float
    callback: TimerCallback
    next_fire_monotonic: float
    cancelled: bool = field(default=False, init=False)


class Scheduler:
    """Manages named periodic timers.

    Behavior:
        - ``set_timer(name, interval, cb)`` installs (or replaces) a timer.
          The first fire is `interval` seconds from registration.
        - ``cancel_timer(name)`` removes a timer; no-op if unknown.
        - ``run()`` (production) loops forever, sleeping until next due.
        - ``tick(clock)`` (tests) fires every timer whose ``next_fire_monotonic``
          has passed; returns the count of fired callbacks.

    The scheduler does not own its clock — callers pass a clock instance.
    This lets tests share a TestClock with the rest of the runtime.
    """

    def __init__(self, clock: Clock | None = None) -> None:
        self._clock: Clock = clock or SystemClock()
        self._timers: dict[str, _Timer] = {}
        self._stop_event: asyncio.Event | None = None

    # ── Public API ──────────────────────────────────────────

    def set_timer(
        self,
        name: str,
        interval: timedelta | float,
        callback: TimerCallback,
    ) -> None:
        """Install or replace a periodic timer.

        Replacing a timer with the same name is atomic — the previous
        timer is cancelled before the new one is installed.
        """
        if not name:
            raise ValueError("Timer name must be non-empty")

        seconds = interval.total_seconds() if isinstance(interval, timedelta) else float(interval)
        if seconds <= 0:
            raise ValueError(f"Timer interval must be > 0 seconds, got {seconds}")

        # Cancel previous timer with same name (idempotent replace)
        if name in self._timers:
            self._timers[name].cancelled = True

        self._timers[name] = _Timer(
            name=name,
            interval_seconds=seconds,
            callback=callback,
            next_fire_monotonic=self._clock.monotonic() + seconds,
        )
        logger.debug(f"Timer '{name}' set to fire every {seconds}s")

    def cancel_timer(self, name: str) -> None:
        """Cancel a timer by name. No-op if name is unknown."""
        timer = self._timers.pop(name, None)
        if timer is not None:
            timer.cancelled = True
            logger.debug(f"Timer '{name}' cancelled")

    def has_timer(self, name: str) -> bool:
        return name in self._timers and not self._timers[name].cancelled

    @property
    def active_timer_count(self) -> int:
        return sum(1 for t in self._timers.values() if not t.cancelled)

    # ── Test-mode driver ───────────────────────────────────

    async def tick(self) -> int:
        """Fire any timer whose due time has arrived (uses self._clock).

        Returns the number of callbacks invoked. Designed for tests with
        TestClock — call after ``test_clock.advance(N)``.
        """
        now = self._clock.monotonic()
        fired = 0
        # Snapshot to allow callbacks that mutate _timers
        for timer in list(self._timers.values()):
            if timer.cancelled:
                continue
            while timer.next_fire_monotonic <= now and not timer.cancelled:
                await self._invoke(timer)
                timer.next_fire_monotonic += timer.interval_seconds
                fired += 1
        # Remove cancelled
        self._timers = {n: t for n, t in self._timers.items() if not t.cancelled}
        return fired

    # ── Production driver ──────────────────────────────────

    async def run(self) -> None:
        """Event loop: sleep until next timer is due, fire it, repeat.

        Stops when ``stop()`` is called. Designed for ``SystemClock``;
        not intended for tests (use ``tick`` instead).
        """
        self._stop_event = asyncio.Event()
        logger.info("Scheduler started")
        try:
            while not self._stop_event.is_set():
                if not self._timers:
                    # No timers active — wait for one to be installed
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    continue

                # Find earliest timer
                next_t = min(
                    (t for t in self._timers.values() if not t.cancelled),
                    key=lambda t: t.next_fire_monotonic,
                    default=None,
                )
                if next_t is None:
                    await asyncio.sleep(0.1)
                    continue

                wait_seconds = max(0.0, next_t.next_fire_monotonic - self._clock.monotonic())
                if wait_seconds > 0:
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=wait_seconds)
                        # If we got here, stop was signalled — exit
                        break
                    except asyncio.TimeoutError:
                        pass  # Timer is due, fall through to fire

                if next_t.cancelled:
                    self._timers.pop(next_t.name, None)
                    continue

                await self._invoke(next_t)
                next_t.next_fire_monotonic += next_t.interval_seconds
        finally:
            logger.info("Scheduler stopped")

    def stop(self) -> None:
        """Signal ``run()`` to exit on its next iteration."""
        if self._stop_event is not None:
            self._stop_event.set()

    # ── Internal ──────────────────────────────────────────

    async def _invoke(self, timer: _Timer) -> None:
        """Call the timer's callback, awaiting if it is a coroutine."""
        try:
            result = timer.callback()
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            logger.error(
                f"Timer '{timer.name}' callback raised: {exc}",
                exc_info=True,
            )
