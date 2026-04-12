# Architecture

How Kairos is structured. Read this before extending the runtime or writing a new adapter.

## High level

Kairos has two engines for two use cases:

```
┌────────────────────────────────────────────────────────────────┐
│  v0.1 PAPER / BACKTEST PATH                                    │
│                                                                │
│  Engine + Strategy + BacktestEngine + DataCatalog              │
│  → simple, synchronous, in-memory                              │
│  → for learning, prototyping, and offline simulation           │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│  v0.2 LIVE PATH                                                │
│                                                                │
│  LiveEngine + Actor + MarketCache + BracketManager + Adapter   │
│  → async event loop, multi-actor, atomic brackets, OCO         │
│  → for production live trading                                 │
└────────────────────────────────────────────────────────────────┘
```

Both share `kairos.types` (Bar, Order, Fill, Position, Instrument, OrderSide, etc.) so types flow between them.

## v0.2 live runtime layout

```
                           ┌───────────────────┐
                           │  Strategy code    │
                           │  (your bot)       │
                           └────────┬──────────┘
                                    │ inherits
                                    │
                           ┌────────▼──────────┐
                           │     Strategy      │
                           │  (kairos)         │
                           └────────┬──────────┘
                                    │
                                    │ registered with
                                    │
┌──────────────────────────────────▼────────────────────────────────┐
│                          LiveEngine                                │
│                                                                    │
│  ┌──────────┐  ┌────────────┐  ┌──────────┐  ┌─────────────────┐   │
│  │ EventBus │  │ Scheduler  │  │  Clock   │  │  MarketCache    │   │
│  │  (queues │  │  (timers)  │  │ (system  │  │   (bars/ticks/  │   │
│  │   per    │  │            │  │   or     │  │  orders/posn)   │   │
│  │  kind)   │  │            │  │   test)  │  │                 │   │
│  └────┬─────┘  └────┬───────┘  └──────────┘  └────────┬────────┘   │
│       │             │                                  │            │
│       │             │  fan-out                         │  reads     │
│       │             ▼                                  │            │
│   ┌───┴───────────────────────────────────────────────▼──────┐    │
│   │                  Actors (Protection, Intelligence,        │    │
│   │              Learning, Notification, ParameterTuner)      │    │
│   │                                                            │    │
│   │   - on_bar / on_tick / on_order_filled / on_signal /      │    │
│   │     on_adapter_disconnected / on_adapter_reconnected      │    │
│   │   - publish_signal — emits to other actors via the bus    │    │
│   │   - set_timer — schedules periodic callbacks              │    │
│   └────────────────────────────────────────────────────────────┘    │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                   BracketManager + Reconciler                │  │
│  │                                                              │  │
│  │   submits orders via the adapter; ensures atomicity (entry+  │  │
│  │   SL+TP all-or-none) and OCO (TP fill cancels SL, etc.)      │  │
│  └──────────────────────────────┬───────────────────────────────┘  │
└───────────────────────────────┼─────────────────────────────────┘
                                │
                                │ submit / cancel orders
                                ▼
                       ┌────────────────────┐
                       │  LiveAdapter       │       (Protocol)
                       │                    │
                       │  - BinanceLive     │       (concrete v0.2)
                       │  - KrakenLive ...  │       (future)
                       └─────────┬──────────┘
                                 │
                                 │ REST + WebSocket
                                 ▼
                          ┌────────────┐
                          │  Exchange  │
                          │ (Binance)  │
                          └────────────┘
```

## Module map

| Package | Purpose |
|---------|---------|
| `kairos.runtime` | `Clock`, `Scheduler`, `EventBus`, `LiveEngine`, `ParameterProvider` |
| `kairos.actors` | `Actor` ABC + `ActorConfig` |
| `kairos.cache` | `MarketCache` + `Account` |
| `kairos.execution` | `BracketManager`, `Reconciler`, `ExecutionPolicy` + `StaticPolicy` |
| `kairos.adapters` | `LiveAdapter` Protocol + `BinanceLive` |
| `kairos.parity` | Cross-engine fill matcher (already in v0.1) |
| `kairos.indicators` | 12 indicators (v0.1) |
| `kairos.orders` | Basic `OrderManager` + `PositionTracker` (v0.1) |
| `kairos.exchanges` | v0.1 `BinanceAdapter` + `BinanceWebSocket` (used by `BinanceLive`) |
| `kairos.backtest` | `BacktestEngine` + `DataCatalog` (v0.1) |
| `kairos.marketplace` | Strategy registry + builder (v0.1) |
| `kairos.types` | `Bar`, `Order`, `Fill`, `Position`, `Instrument`, enums |

## Event flow (live)

```
Adapter (Binance WS frame arrives)
    │
    │  parse → Bar / Tick / Fill / OrderUpdate
    │
    ▼
Adapter callback (set by engine at register time)
    │
    │  await engine.event_bus.publish("bar", bar)
    │
    ▼
EventBus
    │
    │  fan out to subscribers of "bar"
    │
    ├──► Actor A's queue
    ├──► Actor B's queue
    └──► Strategy queue
              │
              │  consumer task awaits queue.get(), calls hook
              │
              ▼
       Actor.on_bar(bar)  /  Strategy.on_bar(bar)
              │
              │  may publish signals or submit orders
              │
              ▼
       (signals) → EventBus → other actors
       (orders)  → BracketManager → adapter.submit_order → Exchange
```

Single-process. Single asyncio loop. No threads. No locks (consumers are single-tasked).

## Lifecycle

```
LiveEngine.run()
  │
  ├─ for each actor: actor.on_start()
  │
  ├─ spawn one consumer task per actor (drains its queue)
  ├─ spawn the scheduler task (fires timers)
  │
  ├─ block until shutdown_event set (SIGTERM / SIGINT / .stop())
  │
  └─ shutdown:
       ├─ scheduler.stop()
       ├─ cancel consumer tasks (drain in-flight items)
       ├─ for each actor (LIFO): on_stop() with 5 s timeout
       ├─ adapter.disconnect()
       └─ event_bus.close()
       exit 0
```

## Exception isolation

If `Actor.on_bar()` raises:

1. Engine catches the exception in `_route()`
2. Logs full traceback at `ERROR`
3. Sets `actor.healthy = False`
4. Publishes `signal:actor_degraded` with `{actor, hook, error}`
5. Skips further events to that actor (it's done — no retries)
6. **Engine survives**; other actors keep receiving events

This is the foundational contract: one bad actor never takes down the whole process. The SaaS layer can listen for `signal:actor_degraded` and alert the operator.

## Bracket order state machine

```
        submit_bracket()
              │
              ▼
         ┌─────────┐  entry submission fails
         │ pending │ ────────────────────► raise (no orders)
         └────┬────┘
              │ entry succeeds
              ▼
         ┌─────────┐  SL submission fails
         │ pending │ ────────────────────► reverse-close entry,
         │  (entry │                       state = "failed",
         │ filled, │                       BracketSubmissionError
         │ no exit)│
         └────┬────┘
              │ SL ok
              ▼
         ┌─────────┐  TP submission fails
         │ pending │ ────────────────────► cancel SL,
         │  (entry,│                       reverse-close entry,
         │ SL armed│                       state = "failed",
         │  no TP) │                       BracketSubmissionError
         └────┬────┘
              │ TP ok
              ▼
         ┌─────────┐  TP fills            ┌───────────┐
         │  armed  │ ──────────────────►  │ completed │
         │ (entry, │                      │ exit_type │
         │ SL & TP │  SL fills            │ = "tp"|   │
         │  ready) │ ──────────────────►  │   "sl"    │
         └─────────┘                      └───────────┘
              │                                ▲
              │ cancel_bracket()               │
              └────────────────────────────────┘
                       exit_type = "manual"
```

When TP fills, the OCO sibling (SL) is cancelled within 2 s. Same for SL → TP.

## Curation principle

Per the [vision](vision.md), Kairos curates the best primitives the open-source ecosystem provides and adds a single proprietary layer on top: **adaptivity**.

What we adopt (with attribution in [`CREDITS.md`](../CREDITS.md)):

- **`ccxt`** for non-Binance exchange transport (200+ venues handled by one library)
- **`pandas-ta`** for indicator math reference
- **`hummingbot`** patterns for WebSocket reconnect + rate limiting (we wrote our own; pattern attribution only)
- **`NautilusTrader`** for order state machine design (study only — clean-room implementation; LGPL means we can't vendor)
- **`Jesse` / `Freqtrade`** for strategy lifecycle conventions

What is **only Kairos**:

- The adaptive runtime layer (`ParameterProvider`, `ExecutionPolicy` design hooks for v0.3+)
- The IngestionActor (the meta-improvement engine — coming in v0.4)
- The `parity` module (cross-engine fill matcher with verdict logic)
- The `Why card` explanation field on `Fill` (design hook in v0.2, populated v0.3)

## Design hooks for v0.3+

Three extension points are wired in v0.2 but no-op until v0.3+:

| Hook | Where | What v0.3+ does |
|------|-------|------------------|
| `Fill.explanation: dict \| None` | `kairos.types` | v0.3 fills it with indicators / regime / win probability for the **why card** UI feature |
| `ParameterProvider` | `kairos.runtime.parameters` | v0.3 plugs in `BayesianProvider` for **continual tuning** (Bayesian posterior per parameter, updated per trade) |
| `ExecutionPolicy` | `kairos.execution.policy` | v0.3 plugs in `AdaptivePolicy` for **adaptive execution** (learn optimal order type per regime × spread) |

These let v0.3 work add value without changing the v0.2 API. Strategies and actors compiled against v0.2 keep running on v0.3+ with no changes.

## Testing

- 181 tests, all pure Python, run in <1 s
- Run with `pytest`
- `TestClock` makes the runtime fully deterministic in tests (no `asyncio.sleep`)
- Adapter integration tests against Binance testnet require API keys; not in CI by default

## What's not yet here

- v0.2.1: full Binance user-data WebSocket implementation (currently the listenKey + WS session methods are documented `NotImplementedError` hooks)
- v0.3: adaptive execution + continual tuning + why-card population
- v0.4: IngestionActor + counterfactual shadow

See [vision.md](vision.md) for the full roadmap.
