## Context

Kairos exposes two layered Binance Spot adapters:

- `kairos.adapters.binance_live.BinanceLive` — the public-facing live adapter. Owns the user-data WebSocket task, exposes `set_fill_callback`, and is the object that engines (and `BracketManager` via `engine.register_adapter`) interact with.
- `kairos.exchanges.binance.BinanceAdapter` — an internal REST wrapper around `ccxt.binance`. Constructed lazily by `BinanceLive.connect()` and stored at `self._rest`. It also exposes a `_fill_callback` attribute and invokes it from `submit_order` whenever ccxt returns `result["status"] == "closed"` (instant-fill MARKET orders, the steady-state case for liquid spot pairs).

Two distinct attribute slots, no propagation between them:

```text
caller ──set_fill_callback──▶ BinanceLive._on_fill   (used only by WS path)
                              BinanceAdapter._fill_callback  ← always None
```

Result for a MARKET BUY that fills instantly:

```
BinanceLive.submit_order
  └─ BinanceAdapter.submit_order
       └─ ccxt create_order → status="closed"
       └─ if self._fill_callback:   ← None, branch never taken
       └─ returns Order(status=FILLED)
caller (BracketManager.submit_bracket_two_phase)
  └─ writes bracket.entry_order_id = order.id
  └─ writes bracket.state = "pending_fill"
  └─ ⏳ waits forever for an on_order_filled call that never arrives
```

`_arm_exits` is gated on the entry-fill callback, so SL and TP orders are never placed at the venue. The position sits exposed.

The second bug shares the same blind spot from the other direction. `BinanceAdapter.submit_order` wraps the ccxt call in a broad `except Exception` (`kairos/exchanges/binance.py:273-278`) and returns `Order(id="", status=REJECTED)` instead of raising. `BracketManager.submit_bracket_two_phase` (`kairos/execution/bracket_manager.py:284-308`) does not inspect `.status` — it stores the empty id, persists `pending_fill`, and the bracket can never reconcile because no order exists at the venue. Confirmed in prod: 25 brackets for `sim-basic-500` (capital insufficient at testnet) all carry `entry_order_id = ""`.

Both bugs hide failures behind successful-looking objects. This change makes the success/failure path explicit on both axes (callback wiring + exception propagation) so the bracket pipeline cannot silently desync from venue state.

## Goals / Non-Goals

**Goals:**

- Single `set_fill_callback` registration on `BinanceLive` (or `BybitLive`) results in **every** fill — instant REST, WS user-data, REST polling — invoking exactly one callback. No silent drops.
- `submit_order` failures are observable to callers as exceptions. Sentinel `Order(id="", status=REJECTED)` is removed from the public API of `BinanceAdapter`.
- `BracketManager.submit_bracket_two_phase` refuses to persist a bracket whose entry order is REJECTED, even if a third-party adapter forgets to raise (defence in depth).
- Test coverage that locks in the callback-propagation contract and the raise-on-REJECTED contract — so regressions break CI, not production.
- Ship as `kairos-engine 0.3.4` via the trusted-publishing GHA workflow.

**Non-Goals:**

- Restructuring the two-class layering (`BinanceLive` wrapping `BinanceAdapter`). A future cleanup may collapse them, but that touches every test fixture and is not justified for a fix release.
- Any change to consumer behaviour for already-stuck brackets. Cleanup of the 124 historical `pending_fill` rows in the prod database lives in the trading-autopilot openspec change, not here.
- Adding a fourth fill-source path. The contract documents three (REST instant, WS, REST polling); we are not introducing a new one.
- Sync-vs-async signature changes to the callback. The mismatch between `BinanceLive._process_user_ws_message`'s `await self._on_fill(fill)` and the consumer's sync wrapper is fixed on the consumer side. Kairos's `await` of the registered callback is correct given the async-first contract; the consumer adapts.

## Decisions

### Decision 1 — Propagate the callback from `BinanceLive` to `BinanceAdapter` rather than refactoring the inner callback away

**Choice**: `BinanceLive.set_fill_callback(cb)` will (a) store `self._on_fill = cb`, AND (b) if `self._rest is not None`, also assign `self._rest._fill_callback = cb`. Mirror inside `connect()` so a callback registered before `connect()` (the documented order in the class docstring) gets pushed down to `_rest` once `_rest` is constructed. Mirror again on any future reconnect path that recreates `_rest`.

**Alternatives considered**:

- *(B) Remove `_fill_callback` from `BinanceAdapter` entirely; have its `submit_order` return the `Fill` to the caller and have `BinanceLive.submit_order` invoke `self._on_fill(fill)`*. Cleaner long-term — eliminates the duplicate slot and the propagation hazard. Rejected for this fix because it touches every direct consumer of `BinanceAdapter` (used by some test fixtures and the testnet poller's `_handle_terminal` path which reaches `_rest._exchange.fetch_order`). Out of scope for a 0.3.x patch; track as a follow-up cleanup for 0.4.0.
- *(C) Make `BinanceLive` not own a `BinanceAdapter` for execution at all; rewire `submit_order` to use ccxt directly*. Even bigger blast radius than (B); same reason to reject for now.

**Why (A)**: minimal diff (~10 lines + tests), preserves all existing call sites, and the propagation invariant is enforceable by a single test.

### Decision 2 — Raise on REJECTED in `BinanceAdapter.submit_order`, NOT just log

**Choice**: replace the `return Order(id="", status=REJECTED)` branch in `kairos/exchanges/binance.py:273-278` with `raise OrderSubmissionError(...) from exc`. Define a new exception class `OrderSubmissionError(Exception)` in `kairos/exchanges/exceptions.py` (or wherever the closest existing exception lives — there is already `BracketSubmissionError` in `kairos/execution/bracket_manager.py`; reuse pattern).

**Alternatives considered**:

- *Keep returning the sentinel, but add a deprecation warning*. Rejected — it preserves the failure mode for any caller that wasn't explicitly migrated, including `BracketManager`. Same outcome as today for them.
- *Return `None` instead of a sentinel*. Rejected — `None` is even harder to attribute (callers crash later with AttributeError instead of a typed exception with the rejection reason).

**Why raise**: ccxt already raises typed exceptions (`ExchangeError`, `InsufficientFunds`, `InvalidOrder`, etc.); the wrapper should preserve that signal, not erase it. Callers that genuinely want a "best-effort, don't care about failure" path can wrap their own `try/except` — they are the minority and should be explicit.

### Decision 3 — Defence-in-depth: `BracketManager` checks `entry_order.status` even after the adapter contract change

**Choice**: in `kairos/execution/bracket_manager.py::submit_bracket_two_phase`, immediately after `entry_order = await self._adapter.submit_order(...)` (line 285-294), check `if entry_order.status == OrderStatus.REJECTED: raise BracketSubmissionError(f"Bracket {bid}: entry rejected by adapter")`. The check is unreachable if every adapter honours Decision 2, but it locks the bracket pipeline against a third-party adapter that doesn't.

**Alternative considered**: trust the adapter contract; no check. Rejected — `BracketManager` is the consolidation point that downstream consumers like `trading-autopilot` rely on for safety-critical state. The cost of the check is one comparison; the cost of a regression here is silent capital exposure.

### Decision 4 — Apply the propagation pattern to `BybitLive` in the same release

**Choice**: `kairos/adapters/bybit_live.py:259` has the identical `set_fill_callback(self, callback)` shape. Apply the same propagation logic. No prod consumer of Bybit yet, but the bug is latent and shipping the asymmetric fix would virtually guarantee re-discovering it later.

**Alternative considered**: defer Bybit until first real consumer activates. Rejected — fixing both costs five extra lines and one extra test; the symmetry makes the contract self-documenting.

### Decision 5 — Tests live under `tests/`, mirroring existing layout

**Choice**: new file `tests/adapters/test_fill_callback_propagation.py` covering Decisions 1 + 4. New file `tests/exchanges/test_binance_adapter_rejection.py` covering Decision 2. Extend existing `tests/execution/test_bracket_manager.py` with a defence-in-depth case for Decision 3.

Use a tiny in-memory ccxt stub for the rejection test (no network). For propagation, the test inspects `adapter._rest._fill_callback is cb` after `set_fill_callback`; no need to actually trade.

## Risks / Trade-offs

- **[Breaking change for direct `BinanceAdapter` consumers]** → Mitigation: documented in CHANGELOG with a one-liner showing the migration (catch `OrderSubmissionError` in addition to ccxt exceptions). Direct consumption of the inner adapter is rare; `BinanceLive` is the documented entry point.
- **[Propagation logic could be skipped on a code path we missed]** (e.g., if a future reconnect recreates `_rest` without re-running `set_fill_callback`) → Mitigation: the test asserts the invariant after `connect()`, after `set_fill_callback()` called pre-connect, and after `set_fill_callback()` called post-connect. A future reconnect path would have to extend the test — and would be visible in code review because it touches `_rest = ...`.
- **[Test fixture creep]** — adding ccxt stubs for the rejection test risks coupling tests to ccxt internals → Mitigation: stub at the smallest possible surface (`exchange.create_order = AsyncMock(side_effect=...)`) and keep it inline in the test file; do not add to a shared conftest.
- **[Downstream timing]** — trading-autopilot needs `kairos-engine>=0.3.4` to pick this up; until they bump, prod stays buggy. No mitigation in this repo; tracked in the consumer's openspec.

## Migration Plan

1. Implement and test (tasks 1.x + 2.x).
2. Bump `pyproject.toml` to `0.3.4`. Update `CHANGELOG.md` with a "Breaking changes" section noting Decision 2.
3. Open PR; CI runs the new tests against the contract.
4. On merge to `main`, the trusted-publishing workflow at `.github/workflows/release.yml` builds + publishes to PyPI on tag `v0.3.4`. Tag manually after merge.
5. Verify install: `pip install kairos-engine==0.3.4` in a clean venv; spot-check that `BinanceLive(...).set_fill_callback(cb)` then `await adapter.connect()` → `adapter._rest._fill_callback is cb`.
6. Notify trading-autopilot to bump the dep and merge its companion change.

**Rollback**: PyPI does not support deletion. If 0.3.4 is bad, ship 0.3.5 with a revert. trading-autopilot would then re-pin to `kairos-engine<0.3.4,>=0.3.3` until 0.3.5 lands.

## Open Questions

- Should the new `OrderSubmissionError` carry a structured `reason` field (e.g., `insufficient_funds`, `min_notional`, `rate_limit`) parsed from the ccxt exception, or just the original message? Tentative answer: just the original message in 0.3.4; structured reasons are a 0.4.0 follow-up if downstream needs them. Resolve before tasks.md is finalised if the answer changes the test surface.
