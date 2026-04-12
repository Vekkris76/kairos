"""Tests for kairos.actors.base."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from kairos.actors import Actor, ActorConfig
from kairos.actors.base import ActorNotRegisteredError
from kairos.runtime.clock import TestClock
from kairos.runtime.event_bus import EventBus
from kairos.runtime.scheduler import Scheduler


@dataclass(frozen=True)
class _MyConfig(ActorConfig):
    threshold: float = 0.5


class _SpyActor(Actor):
    """Actor that records every event it receives."""

    def __init__(self, config: _MyConfig) -> None:
        super().__init__(config)
        self.events: list[tuple[str, object]] = []

    def on_start(self) -> None:
        self.events.append(("start", None))

    def on_stop(self) -> None:
        self.events.append(("stop", None))

    def on_bar(self, bar: object) -> None:
        self.events.append(("bar", bar))

    def on_order_filled(self, event: object) -> None:
        self.events.append(("filled", event))

    def on_signal(self, name: str, value: object) -> None:
        self.events.append((f"signal:{name}", value))


def _bind(actor: Actor, *, name: str = "test_actor") -> tuple[EventBus, Scheduler, TestClock]:
    """Helper: construct deps, bind actor, return them for inspection."""
    clock = TestClock()
    bus = EventBus()
    sched = Scheduler(clock=clock)
    actor._bind(name=name, clock=clock, scheduler=sched, event_bus=bus)
    return bus, sched, clock


def test_default_hooks_are_noops() -> None:
    """Bare Actor subclass with no overrides must not raise."""

    class BareActor(Actor):
        pass

    a = BareActor(ActorConfig())
    _bind(a)
    a.on_start()
    a.on_stop()
    a.on_bar(None)
    a.on_tick(None)
    a.on_order_filled(None)
    a.on_order_rejected(None)
    a.on_order_accepted(None)
    a.on_signal("x", None)
    a.on_adapter_disconnected("binance")
    a.on_adapter_reconnected("binance")


def test_bind_sets_runtime_handles() -> None:
    a = _SpyActor(_MyConfig())
    bus, sched, clock = _bind(a)
    assert a.log.name == "kairos.actor._SpyActor"
    assert a.clock is clock
    assert a._scheduler is sched
    assert a._event_bus is bus
    assert a.healthy is True


def test_publish_signal_before_bind_raises() -> None:
    a = _SpyActor(_MyConfig())
    with pytest.raises(ActorNotRegisteredError):
        a.publish_signal("x", 1)


def test_set_timer_before_bind_raises() -> None:
    a = _SpyActor(_MyConfig())
    with pytest.raises(ActorNotRegisteredError):
        a.set_timer("x", 1.0, lambda: None)


def test_cancel_timer_before_bind_is_noop() -> None:
    a = _SpyActor(_MyConfig())
    a.cancel_timer("nonexistent")  # must not raise


def test_set_timer_namespaces_by_actor_name() -> None:
    a = _SpyActor(_MyConfig())
    _, sched, _ = _bind(a, name="protector")
    a.set_timer("heartbeat", 1.0, lambda: None)
    assert sched.has_timer("protector:heartbeat") is True
    assert sched.has_timer("heartbeat") is False  # NOT in raw form


def test_actor_config_is_frozen() -> None:
    cfg = _MyConfig(threshold=0.7)
    with pytest.raises(Exception):  # FrozenInstanceError
        cfg.threshold = 0.9  # type: ignore[misc]


def test_healthy_starts_true() -> None:
    a = _SpyActor(_MyConfig())
    _bind(a)
    assert a.healthy is True
