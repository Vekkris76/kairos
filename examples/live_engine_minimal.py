"""Minimal LiveEngine example — register an actor, run, gracefully shut down.

This example does NOT trade. It demonstrates the v0.2 live runtime
shape: an Actor receives events (we publish a few synthetic ones for
illustration), the Scheduler fires a heartbeat timer, and the engine
shuts down cleanly on Ctrl+C.

For a strategy-driven live example, wait for v0.2.1 (Strategy class
wiring on LiveEngine) or run a v0.1 ``Engine`` for paper trading.

Run::

    python examples/live_engine_minimal.py
"""

from __future__ import annotations

import asyncio
import logging

from kairos import Actor, ActorConfig, LiveEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


class HeartbeatActor(Actor):
    """Logs a beat every 5 seconds. Demonstrates timers + lifecycle."""

    def on_start(self) -> None:
        self.log.info("HeartbeatActor starting")
        self.set_timer("heartbeat", 5.0, self._beat)

    def on_stop(self) -> None:
        self.log.info("HeartbeatActor stopping (cleanup hook)")

    def _beat(self) -> None:
        self.log.info("💓 alive")


class FillLogger(Actor):
    """Logs every fill the engine routes here. Demonstrates events."""

    def on_order_filled(self, fill) -> None:  # noqa: ANN001
        self.log.info(
            f"Fill: {fill.side.name} {fill.quantity} {fill.symbol} @ {fill.price}"
        )


async def _publish_demo_events(engine: LiveEngine) -> None:
    """Tiny demo: publish synthetic events so the actors have something to do."""
    from kairos.types import Fill, OrderSide

    await asyncio.sleep(2)  # let the engine warm up
    await engine.event_bus.publish(
        "order_filled",
        Fill(
            order_id="demo-1",
            trade_id="t-1",
            symbol="BTCUSDC",
            side=OrderSide.BUY,
            price=50_000.0,
            quantity=0.001,
            commission=0.05,
            timestamp=0,
        ),
    )


async def main() -> None:
    engine = LiveEngine()
    engine.add_actor(HeartbeatActor(ActorConfig()), events={"bar"})
    engine.add_actor(FillLogger(ActorConfig()), events={"order_filled"})

    # Spawn a side task that publishes a demo fill after 2s
    asyncio.create_task(_publish_demo_events(engine))

    # Run forever (Ctrl+C to stop)
    await engine.run()


if __name__ == "__main__":
    asyncio.run(main())
