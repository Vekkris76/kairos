"""Tests for kairos.strategies.live.LiveStrategy."""

from __future__ import annotations

import pytest

from kairos import Account, LiveEngine, LiveStrategy, MarketCache, TestClock
from kairos.actors import ActorConfig
from kairos.types import Bar


pytestmark = pytest.mark.asyncio


def _bar(symbol: str = "BTCUSDC", tf: str = "15m", close: float = 50_000.0) -> Bar:
    return Bar(
        symbol=symbol,
        timeframe=tf,
        timestamp=0,
        open=close - 10,
        high=close + 20,
        low=close - 30,
        close=close,
        volume=100.0,
    )


class _SimpleStrategy(LiveStrategy):
    """Trivial strategy: counts on_bar_ready calls + records them."""

    def __init__(self, config: ActorConfig) -> None:
        super().__init__(config)
        self.add_ema(3, "fast")
        self.bars_seen = 0
        self.ready_calls = 0
        self.bar_history: list = []

    def on_bar_ready(self, bar) -> None:  # noqa: ANN001
        self.ready_calls += 1
        self.bar_history.append(bar)


# ── LiveStrategy basics ─────────────────────────────────────────


async def test_live_strategy_indicator_warmup_gates_on_bar_ready() -> None:
    strategy = _SimpleStrategy(ActorConfig())
    strategy.symbol = "BTCUSDC"
    strategy.timeframe = "15m"

    engine = LiveEngine(clock=TestClock())
    engine.add_strategy(strategy)

    import asyncio

    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.02)

    # First 2 bars: not warmed (EMA(3) needs 3 values)
    await engine.event_bus.publish("bar", _bar(close=100))
    await engine.event_bus.publish("bar", _bar(close=101))
    await asyncio.sleep(0.05)
    assert strategy.ready_calls == 0

    # Third bar: warmed
    await engine.event_bus.publish("bar", _bar(close=102))
    await asyncio.sleep(0.05)
    assert strategy.ready_calls == 1

    engine.stop()
    await task


async def test_live_strategy_filters_to_own_symbol() -> None:
    strategy = _SimpleStrategy(ActorConfig())
    strategy.symbol = "BTCUSDC"
    strategy.timeframe = "15m"

    engine = LiveEngine(clock=TestClock())
    engine.add_strategy(strategy)

    import asyncio

    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.02)

    # Warm up with own bars first
    for _ in range(3):
        await engine.event_bus.publish("bar", _bar(symbol="BTCUSDC"))
    await asyncio.sleep(0.05)
    initial_ready = strategy.ready_calls

    # Now publish a bar for a different symbol — should NOT be processed
    await engine.event_bus.publish("bar", _bar(symbol="ETHUSDC", close=3000))
    await asyncio.sleep(0.05)
    assert strategy.ready_calls == initial_ready

    engine.stop()
    await task


async def test_live_strategy_indicator_accessors() -> None:
    strategy = _SimpleStrategy(ActorConfig())
    strategy.symbol = "BTCUSDC"
    strategy.timeframe = "15m"

    engine = LiveEngine(clock=TestClock())
    engine.add_strategy(strategy)

    import asyncio

    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.02)
    await engine.event_bus.publish("bar", _bar(close=100))
    await engine.event_bus.publish("bar", _bar(close=110))
    await engine.event_bus.publish("bar", _bar(close=120))
    await asyncio.sleep(0.05)

    # EMA(3) of [100, 110, 120] is somewhere between 100 and 120
    assert strategy.fast_ema() > 100
    assert strategy.fast_ema() <= 120

    engine.stop()
    await task


async def test_live_strategy_cache_helpers_reflect_engine_state() -> None:
    strategy = _SimpleStrategy(ActorConfig())
    strategy.symbol = "BTCUSDC"
    strategy.timeframe = "15m"

    cache = MarketCache()
    engine = LiveEngine(clock=TestClock(), cache=cache)
    engine.add_strategy(strategy)

    # Pre-populate cache
    cache.ingest_account(
        Account(venue="binance", balances_free={"USDC": 1000.0})
    )
    cache.ingest_bar(_bar(close=50_500))

    import asyncio

    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.05)

    # Cache binding worked
    assert strategy.cache is cache
    assert strategy.free_balance("USDC") == 1000.0
    assert strategy.last_close() == 50_500
    assert strategy.has_position() is False

    engine.stop()
    await task


async def test_live_strategy_buy_bracket_pct_without_bracket_manager() -> None:
    strategy = _SimpleStrategy(ActorConfig())
    strategy.symbol = "BTCUSDC"
    strategy.timeframe = "15m"

    engine = LiveEngine(clock=TestClock())
    engine.add_strategy(strategy)

    import asyncio

    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.02)

    # No bracket_manager wired → returns False, doesn't crash
    result = await strategy.buy_bracket_pct(15.0)
    assert result is False

    engine.stop()
    await task


async def test_engine_remembers_strategy_subscriptions() -> None:
    """add_strategy with declared (symbol, timeframe) populates the
    subscription list that adapters honor on connect."""
    strategy = _SimpleStrategy(ActorConfig())
    strategy.symbol = "BTCUSDC"
    strategy.timeframe = "15m"

    strategy_b = _SimpleStrategy(ActorConfig())
    strategy_b.symbol = "ETHUSDC"
    strategy_b.timeframe = "1h"

    engine = LiveEngine(clock=TestClock())
    engine.add_strategy(strategy)
    engine.add_strategy(strategy_b)

    assert ("BTCUSDC", "15m") in engine._strategy_subscriptions
    assert ("ETHUSDC", "1h") in engine._strategy_subscriptions
    assert len(engine._strategy_subscriptions) == 2


async def test_engine_dedupes_strategy_subscriptions() -> None:
    """Two strategies on the same (symbol, timeframe) → one subscription."""
    s1 = _SimpleStrategy(ActorConfig())
    s1.symbol = "BTCUSDC"
    s1.timeframe = "15m"

    s2 = _SimpleStrategy(ActorConfig())
    s2.symbol = "BTCUSDC"
    s2.timeframe = "15m"

    engine = LiveEngine(clock=TestClock())
    engine.add_strategy(s1)
    engine.add_strategy(s2)

    assert engine._strategy_subscriptions.count(("BTCUSDC", "15m")) == 1
