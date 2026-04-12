# Changelog

All notable changes documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) + semver.

## [0.2.1] — 2026-04-12 — *Strategies + adapter wiring*

The minor release that makes the v0.2 live runtime *actually run* end-to-end. v0.2.0 shipped the foundation primitives; v0.2.1 wires them together so a strategy registered with the engine receives bars from a live adapter and updates the cache automatically.

### Added

- **`LiveStrategy`** (in `kairos.strategies.live`) — Actor-shaped strategy base with indicator declaration helpers (`add_rsi`, `add_ema`, `add_atr`), cache + state helpers (`free_balance`, `has_position`, `last_close`), and order shortcuts (`buy_bracket_pct`). Promoted from the V3StrategyActor pattern that emerged in Trading Autopilot's v3 work.
  - Indicators update automatically on every bar
  - `on_bar_ready(bar)` only fires after all indicators are warmed up (uses `Indicator.initialized` — `_count >= period`)
  - Filters incoming bars to its own `symbol` so multi-symbol engines don't cross-feed
  - Strategy authors set `self.symbol` and `self.timeframe` before passing to `engine.add_strategy()`

- **`LiveEngine.register_adapter(adapter)`** — wires adapter callbacks (bars, ticks, fills, order updates, disconnect, reconnect) to the engine's EventBus and MarketCache. The engine connects adapters on `.run()`, subscribes them to every `(symbol, timeframe)` declared by registered strategies, and disconnects them on `.stop()`.

- **Engine ↔ MarketCache binding**:
  - `LiveEngine.cache` is constructed by default (or accepts one via the `cache=` constructor arg)
  - At `add_actor` / `add_strategy` registration, the engine sets `actor.cache = self.cache` so actors and strategies have direct read access
  - Bars / ticks / fills / order updates from any registered adapter automatically populate the cache before being published on the bus

- **`LiveEngine.add_strategy(strategy)`** — finally functional. Sugar over `add_actor` with default events `{"bar", "order_filled"}`. Records the strategy's `(symbol, timeframe)` for adapter subscription on connect. De-duplicates so two strategies on the same stream produce one subscription.

### Changed

- `LiveEngine.run()` now: connects adapters → subscribes to streams → invokes `on_start` → spawns consumer tasks → blocks on shutdown. Disconnect-on-shutdown wired.

### Tests

**195 passing** (181 v0.2.0 + 14 new):

- 7 LiveStrategy tests: indicator warmup gating, symbol filtering, accessors, cache-binding, no-bracket-manager, subscription tracking, dedup
- 7 LiveEngine integration tests: adapter callbacks → cache → bus, fill flow, tick flow, disconnect/reconnect propagation, multi-adapter, registration safety

### Migration from 0.2.0

No breaking changes. v0.2.0 code keeps working unchanged. New strategies should subclass `LiveStrategy`:

```python
from kairos import LiveEngine, LiveStrategy
from kairos.actors import ActorConfig

class MyStrategy(LiveStrategy):
    def __init__(self, config):
        super().__init__(config)
        self.add_ema(8, "fast")
        self.add_ema(21, "slow")

    def on_bar_ready(self, bar):
        if self.fast_ema() > self.slow_ema() and self.free_balance() > 100:
            import asyncio
            asyncio.create_task(self.buy_bracket_pct(15.0, atr_multiplier=2.0))

strategy = MyStrategy(ActorConfig())
strategy.symbol = "BTCUSDC"
strategy.timeframe = "15m"

engine = LiveEngine()
engine.register_adapter(BinanceLive(api_key, api_secret))
engine.add_strategy(strategy)
await engine.run()
```

### What's still NOT in 0.2.1

- BinanceLive's user-data WebSocket implementation (the listenKey + WS session methods are documented `NotImplementedError` hooks). Until that lands in 0.2.2, fills arrive only via reconciliation polling.
- Adaptive features (§1-10 from vision) — still v0.3+

---

## [0.2.0] — 2026-04-12 — *Live runtime is here*

The first **production-ready** Kairos release. Ships the live trading runtime that lets you run strategies against a real exchange (or a mock for tests) with proper actor orchestration, atomic bracket orders, OCO semantics, and reconciliation.

This release is the foundation for the v0.3+ adaptive differentiators (see [`docs/vision.md`](docs/vision.md)). Everything below is engineered with a stable extension surface so v0.3 can plug in adaptive execution, continual tuning, and the IngestionActor without breaking the API.

### Added — Live runtime (`kairos.runtime`)

- **`Clock`** + `SystemClock` + `TestClock` — dependency-injected clock; `TestClock.advance(seconds)` makes the entire runtime deterministic in tests
- **`Scheduler`** — named periodic timers, idempotent `set_timer` / `cancel_timer`, async or sync callbacks, exceptions caught per timer, two run modes (production `.run()` and test `.tick()`)
- **`EventBus`** — typed asyncio queues per event kind; subscribers declare which kinds they care about; built-in kinds (`bar`, `tick`, `order_accepted`, `order_rejected`, `order_filled`, `adapter_disconnected`, `adapter_reconnected`, `shutdown`); custom signals via `signal:<name>`; typo-guard at subscribe + publish (`subscribe({"bars"})` raises *did you mean 'bar'?*)
- **`LiveEngine`** — orchestrator with `add_actor`, `add_strategy`, `register_adapter`, `run`, `stop`. Graceful shutdown (SIGTERM / SIGINT, 10s drain, 5s per-actor `on_stop`). **Exception isolation**: an actor raising marks itself `healthy=False`, publishes `signal:actor_degraded`, and stops receiving events; the engine survives.

### Added — Actors (`kairos.actors`)

- **`Actor`** ABC + **`ActorConfig`** (frozen dataclass)
- Default no-op hooks: `on_start`, `on_stop`, `on_bar`, `on_tick`, `on_order_filled`, `on_order_rejected`, `on_order_accepted`, `on_signal`, `on_adapter_disconnected`, `on_adapter_reconnected`
- Bound at registration: `self.log`, `self.clock`, `self._scheduler`, `self._event_bus`
- Helpers: `publish_signal(name, value)`, `set_timer(name, interval, cb)` (timers namespaced by actor), `cancel_timer`

### Added — Market cache (`kairos.cache`)

- **`MarketCache`** — bars, ticks, orders, positions (netted, spot-style), accounts, instruments
- Configurable retention per stream (default 500 bars, 100 ticks)
- O(1) lookups; snapshots returned as copied lists (iteration-safe)
- Indicator warmup gating: `cache.is_warmed_up(symbol, tf, required_bars)` for the engine to gate `on_bar_ready` calls
- **`Account`** — per-venue free / locked balance snapshot

### Added — Execution (`kairos.execution`)

- **`BracketManager`** — atomic bracket orders (entry + SL + TP linked by `bracket_id`)
  - **Atomicity guarantee**: if entry succeeds but SL or TP submission fails, the entry is immediately closed with a reverse MARKET order; the bracket is never left half-armed
  - **OCO**: if TP fills, SL is cancelled within 2s; if SL fills, TP is cancelled within 2s
  - Idempotent manual cancel; introspection (`bracket_for_order`, `active_brackets`)
- **`Reconciler`** — reconnect-time order/position state recovery
  - Diffs cache vs venue: recovers unknown open orders; marks disappeared cached orders as cancelled
  - Best-effort emission of synthetic fills for "filled during outage" scenarios (adapter-specific override hook)
  - Returns a `ReconciliationReport` with counts and errors
- **`ExecutionPolicy`** ABC + **`StaticPolicy`** baseline (MARKET entries, STOP_MARKET SL, LIMIT TP) — design hook for v0.3's `AdaptivePolicy` (vision §1)

### Added — Adapters (`kairos.adapters`)

- **`LiveAdapter`** Protocol — what the engine consumes from venue bridges
- **`BinanceLive`** — Binance Spot adapter (REST + market data WS + user-data WS), pattern adapted from hummingbot's reconnect logic (MIT, see [CREDITS.md](CREDITS.md)). User-data WS implementation hooks lock in v0.2.1.

### Added — Design hooks for v0.3+ differentiators (vision §1, §3, §6)

- **`Fill.explanation: dict | None`** — v0.2 leaves it `None`; v0.3 fills it with the "why card" record (indicators at entry, regime, win probability, counterfactual). Strategies/actors can read it today and get a no-op; tomorrow the same code lights up.
- **`Fill.bracket_id` + `Fill.strategy_name`** — first-class attribution for explainability and metrics
- **`ParameterProvider`** ABC + **`StaticProvider`** — design hook for v0.3 continual tuning. Strategies will accept a provider; v0.2 wires `StaticProvider` from profile JSONs; v0.3 will plug in `BayesianProvider`.

### Tests

**181 passing**, broken down:
- 54 from v0.1 (indicators, risk, positions, paper exchange-style, parity)
- 9 clock + 9 scheduler + 12 event bus + 8 actor + 13 live engine = **51 runtime**
- 24 market cache
- 8 execution policy + 14 bracket manager + 11 reconciler = **33 execution**
- 8 parameters
- 3 fill explanation hook
- 8 live adapter protocol

All pure Python; runs in <1 second.

### Documentation

- README rewritten with curation-plus-differentiation manifesto
- [`docs/vision.md`](docs/vision.md) — full product vision (manifesto, 10 differentiators, glossary, moat)
- [`docs/architecture.md`](docs/architecture.md) — runtime, actors, cache, execution wiring
- [`docs/getting-started.md`](docs/getting-started.md) — first live engine in 20 lines
- [`CREDITS.md`](CREDITS.md) — adopted primitives + license attribution
- New examples for the live runtime in [`examples/`](examples/)

### Migration from 0.1.x

The v0.1 surface (`Engine`, `Strategy`, `BacktestEngine`, `DataCatalog`, `parity` module) is **unchanged** and continues to work. `LiveEngine` is a separate class for live trading; you don't have to migrate paper / backtest code.

If you were using the v0.1 `Engine` for live trading (it had a basic mode), switch to `LiveEngine`:

```python
# v0.1
from kairos import Engine, Strategy
engine = Engine(exchange="binance", api_key="...", api_secret="...")

# v0.2
from kairos import LiveEngine, Actor, BinanceLive
adapter = BinanceLive(api_key="...", api_secret="...")
engine = LiveEngine()
engine.register_adapter(adapter)
```

See [`docs/getting-started.md`](docs/getting-started.md) for the full pattern.

### What's NOT yet in 0.2.0 (next)

- v0.2.1 (point release): full Binance user-data WS implementation (currently the listenKey + WS session methods raise `NotImplementedError` as documented hooks)
- v0.3.0: adaptive execution + continual tuning + why-card population (vision §1, §3, §6)
- v0.4.0: IngestionActor + counterfactual shadow (vision §7, §10) — *the meta-improvement engine that makes Kairos self-improving*

---

## [0.2.0a1] — 2026-04-12 — *Runtime alpha*

First Kairos-branded code release: Clock, Scheduler, EventBus, Actor base, LiveEngine skeleton. Tagged `v0.2.0a1`. Superseded by `0.2.0`.

## [0.2.0a0] — 2026-04-12 — *Kairos rebrand*

Rename release: `autopilot-engine` → `kairos-engine` on PyPI; Python module `autopilot` → `kairos`; GitHub repo `Vekkris76/autopilot-engine` → `Vekkris76/kairos`. No new features. Tagged `v0.2.0a0`. Superseded by `0.2.0`.

### Migration aliases

- `autopilot-engine==0.1.99` published as a 6-month deprecation alias: `pip install autopilot-engine` still works; emits `DeprecationWarning` on import; re-exports the public Kairos API.

---

## [0.1.0] — 2026-03 — *Initial release as autopilot-engine*

First public release under the original name `autopilot-engine`. Preserved for historical reference.

### Added
- Async event-driven engine (paper trading + backtest)
- 12 built-in indicators (EMA, SMA, RSI, ATR, MACD, Bollinger, Stochastic, VWAP, OBV, Donchian, ADX, HMA)
- Order manager (market, limit, stop variants, basic brackets)
- Position tracker with PnL netting
- Risk validator (balance, lot size, notional, drawdown, rate limits)
- Backtest engine with parquet data catalog
- Binance Spot adapter (CCXT + WebSocket — basic)
- Strategy marketplace (registry + builder)
- Analytics (Sharpe, Sortino, profit factor)

### Subsequent additions (pre-rename, in `main`)
- `kairos.parity` module — fill matcher with PASS/WARN/FAIL verdict for cross-engine parity checks (21 tests)
