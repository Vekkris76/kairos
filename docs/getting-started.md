# Getting Started

This guide covers the two main paths Kairos supports: **paper trading + backtest** (the v0.1 surface — `Engine`, `Strategy`, `BacktestEngine`) and **live trading** (the v0.2 surface — `LiveEngine`, `Actor`, `BinanceLive`).

Both coexist in the same package. Pick the one that matches what you're building.

## Installation

```bash
pip install kairos-engine
```

If you previously installed `autopilot-engine`, it still works (deprecation alias for 6 months) but please switch:

```bash
pip uninstall autopilot-engine
pip install kairos-engine
```

From source:

```bash
git clone https://github.com/Vekkris76/kairos.git
cd kairos
pip install -e ".[dev]"
```

## Path A — Paper trading + backtest (v0.1 API)

For experimenting, learning, and offline backtesting. No exchange account required.

### Your first paper bot

```python
from kairos import Engine, Strategy


class SimpleBot(Strategy):
    def setup(self):
        self.add_ema(8, "fast")
        self.add_ema(21, "slow")

    def on_bar(self, bar):
        if self.fast_ema() > self.slow_ema() and not self.has_position():
            self.buy(20)         # 20% of balance
        elif self.fast_ema() < self.slow_ema() and self.has_position():
            self.sell_all()


engine = Engine(exchange="paper", initial_balance=1000)
engine.add(SimpleBot, symbol="BTCUSDC", timeframe="1h")
engine.run()
```

Run it: `python my_bot.py`. The paper exchange simulates fills at the bar close.

### Backtesting

Test on historical data before risking real money:

```python
from kairos import BacktestEngine
from kairos.types import Bar

bars = [
    Bar("BTCUSDC", "1h", 1700000000000, 70000, 70500, 69500, 70200, 100),
    Bar("BTCUSDC", "1h", 1700003600000, 70200, 71000, 70000, 70800, 150),
    # ... thousands more, loaded from CSV / parquet / API
]

bt = BacktestEngine(initial_balance=1000)
bt.load_bars("BTCUSDC", "1h", bars)
bt.add(SimpleBot, symbol="BTCUSDC", timeframe="1h")
results = bt.run()

print(results)
# === Backtest Results ===
# Trades:        42
# Win Rate:      61.9%
# Return:        +12.50%
# Max Drawdown:  3.20%
```

## Path B — Live trading (v0.2 API)

For production: real money, real exchange, real fills, real risk.

This path uses Kairos's new live runtime: `LiveEngine` orchestrates strategies and actors; `BinanceLive` (the adapter) talks to the exchange; `MarketCache` keeps the in-memory state; `BracketManager` handles atomic SL/TP brackets with OCO.

### A minimal live engine

```python
import asyncio
import logging

from kairos import Actor, ActorConfig, BinanceLive, LiveEngine

logging.basicConfig(level=logging.INFO)


class HeartbeatActor(Actor):
    """Tiny actor: logs every minute that we're alive."""

    def on_start(self):
        self.set_timer("heartbeat", 60.0, self._beat)

    def _beat(self):
        self.log.info("💓 alive")


async def main():
    adapter = BinanceLive(
        api_key="YOUR_API_KEY",
        api_secret="YOUR_API_SECRET",
        testnet=False,         # True for Binance testnet
    )

    engine = LiveEngine()
    engine.add_actor(
        HeartbeatActor(ActorConfig()),
        events={"bar"},        # actor cares about bars (any event kind works)
    )

    # Wire the adapter (engine connects, subscribes, drives the loop)
    # Strategy registration lands in v0.2.1 — for now this skeleton runs
    # actors against an empty event stream.

    await engine.run()         # blocks until SIGTERM/SIGINT or .stop()


if __name__ == "__main__":
    asyncio.run(main())
```

The engine handles graceful shutdown automatically (`Ctrl+C` or `docker compose down` → 10 s drain → `on_stop` for every actor → exit 0).

> **Important**: create API keys with **trading permissions only** — never enable withdrawals. Whitelist your server IP.

### Actors are first-class

The five core SaaS actors (Protection, Intelligence, Learning, Notification, ParameterTuner) — see the [Trading Autopilot vision doc](https://github.com/Vekkris76/kairos/blob/main/docs/vision.md) — all subclass `kairos.Actor`. They respond to events the engine routes to them:

```python
from kairos import Actor, ActorConfig
from kairos.types import OrderSide


class ProtectionActor(Actor):
    """Halts trading when daily loss > 3% or drawdown > 15%."""

    def __init__(self, config):
        super().__init__(config)
        self._daily_pnl = 0.0
        self._peak_equity = 0.0

    def on_start(self):
        # Reset daily counter at UTC midnight
        from datetime import timedelta
        self.set_timer("daily_reset", timedelta(hours=24), self._reset_day)

    def on_order_filled(self, fill):
        if fill.side == OrderSide.SELL:
            # Update PnL from realized portion (reads cache.position for context)
            pos = self.cache.position(fill.symbol) if self.cache else None
            if pos:
                self._daily_pnl = pos.realized_pnl

        if self._daily_pnl < -0.03 * self._peak_equity:
            self.publish_signal("risk_state", "HALTED")
            self.notify_telegram("🛑 Daily loss limit hit — halted")  # SaaS-side helper

    def _reset_day(self, _event):
        self._daily_pnl = 0.0
```

When you register the actor, declare what events it wants:

```python
engine.add_actor(
    ProtectionActor(ActorConfig()),
    events={"order_filled", "signal:position_opened"},
)
```

### Bracket orders

The `BracketManager` (in `kairos.execution`) submits an entry plus stop-loss plus take-profit atomically, with OCO:

```python
from kairos import BracketManager, OrderSide

bm = BracketManager(adapter=adapter)
bracket = await bm.submit_bracket(
    symbol="BTCUSDC",
    side=OrderSide.BUY,
    quantity=0.001,
    sl_price=49_000.0,
    tp_price=52_000.0,
    reference_price=50_000.0,
)
print(bracket.bracket_id, bracket.state)   # "br-...", "armed"
```

If the entry succeeds but the SL or TP submission fails, the entry is **immediately closed with a reverse MARKET order** — the bracket is never left half-armed. If TP fills, the SL is cancelled within 2 s; if SL fills, TP is cancelled. See [`docs/architecture.md`](architecture.md) for the full state machine.

### Reconciliation on reconnect

The `Reconciler` diffs the cache vs the venue after a WebSocket disconnect:

```python
from kairos import Reconciler

reconciler = Reconciler(adapter=adapter, cache=engine.cache)
report = await reconciler.reconcile()
print(report)    # ReconciliationReport(recovered_orders=2, cancels_recorded=1, ...)
```

The engine wires this up automatically when the adapter emits `adapter_reconnected`.

## Path C — Cross-engine parity (`kairos.parity`)

For comparing two engines (e.g. v0.1 vs v0.2, or your engine vs another) on the same fills:

```python
from kairos.parity import FillRecord, match_fills

baseline = [FillRecord(strategy_name="x", symbol="BTCUSDC",
                       side="BUY", quantity=0.1, price=50000.0, ts_ns=...)]
candidate = [FillRecord(strategy_name="x", symbol="BTCUSDC",
                        side="BUY", quantity=0.1, price=50000.0, ts_ns=...)]

report = match_fills(baseline, candidate)
print(report.verdict)             # "PASS" | "WARN" | "FAIL"
print(report.pnl_divergence_pct)  # 0.0
```

Configurable tolerances: ±1% quantity, ±900 s time, ±0.1% price (defaults).

## Multi-strategy

Run multiple strategies on multiple pairs simultaneously. The v0.1 path:

```python
engine = Engine(exchange="paper", initial_balance=1000)
engine.add(TrendFollower, symbol="BTCUSDC", timeframe="1h")
engine.add(MeanReversion, symbol="ETHUSDC", timeframe="15m")
engine.add(GridBot, symbol="SOLUSDC", timeframe="4h")
engine.run()
```

The v0.2 path: same idea — register multiple actors against the `LiveEngine`. Strategy class wiring on `LiveEngine` lands in v0.2.1.

## Next steps

- [Architecture](architecture.md) — runtime, actors, cache, execution wiring
- [Strategy Guide](strategy-guide.md) — every available method on `Strategy` / `Actor`
- [Indicator Reference](indicators.md) — 12 built-in indicators
- [Exchange Setup](exchange-setup.md) — Binance API key configuration
- [Backtesting Guide](backtesting.md) — historical data, walkforward, metrics
- [Vision](vision.md) — what Kairos is becoming (the v0.3+ adaptive layer)
- [CREDITS.md](../CREDITS.md) — open-source primitives we adopt + license attribution
