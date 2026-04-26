## 1. Tests first

- [x] 1.1 Add `tests/test_binance_fill_callback_propagation.py` (flat layout per Kairos convention) with cases: callback registered pre-`connect`, callback registered post-`connect`, callback re-registered, asserting `adapter._rest._fill_callback is cb` after each.
- [x] 1.2 Extend the same test file with an instant-fill scenario: stub `BinanceAdapter._exchange.create_order` to return `{"status": "closed", ...}` and assert the registered callback receives exactly one `Fill`.
- [x] 1.3 N/A — `BybitLive` does REST submission directly via `httpx.AsyncClient` (no inner adapter with a separate `_fill_callback` slot), so RC1's propagation bug shape doesn't apply. Replaced by 1.3a below.
- [ ] 1.3a Add `tests/test_bybit_submit_raises_on_retcode_nonzero.py` (or extend `tests/test_bybit_live.py`) locking in the existing-correct behaviour: `submit_order` raises `RuntimeError` when the Bybit response has `retCode != 0`. Defends against a future regression that could re-introduce the silent-sentinel pattern.
- [x] 1.4 Add `tests/test_binance_adapter_rejection.py` (flat layout): stub `_exchange.create_order` with `side_effect=ccxt.InsufficientFunds(...)` and assert `BinanceAdapter.submit_order` raises `OrderSubmissionError` with the original exception chained via `__cause__`.
- [x] 1.5 Extend `tests/test_bracket_manager.py` (flat layout) with two cases: (a) adapter raises `OrderSubmissionError` → `submit_bracket_two_phase` raises `BracketSubmissionError`; (b) non-conforming adapter returns `Order(id="", status=REJECTED)` → still raises `BracketSubmissionError` (defence-in-depth path).
- [x] 1.6 Ran the full test suite locally; confirmed 5 failures across the new tests with the expected error messages (red phase confirmed: 2 propagation, 1 connect-propagation, 2 bracket-manager).

## 2. Implementation

- [x] 2.1 Defined `OrderSubmissionError(Exception)` in `kairos/exchanges/exceptions.py` (new file). Importable directly via `kairos.exchanges.exceptions.OrderSubmissionError`. No package-level re-export needed for the test surface.
- [x] 2.2 Replaced the `except Exception → return Order(id="", status=REJECTED)` branch in `BinanceAdapter.submit_order` with `raise OrderSubmissionError(str(e)) from e`. `cancel_order` was unchanged (already returns `False` rather than a sentinel; not the same bug shape).
- [x] 2.3 `BinanceLive.set_fill_callback` now propagates to `self._rest._fill_callback` when `_rest` is non-None.
- [x] 2.4 `BinanceLive.connect` now propagates an already-registered `_on_fill` to the freshly-constructed `_rest` immediately after `BinanceAdapter(...)` is built and before `_rest.connect()` is awaited.
- [x] 2.5 N/A — `BybitLive` has no inner adapter slot to propagate to (REST goes through `httpx.AsyncClient` directly inside `BybitLive.submit_order`). The contract spec scenario "Bybit adapter honours the same contract" is satisfied vacuously. RC3 also doesn't apply: `BybitLive.submit_order` already raises on `retCode != 0` and on HTTP errors. No code change required; lock-in test in 1.3a.
- [x] 2.6 In `BracketManager.submit_bracket_two_phase`: added `if entry_order.status == OrderStatus.REJECTED:` guard that sets `bracket.state="failed"`, populates `failure_reason`, and raises `BracketSubmissionError`. Added `except OrderSubmissionError` that re-raises as `BracketSubmissionError` chained via `from exc`. Imported `OrderStatus` at module top, `OrderSubmissionError` lazily inside the method to avoid the cycle (exchanges → execution would otherwise be the only edge in that direction).
- [x] 2.7 Ran the full Kairos test suite: **280 passed, 0 failed**. The 13 warnings are pre-existing pytest-asyncio noise on sync test functions in unrelated files (will document in commit body per the operational discipline policy).

## 3. Release

- [x] 3.1 Bumped `version` in `pyproject.toml` from `0.4.1` to `0.4.2` (the proposal said 0.3.3→0.3.4 but the repo was already at 0.4.1; bumped to 0.4.2 instead). Also bumped `__version__` in `kairos/__init__.py` to keep the two in sync.
- [x] 3.2 Added a `## [0.4.2]` section to `CHANGELOG.md` covering: callback propagation fix (RC1), `OrderSubmissionError` contract change (RC3, **breaking**), `BracketManager` defence-in-depth, with the migration code snippet for direct `BinanceAdapter` consumers.
- [x] 3.3 PR #3 opened, CI green on Python 3.11/3.12/3.13, merged via merge-commit (consistent with the repo's history of merge-commits on PRs #1 and #2). Branch `fix/bracket-fill-callback-pipeline-0.4.2` deleted post-merge.
- [x] 3.4 Tag `v0.4.2` annotated + pushed. `release.yml` ran: `Pre-ship gate` ✓, `Publish to PyPI (trusted)` ✓ after manual environment approval. Run id 24950876510.
- [x] 3.5 Sanity check in fresh venv: `pip install kairos-engine==0.4.2` succeeds, `BinanceLive.set_fill_callback(cb)` post-`_rest`-stub propagates to `_rest._fill_callback`, `OrderSubmissionError` is importable from `kairos.exchanges.exceptions`, `kairos.__version__ == "0.4.2"`.
- [x] 3.6 trading-autopilot openspec `recover-stuck-brackets-and-async-fill-wrapper` is now unblocked. The change's task 0.1 prerequisite gate is satisfied — `pip index versions kairos-engine` shows `0.4.2`.

## 4. Archive

- [ ] 4.1 Run `openspec validate fix-bracket-fill-callback-and-rejected-handling` and confirm it passes.
- [ ] 4.2 After downstream verification (trading-autopilot bumps the dep and the prod brackets observe SL/TP arming via the new path), run `openspec archive fix-bracket-fill-callback-and-rejected-handling` to move the change into `openspec/changes/archive/` and merge spec deltas into `openspec/specs/bracket-fill-pipeline/`.
