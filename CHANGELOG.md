# Changelog

All notable changes documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) + semver.

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
