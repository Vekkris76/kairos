"""Tests for kairos.execution.bracket_manager.BracketManager."""

from __future__ import annotations

import uuid

import pytest

from kairos.execution.bracket_manager import (
    BracketManager,
    BracketSubmissionError,
)
from kairos.types import Order, OrderSide, OrderStatus, OrderType, TimeInForce


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
