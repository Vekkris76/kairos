# Changelog

All notable changes documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) + semver.

## [0.3.7] — 2026-04-21 — *Instrument metadata ingested on connect*

### Changed

- `LiveEngine.run()` now ingests instrument metadata
  (`min_notional`, `qty_step`, `price_precision`, etc.) into
  `MarketCache` immediately after each adapter connects, before bar
  subscriptions start. Strategies can read per-symbol instrument
  specs via `self.cache.instrument(symbol)` without a separate async
  round-trip at `on_start`. Previously `MarketCache.ingest_instruments()`
  was never called at runtime — only in tests — so
  `self.cache.instrument(symbol)` always returned `None` for live
  strategies.

### Migration

Consumers that worked around the missing cache (e.g. a `MinNotionalMixin`
calling `adapter.get_instrument()` manually from `on_start`) can now
switch to `self.cache.instrument(symbol)`. The workaround remains
valid — this change is additive and non-breaking.

### Safety

Each `get_instrument` call is wrapped in `try/except`. A failure logs a
warning but never aborts the connect sequence; the cache stays empty
for that symbol, letting downstream strategies fall back to their
previous defaults.

## [0.3.6] — 2026-04-20 — *Guarded two-phase bracket helper*

### Added

- `LiveStrategy._submit_bracket_two_phase_guarded` — two-phase
  counterpart of `_submit_bracket_guarded`. Same `_lifecycle_gate`
  check (BUY-only, SELL bypasses, `force=True` bypasses,
  exception fails closed) but delegates to
  `bracket_manager.submit_bracket_two_phase(...)` so strategies
  can opt into partial-fill-aware SL/TP sizing without bypassing
  the F1 footgun guard.

### Why this ships as 0.3.6 (not part of 0.3.5)

0.3.5 added the `BracketManager.submit_bracket_two_phase` primitive
but no guarded wrapper. Downstream strategies either had to
replicate the gate check inline (easy to drift) or call
`bracket_manager.submit_bracket_two_phase` unguarded (the exact F1
vector the single-phase gate was introduced to close). Surfaced
during the DonchianTrend wiring effort in trading-autopilot — the
guarded helper keeps the host's `lifecycle_gate` contract intact
along the two-phase path.

## [0.3.5] — 2026-04-20 — *Two-phase bracket + partial-fill awareness*

### Added

- `BracketManager.submit_bracket_two_phase`: submits only the entry at
  call time; SL and TP are armed by `on_order_filled` when the entry
  fill arrives, sized to the actual `filled_qty` (not the requested
  quantity). Eliminates SL/TP over-sizing on partial fills. For MARKET
  entries on liquid pairs `submit_bracket` remains equivalent and
  simpler; use the two-phase variant for LIMIT entries or illiquid
  books where partial fills are a real risk.
- New `Bracket.state = "pending_fill"` lifecycle state, plus
  `Bracket.two_phase: bool` + internal `_sl_price_pending` /
  `_tp_price_pending` that buffer the exit prices until the fill
  arrives.

### Changed

- `BracketManager.on_order_filled` now accepts `Fill | str`. When a
  `Fill` is passed and the leg is the entry, `Bracket.filled_qty` +
  `Bracket.filled_price` are populated and `Bracket.quantity` is
  rewritten to the actual filled amount on partial fills (SL and TP
  for single-phase brackets remain at their original size — re-arming
  them would open a window of unprotected exposure). Legacy `str`
  path preserved for existing callers.

### Notes on wiring

`on_order_filled` awaits `_arm_exits` directly so failures propagate
via `BracketSubmissionError` and `bracket.state` is deterministic
when the hook returns. The live engine's `_route` currently calls
`actor.on_order_filled` without `await` — any strategy wiring the
two-phase bracket to a v3 actor must add an async bridge (e.g.
`asyncio.create_task` in the actor hook) until `_route` grows
coroutine-await support. That wiring lands in a separate
`trading-autopilot` PR, not here.

## [0.3.4] — 2026-04-18 — *Release-hygiene scaffolding*

### Added

- `scripts/release.sh` — local pre-ship gate that runs full pytest,
  build, and `twine check` before any `uv publish`. Fallback for
  manual releases; validates the same invariants as the new GHA
  workflow.
- `.github/workflows/release.yml` — GitHub Actions trusted
  publishing workflow. Triggered by `v*.*.*` tags. Runs the full
  pre-ship gate (tag/pyproject version match, CHANGELOG entry
  present, lint, pytest, build, twine check) and publishes via
  OIDC to PyPI. Zero on-disk tokens.
- `docs/release.md` — one-time PyPI + GitHub environment setup
  instructions + per-release flow + failure-mode recovery.

### Fixed

- `.github/workflows/ci.yml` — was linting `autopilot/` (path from
  the pre-v0.2.0 rename era, ~March 2026). Now correctly targets
  `kairos/` + `tests/`. Adopts `uv` via `astral-sh/setup-uv@v3` for
  parity with the release workflow.

### Note on v0.3.3 commit history

Commit `a2bae0f` originally tagged v0.3.3 only included the
CHANGELOG + pyproject.toml bump — the actual `reduce_only` kwarg
code change in `kairos/strategies/live.py` was left uncommitted at
tag time but WAS captured in the PyPI wheel (which builds from the
working tree). This was amended post-hoc to `dba8eaf` via
`git commit --amend` + `git tag -f v0.3.3` + force-push. The
0.3.3 wheel on PyPI is unaffected; git history now matches. The
release-hygiene scaffolding shipped in 0.3.4 was built specifically
to prevent this kind of working-tree / tag divergence going
forward (`scripts/release.sh` rejects a publish when the tag
doesn't point at HEAD).

## [0.3.3] — 2026-04-18 — *`reduce_only` kwarg on `_submit_guarded`*

### Fixed

- `LiveStrategy._submit_guarded` now accepts `reduce_only: bool = False`
  and forwards it to the adapter when set, matching what
  existing v3 strategies (DCA `_sell_all_async`, EMA
  `_close_position_async`) pass when closing positions. 0.3.2 shipped
  without the kwarg, which surfaced as
  `TypeError: _submit_guarded() got an unexpected keyword argument
  'reduce_only'` the first time a DCA SELL went through the guarded
  helper. No API change beyond adding the kwarg.

## [0.3.2] — 2026-04-18 — *Lifecycle submit gate*

### Added

- **`LiveStrategy._submit_guarded(...)`**: new helper that routes
  single-order submits through the adapter with an optional
  lifecycle-gate check. BUY-side submits consult
  `self._lifecycle_gate` (a zero-argument callable returning bool);
  SELL-side and `force=True` always pass. Fail-closed on exceptions.
- **`LiveStrategy._submit_bracket_guarded(...)`**: the bracket
  counterpart — same gate semantics, delegates to
  `bracket_manager.submit_bracket(...)` on allow.
- **`LiveEngine.add_strategy(lifecycle_gate=...)`**: new optional
  keyword argument. Binds the callable on the strategy instance
  (`strategy._lifecycle_gate`) so `_submit_guarded` and
  `_submit_bracket_guarded` can consult it. Default None — no
  behaviour change for existing callers.

### Changed

- `LiveStrategy.buy_bracket_pct` now routes its bracket entry
  through `_submit_bracket_guarded`, so strategies that used the
  canonical helper inherit the gate automatically.

### Rationale

Trading Autopilot's ASL (Autonomous Strategy Lifecycle) gates
multi-user signal fan-out at the dispatcher level, but the
`strategy → broker direct` path (via
`bracket_manager._adapter.submit_order`) bypassed every gate. A
SHADOW strategy could still place real orders on the host's
adapter account. The new helpers give the host a one-line block on
non-CHAMPION entries while keeping SELLs and cancels flowing (so a
retired strategy can still close its own positions). The callback
is zero-argument by design — the host closes over the per-strategy
identifier at registration time, keeping Kairos agnostic of what a
"lifecycle" even means.

### Backward compatibility

Purely additive. Every existing caller of `LiveStrategy`,
`LiveEngine.add_strategy`, and `BracketManager.submit_bracket` sees
identical behaviour. Opt in by passing `lifecycle_gate=` when you
call `add_strategy`; opt out by leaving it None.

See Trading Autopilot's
`openspec/changes/strategy-lifecycle-submit-gate/` for the host-side
integration and the 2026-04-18 incident retro that motivated it.

## [0.3.1] — 2026-04-14 — *Binance user-data WS via WS-API*

### Fixed

- **`BinanceLive._fetch_listen_key`**: migrated from the retired
  `POST /api/v3/userDataStream` REST endpoint (returns 410 Gone from
  Binance's nginx since early 2024) to the modern WebSocket API at
  `wss://ws-api.binance.com:443/ws-api/v3` using
  `userDataStream.start`. Works for both HMAC and Ed25519 keys;
  real-time fills + order updates flow again on mainnet.

### Changed

- `_keepalive_listen_key` and `_close_listen_key` likewise routed
  through WS-API (`userDataStream.ping` / `.stop`).
- New helper `_ws_api_call(method, params)` — short-lived WS, one
  request/response, common error handling for all three lifecycle
  ops.
- Added WS-API endpoint constants (prod + testnet variants).

### Notes

No API changes. Existing `BinanceLive(api_key=..., api_secret=...,
testnet=...)` callers are unaffected. Live-tested against mainnet
with operator Ed25519 keys → listenKey fetched, pinged, stopped
cleanly.

## [0.3.0] — 2026-04-13 — *Strategy signal emission*

Strategies can now publish their decisions to the engine's event bus as `StrategySignal` events, enabling downstream consumers (e.g. a multi-tenant signal dispatcher) to fan out per-user orders without each strategy needing to know about users.

### Added

- **`StrategySignal` dataclass** (`kairos.types`, exported from `kairos`): frozen, action-based decision record with fields `strategy`, `symbol`, `action`, `pct_of_capital`, `sl_atr_mult`, `tp_atr_mult`, `price_level`, `order_ref`, `reason`, `ts_ns`. Actions currently documented: `buy_bracket`, `sell_all`, `grid_entry`, `grid_cancel`.

- **`LiveStrategy.emit_signal(action, **kwargs)`**: fire-and-forget helper mirroring `Actor.publish_signal`. Builds a `StrategySignal` (strategy name derived from class name), publishes on `"strategy_signal"`. Safe to call before registration (no-op with debug log) — never raises.

- **`"strategy_signal"` registered in `KNOWN_KINDS`**: subscribers can listen without tripping `UnknownEventKindError`.

### Tests

**227 passing** (216 → 227): 11 new tests for `StrategySignal` construction, event-bus registration, `emit_signal` publishing mechanics (single + multi-subscriber), strategy-name derivation from class, symbol override, and pre-registration safety.

### Migration from 0.2.3

Fully additive. Existing strategies keep working unchanged. To adopt the new pattern:

```python
# Before (single-tenant submit_order only):
async def on_bar_ready(self, bar):
    if self.rsi() < 30:
        await self.buy_bracket_pct(15.0, atr_multiplier=2.0)

# After (dual-write: both submit directly AND broadcast for dispatchers):
async def on_bar_ready(self, bar):
    if self.rsi() < 30:
        self.emit_signal(
            "buy_bracket",
            pct_of_capital=0.15,
            sl_atr_mult=2.0,
            tp_atr_mult=2.0,
            reason="RSI oversold",
        )
        await self.buy_bracket_pct(15.0, atr_multiplier=2.0)
```

The direct submission continues to work for single-tenant setups; the signal unlocks multi-tenant dispatch.

## [0.2.3] — 2026-04-13 — *Binance Ed25519 key support*

Binance Spot accepts two API-key types: HMAC-SHA256 (alphanumeric secret) and Ed25519 (Base64-encoded PKCS#8 DER private key). CCXT's Binance client auto-detects Ed25519 **only when the secret is wrapped in PEM envelope** — raw Base64 DER is silently treated as HMAC and signed incorrectly, causing `-1022 Signature for this request is not valid` on every signed call.

### Fixed

- **`BinanceAdapter` now accepts both key types.** A new `_normalize_binance_secret` helper detects raw Base64 DER (prefix `MC4C` / `MFMC`) and wraps it in PEM before passing to CCXT. HMAC secrets pass through untouched. Plain PEM-wrapped Ed25519 secrets are preserved. Callers don't need to know which flavor they have — pass the secret as Binance gave it.
- Verified against a live Binance mainnet account: Ed25519 key fetched `/api/v3/account` successfully, including balance retrieval.

### Tests

**216 passing** (209 → 216): 7 new tests for `_normalize_binance_secret` covering HMAC pass-through, whitespace stripping, both Ed25519 prefix variants (`MC4C`/`MFMC`), PEM-already-wrapped idempotency, and an end-to-end synthetic-key round-trip that signs 64-byte Ed25519 signatures.

### Migration from 0.2.2

No breaking changes. Existing HMAC-key callers see identical behavior. Ed25519 callers that were manually PEM-wrapping their secrets before calling Kairos can stop doing that — the adapter handles it now.

## [0.2.2] — 2026-04-12 — *BinanceLive user-data WebSocket*

Closes the last stub in the v0.2 live adapter: **real-time fills from Binance via the user-data stream**. Before this release, `BinanceLive._fetch_listen_key` and `BinanceLive._user_ws_session` raised `NotImplementedError` and adapters fell back to reconciliation polling. Now the live adapter is wire-complete.

### Added

- **`BinanceLive._fetch_listen_key()`** — `POST /api/v3/userDataStream` with the `X-MBX-APIKEY` header (prod: `api.binance.com`, testnet: `testnet.binance.vision`).
- **`BinanceLive._user_ws_session()`** — connects `wss://.../ws/{listenKey}`, streams `executionReport` frames, parses each into a `Fill` (on `x=TRADE`) + `Order` status update. Ping interval 30s, timeout 10s.
- **`BinanceLive._keepalive_listen_key()`** — background task that `PUT`s the listenKey every 30 min per Binance's spec. Failures are logged but don't kill the adapter — the reconnect loop rebuilds the key on the next session.
- **`BinanceLive._close_listen_key()`** — polite `DELETE` on disconnect.
- **Testnet URL switch** — `_rest_base()` / `_ws_base()` return the right host based on the `testnet=` constructor flag. `BinanceAdapter` (CCXT) now also calls `set_sandbox_mode(True)` when `testnet=True`.
- **Binance → Kairos enum mappers** — `_map_binance_order_status` (NEW → ACCEPTED, FILLED → FILLED, etc.) and `_map_binance_order_type` (LIMIT_MAKER → LIMIT, STOP_LOSS → STOP_MARKET, etc.).

### Tests

**209 passing** (200 v0.2.1 + 9 new): executionReport → Fill; non-execution events ignored; NEW exec_type doesn't emit a fill; partial fills emit both Fill and Order update; SELL side routed correctly; prod/testnet URL switch; enum mappers.

### Migration from 0.2.1

No breaking changes. Existing callers see:
- `BinanceLive(testnet=True, ...)` now reaches real Binance testnet endpoints instead of swallowing the NotImplementedError.
- Fills flow through `set_fill_callback` as soon as the user-data WS connects — no more waiting on reconciliation polling.

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
