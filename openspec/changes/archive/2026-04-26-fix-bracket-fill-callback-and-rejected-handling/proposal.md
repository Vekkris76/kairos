## Why

Live diagnosis on a downstream consumer (`trading-autopilot`, 2026-04-26) found that 100 % of `buy_bracket` signals leave their brackets stuck in `pending_fill` state in the consumer's database, despite the underlying entry orders actually filling at the venue. Two distinct bugs in this engine cause it:

1. `BinanceLive.set_fill_callback` does not propagate the callback to its inner REST adapter (`BinanceAdapter`), so any market order that fills instantly at submit time silently drops the synthesized fill on the floor.
2. `BinanceAdapter.submit_order` swallows submission errors and returns a sentinel `Order(id="", status=REJECTED)` instead of raising. Callers (notably `BracketManager.submit_bracket_two_phase`) blindly persist the empty id as if the order succeeded.

Today only testnet is affected (no real capital at risk), but this is a hard blocker for any real-capital activation on Binance Spot through this engine.

## What Changes

- **BREAKING**: `BinanceAdapter.submit_order` now raises on submission failure instead of returning `Order(id="", status=REJECTED)`. Callers that previously inspected the sentinel `.status` value must catch the exception instead.
- `BinanceLive.set_fill_callback` and `BinanceLive.connect` propagate the registered fill callback to `self._rest._fill_callback` so instant-fill MARKET orders surface their fill via the same callback as WS user-data fills.
- Apply the same propagation pattern to `BybitLive` (same code shape, latent bug).
- `BracketManager.submit_bracket_two_phase` adds defence-in-depth: rejects an entry order whose `.status == REJECTED` even if the adapter neglects to raise (covers third-party adapters that haven't adopted the new contract).
- Bump `kairos-engine` to `0.3.4`. CHANGELOG entry covering the contract change. Publish via the trusted-publishing GitHub Actions workflow.

## Capabilities

### New Capabilities
- `bracket-fill-pipeline`: codifies the contract that **every** adapter must surface fill events through a single registered callback regardless of which submission path produced the fill (REST instant-fill, WS user-data, REST polling), and that **every** `submit_order` failure is observable to callers (raises, never returns silent sentinels). Greenfield spec — no prior baseline in `openspec/specs/`.

### Modified Capabilities
<!-- None — Kairos has no pre-existing specs. -->

## Impact

- **Code touched** (this repo):
  - `kairos/adapters/binance_live.py` — `set_fill_callback` + `connect` propagation logic.
  - `kairos/adapters/bybit_live.py` — same pattern applied for parity.
  - `kairos/exchanges/binance.py` — `BinanceAdapter.submit_order` raises on failure.
  - `kairos/execution/bracket_manager.py` — defence-in-depth status check in `submit_bracket_two_phase`.
  - Tests under `tests/` (new files for adapter callback propagation + REJECTED handling).
  - `pyproject.toml` version bump to `0.3.4`; `CHANGELOG.md` entry.
- **APIs affected**: `BinanceAdapter.submit_order` contract changes (raises vs. returns sentinel) — breaking for any direct consumer of the inner REST adapter. `BinanceLive` users see no surface change.
- **Downstream consumers**: `trading-autopilot` will bump `kairos-engine>=0.3.4` in its own openspec change (`recover-stuck-brackets-and-async-fill-wrapper`). Any other downstream consumer that constructs `BinanceAdapter` directly must adapt to the new exception contract.
- **Release**: PyPI publish of `kairos-engine==0.3.4` via the trusted-publishing workflow.
