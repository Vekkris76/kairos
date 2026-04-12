"""Tests for kairos.runtime.scheduler."""

from __future__ import annotations

import pytest

from kairos.runtime.clock import TestClock
from kairos.runtime.scheduler import Scheduler


pytestmark = pytest.mark.asyncio


async def test_set_timer_fires_after_interval() -> None:
    clock = TestClock()
    sched = Scheduler(clock=clock)
    fires: list[float] = []
    sched.set_timer("t1", 1.0, lambda: fires.append(clock.monotonic()))

    # Not yet due
    clock.advance(0.5)
    fired = await sched.tick()
    assert fired == 0
    assert fires == []

    # Now due
    clock.advance(0.5)
    fired = await sched.tick()
    assert fired == 1
    assert fires == [pytest.approx(1.0)]


async def test_set_timer_recurring() -> None:
    clock = TestClock()
    sched = Scheduler(clock=clock)
    fires: list[float] = []
    sched.set_timer("recurring", 0.5, lambda: fires.append(clock.monotonic()))

    clock.advance(2.0)
    await sched.tick()
    # Fires at 0.5, 1.0, 1.5, 2.0 → 4 times
    assert len(fires) == 4


async def test_set_timer_replaces_existing_with_same_name() -> None:
    clock = TestClock()
    sched = Scheduler(clock=clock)
    fires: list[str] = []
    sched.set_timer("x", 1.0, lambda: fires.append("first"))
    sched.set_timer("x", 1.0, lambda: fires.append("second"))   # replace

    clock.advance(1.0)
    await sched.tick()
    assert fires == ["second"]
    assert sched.active_timer_count == 1


async def test_cancel_timer() -> None:
    clock = TestClock()
    sched = Scheduler(clock=clock)
    fires: list[int] = []
    sched.set_timer("c", 0.5, lambda: fires.append(1))

    sched.cancel_timer("c")
    clock.advance(2.0)
    await sched.tick()
    assert fires == []
    assert sched.active_timer_count == 0


async def test_cancel_unknown_timer_is_noop() -> None:
    sched = Scheduler(clock=TestClock())
    sched.cancel_timer("nonexistent")  # must not raise


async def test_zero_interval_rejected() -> None:
    sched = Scheduler(clock=TestClock())
    with pytest.raises(ValueError, match="must be > 0"):
        sched.set_timer("bad", 0, lambda: None)
    with pytest.raises(ValueError, match="must be > 0"):
        sched.set_timer("bad", -1.5, lambda: None)


async def test_empty_name_rejected() -> None:
    sched = Scheduler(clock=TestClock())
    with pytest.raises(ValueError, match="non-empty"):
        sched.set_timer("", 1.0, lambda: None)


async def test_async_callback_awaited() -> None:
    clock = TestClock()
    sched = Scheduler(clock=clock)
    fires: list[str] = []

    async def cb() -> None:
        fires.append("async")

    sched.set_timer("a", 0.5, cb)
    clock.advance(0.5)
    await sched.tick()
    assert fires == ["async"]


async def test_callback_exception_does_not_crash_scheduler() -> None:
    clock = TestClock()
    sched = Scheduler(clock=clock)
    good_fires: list[int] = []

    sched.set_timer("bad", 0.5, lambda: 1 / 0)
    sched.set_timer("good", 0.5, lambda: good_fires.append(1))

    clock.advance(0.5)
    fired = await sched.tick()
    # Both fired (exception was caught), good's callback succeeded
    assert fired == 2
    assert good_fires == [1]


async def test_has_timer() -> None:
    sched = Scheduler(clock=TestClock())
    assert sched.has_timer("x") is False
    sched.set_timer("x", 1.0, lambda: None)
    assert sched.has_timer("x") is True
    sched.cancel_timer("x")
    assert sched.has_timer("x") is False
