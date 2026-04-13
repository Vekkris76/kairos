"""Tests for ``StrategySignal`` + ``LiveStrategy.emit_signal``.

The pub/sub pattern for strategy decisions that powers the shared-
engine multi-tenant pivot (Trading Autopilot ``pivot-to-shared-
engine-saas``). Strategies publish; downstream dispatchers consume.
"""

from __future__ import annotations

import asyncio

import pytest

from kairos import LiveEngine, LiveStrategy, StrategySignal, TestClock
from kairos.actors import ActorConfig
from kairos.runtime.event_bus import KNOWN_KINDS, UnknownEventKindError


pytestmark = pytest.mark.asyncio


# ── Dataclass ────────────────────────────────────────────────────


def test_strategy_signal_is_frozen_dataclass() -> None:
    sig = StrategySignal(
        strategy="dca_signal", symbol="BTCUSDC", action="buy_bracket",
    )
    with pytest.raises(Exception):
        sig.strategy = "other"   # type: ignore[misc]


def test_strategy_signal_minimal_construction() -> None:
    sig = StrategySignal(strategy="dca", symbol="BTCUSDC", action="sell_all")
    assert sig.strategy == "dca"
    assert sig.symbol == "BTCUSDC"
    assert sig.action == "sell_all"
    # Optional fields default sensibly
    assert sig.pct_of_capital == 0.0
    assert sig.sl_atr_mult is None
    assert sig.tp_atr_mult is None
    assert sig.price_level is None
    assert sig.order_ref is None
    assert sig.reason == ""
    assert sig.ts_ns == 0


def test_strategy_signal_full_construction() -> None:
    sig = StrategySignal(
        strategy="ema_confluence",
        symbol="ETHUSDC",
        action="buy_bracket",
        pct_of_capital=0.15,
        sl_atr_mult=2.0,
        tp_atr_mult=3.0,
        reason="EMA cross up + RSI > 50",
        ts_ns=1_700_000_000_000_000_000,
    )
    assert sig.pct_of_capital == 0.15
    assert sig.sl_atr_mult == 2.0
    assert sig.reason.startswith("EMA cross")


# ── Event bus registration ───────────────────────────────────────


def test_strategy_signal_is_known_event_kind() -> None:
    assert "strategy_signal" in KNOWN_KINDS


async def test_can_subscribe_to_strategy_signal_without_validation_error() -> None:
    engine = LiveEngine(clock=TestClock())
    # Should not raise UnknownEventKindError
    sub = engine.event_bus.subscribe(["strategy_signal"], name="test")
    assert sub is not None


async def test_unknown_signal_kind_still_rejected() -> None:
    engine = LiveEngine(clock=TestClock())
    with pytest.raises(UnknownEventKindError):
        engine.event_bus.subscribe(["nonexistent_kind"], name="test")


# ── emit_signal wiring ──────────────────────────────────────────


class _CapturingStrategy(LiveStrategy):
    """Test strategy that emits one signal on every bar ready."""

    def __init__(self, config: ActorConfig) -> None:
        super().__init__(config)
        self.bars_seen = 0

    def on_bar_ready(self, bar) -> None:   # noqa: ANN001
        self.bars_seen += 1
        self.emit_signal(
            "buy_bracket",
            pct_of_capital=0.1,
            sl_atr_mult=2.0,
            tp_atr_mult=3.0,
            reason=f"bar #{self.bars_seen}",
        )


async def test_emit_signal_publishes_to_bus() -> None:
    strategy = _CapturingStrategy(ActorConfig())
    strategy.symbol = "BTCUSDC"
    strategy.timeframe = "15m"

    engine = LiveEngine(clock=TestClock())
    engine.add_strategy(strategy)

    # Subscribe to strategy_signal BEFORE starting the engine
    sub = engine.event_bus.subscribe(
        ["strategy_signal"], name="capture",
    )

    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.05)

    # Drive a bar through the strategy (warmup isn't required for
    # _CapturingStrategy since it has no indicators).
    from kairos.types import Bar

    bar = Bar(
        symbol="BTCUSDC", timeframe="15m", timestamp=0,
        open=100, high=110, low=90, close=105, volume=1.0,
    )
    await engine.event_bus.publish("bar", bar)
    await asyncio.sleep(0.05)   # let the emit_signal task drain

    # Pull the signal off the subscriber's queue
    kind, event = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
    assert kind == "strategy_signal"
    assert isinstance(event, StrategySignal)
    assert event.action == "buy_bracket"
    assert event.symbol == "BTCUSDC"
    assert event.pct_of_capital == 0.1
    assert event.sl_atr_mult == 2.0
    assert event.reason == "bar #1"
    assert event.ts_ns > 0

    engine.stop()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()


async def test_emit_signal_sets_strategy_name_from_class() -> None:
    """Class name DCASignalStrategy → strategy='dcasignal'."""

    class DCASignalStrategy(LiveStrategy):
        def on_bar_ready(self, bar) -> None:   # noqa: ANN001
            self.emit_signal("buy_bracket", pct_of_capital=0.05)

    s = DCASignalStrategy(ActorConfig())
    s.symbol = "BTCUSDC"
    s.timeframe = "15m"

    engine = LiveEngine(clock=TestClock())
    engine.add_strategy(s)
    sub = engine.event_bus.subscribe(["strategy_signal"], name="capture")

    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.05)
    from kairos.types import Bar
    await engine.event_bus.publish(
        "bar",
        Bar(symbol="BTCUSDC", timeframe="15m", timestamp=0,
            open=1, high=1, low=1, close=1, volume=1),
    )
    await asyncio.sleep(0.05)

    _, event = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
    assert event.strategy == "dcasignal"

    engine.stop()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()


async def test_emit_signal_without_bus_is_safe_no_op() -> None:
    """Called before Actor registration → no crash, just debug log."""
    s = _CapturingStrategy(ActorConfig())
    s.symbol = "BTCUSDC"
    # Don't register with an engine → self._event_bus is None
    # This must not raise:
    s.emit_signal("buy_bracket", pct_of_capital=0.1)


async def test_emit_signal_respects_explicit_symbol_override() -> None:
    """Some strategies manage multiple symbols; allow per-call override."""

    class MultiSymbolStrategy(LiveStrategy):
        def on_bar_ready(self, bar) -> None:   # noqa: ANN001
            # Override self.symbol for this emission
            self.emit_signal(
                "buy_bracket", symbol="ETHUSDC", pct_of_capital=0.1,
            )

    s = MultiSymbolStrategy(ActorConfig())
    s.symbol = "BTCUSDC"   # default
    s.timeframe = "15m"

    engine = LiveEngine(clock=TestClock())
    engine.add_strategy(s)
    sub = engine.event_bus.subscribe(["strategy_signal"], name="capture")

    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.05)
    from kairos.types import Bar
    await engine.event_bus.publish(
        "bar",
        Bar(symbol="BTCUSDC", timeframe="15m", timestamp=0,
            open=1, high=1, low=1, close=1, volume=1),
    )
    await asyncio.sleep(0.05)

    _, event = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
    assert event.symbol == "ETHUSDC"   # override wins over self.symbol

    engine.stop()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()


async def test_emit_signal_multiple_subscribers_all_receive() -> None:
    """A dispatcher + a logger + a metrics actor can all subscribe."""
    s = _CapturingStrategy(ActorConfig())
    s.symbol = "BTCUSDC"
    s.timeframe = "15m"

    engine = LiveEngine(clock=TestClock())
    engine.add_strategy(s)

    subs = [
        engine.event_bus.subscribe(["strategy_signal"], name=f"s{i}")
        for i in range(3)
    ]

    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.05)
    from kairos.types import Bar
    await engine.event_bus.publish(
        "bar",
        Bar(symbol="BTCUSDC", timeframe="15m", timestamp=0,
            open=1, high=1, low=1, close=1, volume=1),
    )
    await asyncio.sleep(0.05)

    for sub in subs:
        _, event = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
        assert isinstance(event, StrategySignal)

    engine.stop()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
