"""Kairos runtime — async live engine, clock, scheduler, event bus.

Public surface:
    Clock, SystemClock, TestClock
    Scheduler
    EventBus
    LiveEngine

This package is the foundation of Kairos v0.2. It replaces the simpler
``kairos.engine.Engine`` class (kept for v0.1 paper/backtest use cases)
when ``LiveEngine`` is what you need: live trading, multi-actor, async.
"""

from __future__ import annotations

from kairos.runtime.clock import Clock, SystemClock, TestClock
from kairos.runtime.event_bus import EventBus, EventKind, UnknownEventKindError
from kairos.runtime.live_engine import LiveEngine
from kairos.runtime.scheduler import Scheduler

__all__ = [
    "Clock",
    "EventBus",
    "EventKind",
    "LiveEngine",
    "Scheduler",
    "SystemClock",
    "TestClock",
    "UnknownEventKindError",
]
