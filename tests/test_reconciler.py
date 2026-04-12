"""Tests for kairos.execution.reconciler.Reconciler."""

from __future__ import annotations

import pytest

from kairos.cache import MarketCache
from kairos.execution.reconciler import Reconciler
from kairos.types import Order, OrderSide, OrderStatus, OrderType


pytestmark = pytest.mark.asyncio


class MockAdapter:
    """Adapter stub that returns a configurable open-orders list."""

    def __init__(
        self,
        open_orders: list[Order] | None = None,
        per_symbol: dict[str, list[Order]] | None = None,
        raise_on: str | None = None,
    ) -> None:
        self._open_orders = open_orders or []
        self._per_symbol = per_symbol or {}
        self._raise_on = raise_on

    async def get_open_orders(self, *, symbol: str | None = None) -> list[Order]:
        if self._raise_on is not None:
            if self._raise_on == "all" or self._raise_on == symbol:
                raise RuntimeError(f"simulated failure on get_open_orders({symbol})")
        if symbol is None:
            return list(self._open_orders)
        return list(self._per_symbol.get(symbol, []))

    async def cancel_order(self, *, symbol: str, order_id: str) -> bool:
        return True

    async def submit_order(self, **kwargs):  # not used in these tests
        raise NotImplementedError


def _order(
    oid: str,
    symbol: str = "BTCUSDC",
    status: OrderStatus = OrderStatus.ACCEPTED,
) -> Order:
    return Order(
        id=oid,
        symbol=symbol,
        side=OrderSide.BUY,
        type=OrderType.LIMIT,
        quantity=0.1,
        price=50_000,
        status=status,
    )


# ── Recovered orders (in venue, not in cache) ──────────────────


async def test_recovers_unknown_open_order_from_venue() -> None:
    cache = MarketCache()
    venue_order = _order("recovered-1")
    adapter = MockAdapter(open_orders=[venue_order])
    rec = Reconciler(adapter=adapter, cache=cache)

    report = await rec.reconcile()
    assert report.recovered_orders == 1
    assert report.cancels_recorded == 0
    assert cache.order("recovered-1") is venue_order


# ── Disappeared orders (in cache, not in venue) ────────────────


async def test_disappeared_order_marked_cancelled_when_truly_gone() -> None:
    cache = MarketCache()
    cache.ingest_order(_order("disappeared", status=OrderStatus.ACCEPTED))
    adapter = MockAdapter(
        open_orders=[],
        per_symbol={"BTCUSDC": []},  # truly absent
    )
    rec = Reconciler(adapter=adapter, cache=cache)

    report = await rec.reconcile()
    assert report.cancels_recorded == 1
    cached = cache.order("disappeared")
    assert cached is not None
    assert cached.status == OrderStatus.CANCELLED


async def test_disappeared_order_not_marked_when_race_with_refresh() -> None:
    """If the order pops back up in the per-symbol refetch, it was a race."""
    cache = MarketCache()
    cache.ingest_order(_order("flicker", status=OrderStatus.ACCEPTED))
    # Initial fetch shows it gone, but per-symbol refetch sees it (race)
    adapter = MockAdapter(
        open_orders=[],  # initial: gone
        per_symbol={"BTCUSDC": [_order("flicker")]},  # race: back
    )
    rec = Reconciler(adapter=adapter, cache=cache)

    report = await rec.reconcile()
    assert report.cancels_recorded == 0


# ── Errors ─────────────────────────────────────────────────────


async def test_reconcile_returns_error_when_fetch_fails() -> None:
    cache = MarketCache()
    adapter = MockAdapter(raise_on="all")
    rec = Reconciler(adapter=adapter, cache=cache)

    report = await rec.reconcile()
    assert report.recovered_orders == 0
    assert report.cancels_recorded == 0
    assert len(report.errors) == 1
    assert "fetch_open_orders" in report.errors[0]


async def test_per_symbol_fetch_failure_recorded() -> None:
    cache = MarketCache()
    cache.ingest_order(_order("o-fail", status=OrderStatus.ACCEPTED))
    adapter = MockAdapter(
        open_orders=[],
        raise_on="BTCUSDC",
    )
    rec = Reconciler(adapter=adapter, cache=cache)

    report = await rec.reconcile()
    # Recovered_orders = 0, but the disappeared check failed
    assert any("refetch_o-fail" in e for e in report.errors)


# ── Idempotency ────────────────────────────────────────────────


async def test_reconcile_is_idempotent() -> None:
    cache = MarketCache()
    venue_order = _order("stable")
    adapter = MockAdapter(open_orders=[venue_order])
    rec = Reconciler(adapter=adapter, cache=cache)

    r1 = await rec.reconcile()
    assert r1.recovered_orders == 1

    # Second call: order is already in cache, no-op
    r2 = await rec.reconcile()
    assert r2.recovered_orders == 0
    assert r2.cancels_recorded == 0


# ── Synthetic-fill emission ────────────────────────────────────


async def test_emit_synthetic_fill_invokes_callback() -> None:
    cache = MarketCache()
    fills_seen: list = []

    async def emit(fill) -> None:
        fills_seen.append(fill)

    adapter = MockAdapter()
    rec = Reconciler(adapter=adapter, cache=cache, emit_fill=emit)

    from kairos.types import Fill

    fill = Fill(
        order_id="o1",
        trade_id="t1",
        symbol="BTCUSDC",
        side=OrderSide.SELL,
        price=50_000,
        quantity=0.1,
        commission=0.0,
        timestamp=0,
    )
    await rec.emit_synthetic_fill(fill)
    assert fills_seen == [fill]


async def test_emit_synthetic_fill_without_callback_is_noop() -> None:
    cache = MarketCache()
    rec = Reconciler(adapter=MockAdapter(), cache=cache, emit_fill=None)

    from kairos.types import Fill

    fill = Fill(
        order_id="o1", trade_id="t1", symbol="BTCUSDC",
        side=OrderSide.SELL, price=50_000, quantity=0.1,
        commission=0.0, timestamp=0,
    )
    # Must not raise
    await rec.emit_synthetic_fill(fill)
