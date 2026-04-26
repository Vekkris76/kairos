# bracket-fill-pipeline Specification

## Purpose
TBD - created by archiving change fix-bracket-fill-callback-and-rejected-handling. Update Purpose after archive.
## Requirements
### Requirement: Single fill callback covers every fill source

A live exchange adapter (`BinanceLive`, `BybitLive`, and any future equivalent) SHALL surface every order-fill event through the single callback registered via `set_fill_callback(cb)`, regardless of which submission path produced the fill. The known submission paths are: REST instant-fill (a MARKET order that returns `status="closed"` from the venue at submit time), user-data WebSocket (asynchronous fill notification post-submit), and REST polling (fallback used by venues whose user-data WS is unavailable, e.g. Binance testnet).

#### Scenario: REST instant-fill triggers the registered callback

- **WHEN** a caller invokes `BinanceLive.set_fill_callback(cb)` and then submits a MARKET order via `BinanceLive.submit_order(...)` that the venue fills instantly (REST returns `status="closed"`)
- **THEN** `cb(fill)` is invoked exactly once with a `Fill` matching the venue's reported price/quantity, and `cb` is the same callable the caller registered (no other callable is invoked in its place).

#### Scenario: User-data WebSocket fill triggers the registered callback

- **WHEN** a caller has registered a fill callback on `BinanceLive` and the user-data WebSocket emits an `executionReport` with `x="TRADE"` for a previously submitted order
- **THEN** the registered callback is invoked exactly once per execution, with a `Fill` whose `order_id` matches the order id returned by the original `submit_order` call.

#### Scenario: Callback registered before connect still applies after connect

- **WHEN** a caller invokes `BinanceLive.set_fill_callback(cb)` BEFORE calling `BinanceLive.connect()`, and then `connect()` constructs the inner REST client
- **THEN** any subsequent fill — REST instant or WS — invokes `cb`. The inner REST client SHALL hold a reference to `cb` after `connect()` completes (no separate registration call required).

#### Scenario: Callback set after connect propagates to inner clients

- **WHEN** a caller invokes `BinanceLive.connect()` and then `BinanceLive.set_fill_callback(cb)`
- **THEN** the inner REST client's fill-emission path uses `cb` from the next submission onward. No prior registration is required to "prime" the inner slot.

#### Scenario: Callback re-registration replaces all references

- **WHEN** a caller invokes `set_fill_callback(cb_a)`, then later `set_fill_callback(cb_b)`
- **THEN** subsequent fills invoke `cb_b` exclusively. `cb_a` is no longer referenced by any internal slot of the adapter or its inner clients (no double-emission, no stale invocation).

#### Scenario: Bybit adapter honours the same contract

- **WHEN** the same registration + submission sequence is exercised against `BybitLive`
- **THEN** the same propagation guarantees hold. The contract is adapter-agnostic.

### Requirement: Submission failures raise instead of returning sentinels

A REST submission wrapper (`BinanceAdapter.submit_order`, and equivalents on other venue adapters) SHALL raise `OrderSubmissionError` (or a subclass) when the underlying venue or HTTP client reports an error. It SHALL NOT return an `Order` object with an empty id, REJECTED status, or other sentinel value to indicate failure. Callers SHALL be able to distinguish "submitted, accepted by venue" from "rejected" via Python's exception flow alone, without inspecting fields on the returned `Order`.

#### Scenario: ccxt raises during create_order → adapter raises OrderSubmissionError

- **WHEN** the underlying ccxt `create_order` call raises any subclass of `ccxt.BaseError` (e.g. `InsufficientFunds`, `InvalidOrder`, `ExchangeError`, `RateLimitExceeded`)
- **THEN** `BinanceAdapter.submit_order` raises `OrderSubmissionError` with the original exception chained via `from exc`. The original venue/ccxt error message is preserved on `OrderSubmissionError.args[0]` so callers can log it.

#### Scenario: Successful submission returns an Order with a non-empty id

- **WHEN** ccxt `create_order` returns successfully with a non-empty id
- **THEN** `submit_order` returns an `Order` whose `.id` equals the venue's order id, `.status` is `SUBMITTED`/`ACCEPTED`/`FILLED` (never `REJECTED`), and the caller can use `.id` to track the order. The adapter SHALL NOT raise on the success path.

#### Scenario: Submission failure does not leave callback state dirty

- **WHEN** `submit_order` raises `OrderSubmissionError`
- **THEN** the adapter has not invoked any registered fill callback for the failed submission. No partial `Fill` is synthesized, no in-memory order map is mutated. The caller's exception handler sees a clean state.

### Requirement: BracketManager rejects entries whose status is REJECTED

The bracket manager (`kairos.execution.bracket_manager.BracketManager`) SHALL treat any returned entry order with `status == OrderStatus.REJECTED` as a submission failure equivalent to an exception, and SHALL NOT persist or expose a bracket whose `entry_order_id` came from such an order. This requirement provides defence in depth: the adapter contract above forbids returning a REJECTED sentinel, but the bracket manager protects downstream consumers even from non-conforming third-party adapters.

#### Scenario: Adapter returns REJECTED Order → submit_bracket_two_phase raises

- **WHEN** the adapter passed to `BracketManager` returns `Order(id="" , status=OrderStatus.REJECTED)` from `submit_order` instead of raising (a non-conforming adapter)
- **THEN** `submit_bracket_two_phase` raises `BracketSubmissionError` immediately, the bracket's in-memory state is `failed` with a populated `failure_reason`, and the caller can rely on the absence of a partially-initialised bracket.

#### Scenario: Adapter raises OrderSubmissionError → submit_bracket_two_phase re-raises as BracketSubmissionError

- **WHEN** the adapter raises `OrderSubmissionError` from `submit_order` (the conforming path)
- **THEN** `submit_bracket_two_phase` catches it, sets the bracket's state to `failed` with `failure_reason` capturing the underlying exception message, and re-raises as `BracketSubmissionError` so the caller has a single exception type to handle.

