"""Tests for kairos.execution.bracket_manager.BracketManager."""

from __future__ import annotations


import pytest

from kairos.execution.bracket_manager import (
    Bracket,
    BracketManager,
    BracketSubmissionError,
)
from kairos.types import Fill, Order, OrderSide, OrderStatus, OrderType, TimeInForce


pytestmark = pytest.mark.asyncio


class MockAdapter:
    """In-memory adapter for unit tests of BracketManager.

    Records every call. `fail_on` lets a test simulate adapter errors
    on specific submit roles (entry/sl/tp).
    """

    def __init__(self, fail_on: set[str] | None = None) -> None:
        self.submitted: list[dict] = []
        self.cancelled: list[str] = []
        self.fail_on: set[str] = fail_on or set()
        self._counter = 0

    async def submit_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: float | None = None,
        stop_price: float | None = None,
        time_in_force: TimeInForce = TimeInForce.GTC,
        post_only: bool = False,
        reduce_only: bool = False,
    ) -> Order:
        # Infer role from order_type for fail simulation
        if order_type == OrderType.MARKET:
            role = "entry" if not reduce_only else "abort_close"
        elif order_type == OrderType.STOP_MARKET:
            role = "sl"
        elif order_type == OrderType.LIMIT:
            role = "tp"
        else:
            role = "unknown"

        if role in self.fail_on:
            raise RuntimeError(f"simulated failure: {role}")

        self._counter += 1
        oid = f"mock-{role}-{self._counter}"
        self.submitted.append(
            {
                "id": oid,
                "symbol": symbol,
                "side": side,
                "type": order_type,
                "quantity": quantity,
                "price": price,
                "stop_price": stop_price,
                "reduce_only": reduce_only,
                "role": role,
            }
        )
        return Order(
            id=oid,
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            status=OrderStatus.ACCEPTED,
        )

    async def cancel_order(self, *, symbol: str, order_id: str) -> bool:
        self.cancelled.append(order_id)
        return True


# ── Happy path ─────────────────────────────────────────────────


async def test_submit_bracket_arms_all_three_legs() -> None:
    adapter = MockAdapter()
    bm = BracketManager(adapter=adapter)
    bracket = await bm.submit_bracket(
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        quantity=0.1,
        sl_price=49_000,
        tp_price=52_000,
        reference_price=50_000,
    )
    assert bracket.state == "armed"
    assert bracket.entry_order_id is not None
    assert bracket.sl_order_id is not None
    assert bracket.tp_order_id is not None
    assert len(adapter.submitted) == 3
    assert adapter.cancelled == []


async def test_submit_bracket_uses_opposite_side_for_exits() -> None:
    adapter = MockAdapter()
    bm = BracketManager(adapter=adapter)
    await bm.submit_bracket(
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        quantity=0.1,
        sl_price=49_000,
        tp_price=52_000,
        reference_price=50_000,
    )
    sl_order = next(o for o in adapter.submitted if o["role"] == "sl")
    tp_order = next(o for o in adapter.submitted if o["role"] == "tp")
    assert sl_order["side"] == OrderSide.SELL
    assert tp_order["side"] == OrderSide.SELL
    assert sl_order["reduce_only"] is True
    assert tp_order["reduce_only"] is True


# ── Atomicity ──────────────────────────────────────────────────


async def test_sl_failure_closes_entry_with_reverse_market() -> None:
    adapter = MockAdapter(fail_on={"sl"})
    bm = BracketManager(adapter=adapter)
    with pytest.raises(BracketSubmissionError, match="SL submission failed"):
        await bm.submit_bracket(
            symbol="BTCUSDC",
            side=OrderSide.BUY,
            quantity=0.1,
            sl_price=49_000,
            tp_price=52_000,
            reference_price=50_000,
        )
    # 2 submits: entry, then abort-close (reverse MARKET)
    assert len(adapter.submitted) == 2
    abort = adapter.submitted[1]
    assert abort["role"] == "abort_close"
    assert abort["side"] == OrderSide.SELL
    assert abort["reduce_only"] is True


async def test_tp_failure_cancels_sl_and_closes_entry() -> None:
    adapter = MockAdapter(fail_on={"tp"})
    bm = BracketManager(adapter=adapter)
    with pytest.raises(BracketSubmissionError, match="TP submission failed"):
        await bm.submit_bracket(
            symbol="BTCUSDC",
            side=OrderSide.BUY,
            quantity=0.1,
            sl_price=49_000,
            tp_price=52_000,
            reference_price=50_000,
        )
    # 3 submits: entry, sl, abort-close. sl was cancelled.
    assert len(adapter.submitted) == 3
    assert len(adapter.cancelled) == 1
    abort = adapter.submitted[2]
    assert abort["role"] == "abort_close"


async def test_entry_failure_propagates_with_no_close() -> None:
    adapter = MockAdapter(fail_on={"entry"})
    bm = BracketManager(adapter=adapter)
    with pytest.raises(RuntimeError, match="simulated failure: entry"):
        await bm.submit_bracket(
            symbol="BTCUSDC",
            side=OrderSide.BUY,
            quantity=0.1,
            sl_price=49_000,
            tp_price=52_000,
            reference_price=50_000,
        )
    # Nothing submitted (entry failed before reaching adapter), no cancels needed
    assert adapter.submitted == []
    assert adapter.cancelled == []


# ── OCO at fill time ──────────────────────────────────────────


async def test_tp_fill_cancels_sl() -> None:
    adapter = MockAdapter()
    bm = BracketManager(adapter=adapter)
    bracket = await bm.submit_bracket(
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        quantity=0.1,
        sl_price=49_000,
        tp_price=52_000,
        reference_price=50_000,
    )
    sl_id = bracket.sl_order_id
    tp_id = bracket.tp_order_id

    result = await bm.on_order_filled(tp_id)  # type: ignore[arg-type]
    assert result is bracket
    assert bracket.state == "completed"
    assert bracket.exit_type == "tp"
    assert sl_id in adapter.cancelled


async def test_sl_fill_cancels_tp() -> None:
    adapter = MockAdapter()
    bm = BracketManager(adapter=adapter)
    bracket = await bm.submit_bracket(
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        quantity=0.1,
        sl_price=49_000,
        tp_price=52_000,
        reference_price=50_000,
    )
    result = await bm.on_order_filled(bracket.sl_order_id)  # type: ignore[arg-type]
    assert result is bracket
    assert bracket.state == "completed"
    assert bracket.exit_type == "sl"
    assert bracket.tp_order_id in adapter.cancelled


async def test_entry_fill_does_not_complete_bracket() -> None:
    adapter = MockAdapter()
    bm = BracketManager(adapter=adapter)
    bracket = await bm.submit_bracket(
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        quantity=0.1,
        sl_price=49_000,
        tp_price=52_000,
        reference_price=50_000,
    )
    result = await bm.on_order_filled(bracket.entry_order_id)  # type: ignore[arg-type]
    assert result is None
    assert bracket.state == "armed"


async def test_unknown_order_id_returns_none() -> None:
    adapter = MockAdapter()
    bm = BracketManager(adapter=adapter)
    result = await bm.on_order_filled("not-a-bracket-order")
    assert result is None


# ── Partial fill ──────────────────────────────────────────────


async def test_partial_entry_fill_updates_bracket_quantity() -> None:
    """Entry partially filled: bracket.quantity updated to filled_qty."""
    adapter = MockAdapter()
    bm = BracketManager(adapter=adapter)
    bracket = await bm.submit_bracket(
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        quantity=0.1,
        sl_price=49_000,
        tp_price=52_000,
        reference_price=50_000,
    )
    assert bracket.quantity == 0.1

    # Simulate a partial fill: only 0.06 of 0.1 was filled
    partial_fill = Fill(
        order_id=bracket.entry_order_id,
        trade_id="trade-001",
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        price=50_050.0,
        quantity=0.06,           # ← partial
        commission=0.0001,
        timestamp=1_700_000_000_000,
    )
    result = await bm.on_order_filled(partial_fill)

    # Entry fill: bracket stays armed (not completed)
    assert result is None
    assert bracket.state == "armed"
    # Quantity updated to actual filled amount
    assert bracket.filled_qty == 0.06
    assert bracket.filled_price == 50_050.0
    assert bracket.quantity == 0.06   # bracket.quantity reflects reality


async def test_full_entry_fill_with_fill_object() -> None:
    """Full fill via Fill object: same behaviour as str path."""
    adapter = MockAdapter()
    bm = BracketManager(adapter=adapter)
    bracket = await bm.submit_bracket(
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        quantity=0.1,
        sl_price=49_000,
        tp_price=52_000,
        reference_price=50_000,
    )
    full_fill = Fill(
        order_id=bracket.entry_order_id,
        trade_id="trade-002",
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        price=50_000.0,
        quantity=0.1,            # ← full fill
        commission=0.0001,
        timestamp=1_700_000_001_000,
    )
    result = await bm.on_order_filled(full_fill)
    assert result is None
    assert bracket.state == "armed"
    assert bracket.filled_qty == 0.1
    assert bracket.quantity == 0.1   # unchanged


async def test_tp_fill_via_fill_object_completes_bracket() -> None:
    """OCO via Fill object: TP fill cancels SL and completes bracket."""
    adapter = MockAdapter()
    bm = BracketManager(adapter=adapter)
    bracket = await bm.submit_bracket(
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        quantity=0.1,
        sl_price=49_000,
        tp_price=52_000,
        reference_price=50_000,
    )
    tp_fill = Fill(
        order_id=bracket.tp_order_id,
        trade_id="trade-003",
        symbol="BTCUSDC",
        side=OrderSide.SELL,
        price=52_000.0,
        quantity=0.1,
        commission=0.0001,
        timestamp=1_700_000_002_000,
    )
    result = await bm.on_order_filled(tp_fill)
    assert result is bracket
    assert bracket.state == "completed"
    assert bracket.exit_type == "tp"
    assert bracket.sl_order_id in adapter.cancelled


async def test_backward_compat_str_order_id_still_works() -> None:
    """Legacy str path (used by existing tests) still works after refactor."""
    adapter = MockAdapter()
    bm = BracketManager(adapter=adapter)
    bracket = await bm.submit_bracket(
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        quantity=0.1,
        sl_price=49_000,
        tp_price=52_000,
        reference_price=50_000,
    )
    # Pass raw string — simulates old callers
    result = await bm.on_order_filled(bracket.tp_order_id)  # type: ignore[arg-type]
    assert result is bracket
    assert bracket.state == "completed"


# ── Two-phase ──────────────────────────────────────────────────


async def _simulate_entry_fill(
    bm: BracketManager,
    bracket: Bracket,
    *,
    filled_qty: float,
    price: float = 50_000.0,
) -> None:
    """Construct a Fill for the bracket's entry order and dispatch it.

    MockAdapter doesn't auto-fill or fire callbacks — tests drive the
    fill event manually, mirroring what the live engine's event bus
    would do in production.
    """
    assert bracket.entry_order_id is not None
    fill = Fill(
        order_id=bracket.entry_order_id,
        trade_id=f"trade-{bracket.bracket_id}",
        symbol=bracket.symbol,
        side=bracket.side,
        price=price,
        quantity=filled_qty,
        commission=0.0,
        timestamp=1_700_000_000_000,
    )
    await bm.on_order_filled(fill)


async def test_two_phase_entry_only_on_submit() -> None:
    """submit_bracket_two_phase submits only entry — SL+TP pending fill."""
    adapter = MockAdapter()
    bm = BracketManager(adapter=adapter)
    bracket = await bm.submit_bracket_two_phase(
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        quantity=0.1,
        sl_price=49_000,
        tp_price=52_000,
        reference_price=50_000,
    )
    assert bracket.state == "pending_fill"
    assert bracket.two_phase is True
    assert len(adapter.submitted) == 1           # only entry
    assert adapter.submitted[0]["role"] == "entry"
    assert bracket.sl_order_id is None
    assert bracket.tp_order_id is None


async def test_two_phase_full_fill_arms_sl_tp_with_correct_qty() -> None:
    """Full fill: SL+TP armed with filled_qty=0.1."""
    adapter = MockAdapter()
    bm = BracketManager(adapter=adapter)
    bracket = await bm.submit_bracket_two_phase(
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        quantity=0.1,
        sl_price=49_000,
        tp_price=52_000,
        reference_price=50_000,
    )

    await _simulate_entry_fill(bm, bracket, filled_qty=0.1)

    assert bracket.state == "armed"
    assert bracket.sl_order_id is not None
    assert bracket.tp_order_id is not None
    assert len(adapter.submitted) == 3           # entry + SL + TP
    sl = next(o for o in adapter.submitted if o["role"] == "sl")
    tp = next(o for o in adapter.submitted if o["role"] == "tp")
    assert sl["quantity"] == 0.1
    assert tp["quantity"] == 0.1


async def test_two_phase_partial_fill_arms_sl_tp_with_filled_qty() -> None:
    """Partial fill (0.06 of 0.1): SL+TP sized to 0.06, not 0.1."""
    adapter = MockAdapter()
    bm = BracketManager(adapter=adapter)
    bracket = await bm.submit_bracket_two_phase(
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        quantity=0.1,
        sl_price=49_000,
        tp_price=52_000,
        reference_price=50_000,
    )

    await _simulate_entry_fill(bm, bracket, filled_qty=0.06)

    assert bracket.state == "armed"
    assert bracket.quantity == 0.06              # rewritten to filled_qty
    assert bracket.filled_qty == 0.06
    sl = next(o for o in adapter.submitted if o["role"] == "sl")
    tp = next(o for o in adapter.submitted if o["role"] == "tp")
    assert sl["quantity"] == 0.06
    assert tp["quantity"] == 0.06


async def test_two_phase_sl_failure_after_fill_closes_entry() -> None:
    """SL submit fails post-fill: entry closed with reverse MARKET, error raised."""
    adapter = MockAdapter(fail_on={"sl"})
    bm = BracketManager(adapter=adapter)
    bracket = await bm.submit_bracket_two_phase(
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        quantity=0.1,
        sl_price=49_000,
        tp_price=52_000,
        reference_price=50_000,
    )

    with pytest.raises(BracketSubmissionError, match="two-phase SL failed"):
        await _simulate_entry_fill(bm, bracket, filled_qty=0.1)

    assert bracket.state == "failed"
    # 2 submits: entry + abort_close (reverse MARKET)
    assert len(adapter.submitted) == 2
    abort = adapter.submitted[1]
    assert abort["role"] == "abort_close"
    assert abort["reduce_only"] is True


async def test_two_phase_oco_after_arming_works_normally() -> None:
    """Once armed via two-phase, OCO (TP fill → SL cancel) works identically."""
    adapter = MockAdapter()
    bm = BracketManager(adapter=adapter)
    bracket = await bm.submit_bracket_two_phase(
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        quantity=0.1,
        sl_price=49_000,
        tp_price=52_000,
        reference_price=50_000,
    )
    await _simulate_entry_fill(bm, bracket, filled_qty=0.1)
    assert bracket.state == "armed"

    result = await bm.on_order_filled(bracket.tp_order_id)  # type: ignore[arg-type]
    assert result is bracket
    assert bracket.state == "completed"
    assert bracket.exit_type == "tp"
    assert bracket.sl_order_id in adapter.cancelled


# ── Manual cancel ─────────────────────────────────────────────


async def test_cancel_bracket_cancels_both_legs() -> None:
    adapter = MockAdapter()
    bm = BracketManager(adapter=adapter)
    bracket = await bm.submit_bracket(
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        quantity=0.1,
        sl_price=49_000,
        tp_price=52_000,
        reference_price=50_000,
    )
    cancelled = await bm.cancel_bracket(bracket.bracket_id)
    assert cancelled is True
    assert bracket.state == "completed"
    assert bracket.exit_type == "manual"
    assert len(adapter.cancelled) == 2


async def test_cancel_unknown_bracket_returns_false() -> None:
    bm = BracketManager(adapter=MockAdapter())
    assert await bm.cancel_bracket("does-not-exist") is False


# ── Introspection ─────────────────────────────────────────────


async def test_active_brackets_excludes_completed() -> None:
    adapter = MockAdapter()
    bm = BracketManager(adapter=adapter)
    b1 = await bm.submit_bracket(
        symbol="BTCUSDC", side=OrderSide.BUY, quantity=0.1,
        sl_price=49_000, tp_price=52_000, reference_price=50_000,
    )
    b2 = await bm.submit_bracket(
        symbol="ETHUSDC", side=OrderSide.BUY, quantity=1.0,
        sl_price=2900, tp_price=3200, reference_price=3000,
    )
    await bm.on_order_filled(b1.tp_order_id)  # complete b1
    active = bm.active_brackets()
    assert len(active) == 1
    assert active[0].bracket_id == b2.bracket_id


async def test_bracket_for_order_resolves_legs() -> None:
    adapter = MockAdapter()
    bm = BracketManager(adapter=adapter)
    bracket = await bm.submit_bracket(
        symbol="BTCUSDC", side=OrderSide.BUY, quantity=0.1,
        sl_price=49_000, tp_price=52_000, reference_price=50_000,
    )
    assert bm.bracket_for_order(bracket.entry_order_id) is bracket  # type: ignore[arg-type]
    assert bm.bracket_for_order(bracket.sl_order_id) is bracket  # type: ignore[arg-type]
    assert bm.bracket_for_order(bracket.tp_order_id) is bracket  # type: ignore[arg-type]
    assert bm.bracket_for_order("nope") is None


# ── RC3 defence-in-depth: BracketManager rejects bad entries ─────


class _RaisingAdapter:
    """Adapter that raises OrderSubmissionError on every submit_order
    (the conforming-adapter contract for submission failure)."""

    def __init__(self) -> None:
        self.cancelled: list[str] = []

    async def submit_order(self, **kw):
        from kairos.exchanges.exceptions import OrderSubmissionError
        raise OrderSubmissionError("simulated rejection from venue")

    async def cancel_order(self, *, symbol: str, order_id: str) -> bool:
        self.cancelled.append(order_id)
        return True


class _SentinelReturningAdapter:
    """Non-conforming adapter: returns Order(id="", status=REJECTED) on
    failure instead of raising. The bracket manager's defence-in-depth
    must catch this and refuse to persist the bracket."""

    def __init__(self) -> None:
        self.cancelled: list[str] = []

    async def submit_order(self, **kw):
        return Order(
            id="",
            symbol=kw["symbol"],
            side=kw["side"],
            type=kw["order_type"],
            quantity=kw["quantity"],
            status=OrderStatus.REJECTED,
        )

    async def cancel_order(self, *, symbol: str, order_id: str) -> bool:
        self.cancelled.append(order_id)
        return True


async def test_two_phase_raises_when_adapter_raises_order_submission_error() -> None:
    """Conforming-adapter path: OrderSubmissionError → BracketSubmissionError."""
    adapter = _RaisingAdapter()
    bm = BracketManager(adapter=adapter)
    with pytest.raises(BracketSubmissionError):
        await bm.submit_bracket_two_phase(
            symbol="BTCUSDC", side=OrderSide.BUY, quantity=0.1,
            sl_price=49_000, tp_price=52_000, reference_price=50_000,
        )


async def test_two_phase_raises_when_adapter_returns_rejected_sentinel() -> None:
    """Defence-in-depth: non-conforming adapter returning Order(status=REJECTED)
    must NOT result in a persisted bracket with empty entry_order_id."""
    adapter = _SentinelReturningAdapter()
    bm = BracketManager(adapter=adapter)
    with pytest.raises(BracketSubmissionError, match="REJECTED"):
        await bm.submit_bracket_two_phase(
            symbol="BTCUSDC", side=OrderSide.BUY, quantity=0.1,
            sl_price=49_000, tp_price=52_000, reference_price=50_000,
        )
