"""Tests for kairos.runtime.live_engine.LiveEngine."""

from __future__ import annotations

import asyncio

import pytest

from kairos.actors import Actor, ActorConfig
from kairos.runtime.clock import TestClock
from kairos.runtime.event_bus import UnknownEventKindError
from kairos.runtime.live_engine import LiveEngine


pytestmark = pytest.mark.asyncio


class _SpyActor(Actor):
    def __init__(self) -> None:
        super().__init__(ActorConfig())
        self.events: list[tuple[str, object]] = []
        self.start_called = False
        self.stop_called = False

    def on_start(self) -> None:
        self.start_called = True

    def on_stop(self) -> None:
        self.stop_called = True

    def on_bar(self, bar: object) -> None:
        self.events.append(("bar", bar))

    def on_order_filled(self, event: object) -> None:
        self.events.append(("filled", event))

    def on_signal(self, name: str, value: object) -> None:
        self.events.append((f"signal:{name}", value))


class _RaisingActor(Actor):
    def __init__(self) -> None:
        super().__init__(ActorConfig())
        self.bar_count = 0

    def on_bar(self, bar: object) -> None:
        self.bar_count += 1
        raise RuntimeError("boom")


async def _run_briefly(engine: LiveEngine, *, after: float = 0.05) -> None:
    """Run the engine, schedule a stop after `after` seconds, await done."""
    task = asyncio.create_task(engine.run())
    await asyncio.sleep(after)
    engine.stop()
    await task


# ── Registration ────────────────────────────────────────────────


async def test_add_actor_with_unknown_event_raises() -> None:
    engine = LiveEngine(clock=TestClock())
    a = _SpyActor()
    with pytest.raises(UnknownEventKindError):
        engine.add_actor(a, events={"bars"})  # typo


async def test_add_actor_with_empty_events_raises() -> None:
    engine = LiveEngine(clock=TestClock())
    a = _SpyActor()
    with pytest.raises(ValueError, match="at least one"):
        engine.add_actor(a, events=set())


async def test_actor_count_reflects_registrations() -> None:
    engine = LiveEngine(clock=TestClock())
    assert engine.actor_count == 0
    engine.add_actor(_SpyActor(), events={"bar"})
    engine.add_actor(_SpyActor(), events={"order_filled"})
    assert engine.actor_count == 2


async def test_cannot_add_actor_after_run_starts() -> None:
    engine = LiveEngine(clock=TestClock())
    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.02)
    with pytest.raises(RuntimeError, match="while engine is running"):
        engine.add_actor(_SpyActor(), events={"bar"})
    engine.stop()
    await task


# ── Lifecycle ──────────────────────────────────────────────────


async def test_on_start_called_for_every_actor() -> None:
    engine = LiveEngine(clock=TestClock())
    a = _SpyActor()
    b = _SpyActor()
    engine.add_actor(a, events={"bar"})
    engine.add_actor(b, events={"bar"})

    await _run_briefly(engine)

    assert a.start_called is True
    assert b.start_called is True


async def test_on_stop_called_on_shutdown() -> None:
    engine = LiveEngine(clock=TestClock())
    a = _SpyActor()
    engine.add_actor(a, events={"bar"})

    await _run_briefly(engine)
    assert a.stop_called is True


async def test_double_run_raises() -> None:
    engine = LiveEngine(clock=TestClock())
    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.02)
    with pytest.raises(RuntimeError, match="already running"):
        await engine.run()
    engine.stop()
    await task


# ── Event routing ──────────────────────────────────────────────


async def test_event_routed_to_subscribed_actor() -> None:
    engine = LiveEngine(clock=TestClock())
    a = _SpyActor()
    engine.add_actor(a, events={"bar"})

    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.02)
    await engine.event_bus.publish("bar", {"close": 100.0})
    await asyncio.sleep(0.05)
    engine.stop()
    await task

    assert ("bar", {"close": 100.0}) in a.events


async def test_event_not_delivered_to_unsubscribed_actor() -> None:
    engine = LiveEngine(clock=TestClock())
    bar_only = _SpyActor()
    fill_only = _SpyActor()
    engine.add_actor(bar_only, events={"bar"})
    engine.add_actor(fill_only, events={"order_filled"})

    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.02)
    await engine.event_bus.publish("bar", "B")
    await engine.event_bus.publish("order_filled", "F")
    await asyncio.sleep(0.05)
    engine.stop()
    await task

    assert any(e[0] == "bar" for e in bar_only.events)
    assert not any(e[0] == "filled" for e in bar_only.events)
    assert any(e[0] == "filled" for e in fill_only.events)
    assert not any(e[0] == "bar" for e in fill_only.events)


async def test_signal_routing() -> None:
    engine = LiveEngine(clock=TestClock())
    listener = _SpyActor()
    engine.add_actor(listener, events={"signal:risk_state"})

    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.02)
    await engine.event_bus.publish("signal:risk_state", "HALTED")
    await asyncio.sleep(0.05)
    engine.stop()
    await task

    assert ("signal:risk_state", "HALTED") in listener.events


# ── Exception isolation ────────────────────────────────────────


async def test_actor_exception_marks_degraded_engine_survives() -> None:
    engine = LiveEngine(clock=TestClock())
    raiser = _RaisingActor()
    healthy = _SpyActor()
    engine.add_actor(raiser, events={"bar"})
    engine.add_actor(healthy, events={"bar"})

    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.02)
    await engine.event_bus.publish("bar", "first")
    await asyncio.sleep(0.05)
    await engine.event_bus.publish("bar", "second")
    await asyncio.sleep(0.05)
    engine.stop()
    await task

    # Raiser saw the first event (then raised), got degraded, did NOT see the second
    assert raiser.bar_count == 1
    assert raiser.healthy is False
    # Healthy actor saw both
    assert ("bar", "first") in healthy.events
    assert ("bar", "second") in healthy.events
    assert healthy.healthy is True
    # healthy_actor_count reflects degradation
    assert engine.healthy_actor_count == 1
    assert engine.actor_count == 2


async def test_degraded_signal_published_on_failure() -> None:
    engine = LiveEngine(clock=TestClock())
    raiser = _RaisingActor()
    listener = _SpyActor()
    engine.add_actor(raiser, events={"bar"})
    engine.add_actor(listener, events={"signal:actor_degraded"})

    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.02)
    await engine.event_bus.publish("bar", "trigger")
    await asyncio.sleep(0.05)
    engine.stop()
    await task

    degraded_signals = [e for e in listener.events if e[0] == "signal:actor_degraded"]
    assert len(degraded_signals) == 1
    payload = degraded_signals[0][1]
    assert payload["actor"].startswith("_RaisingActor")
    assert payload["hook"] == "bar"
    assert "boom" in payload["error"]
