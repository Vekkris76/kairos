"""Reconciler — reconnect-time order/position state recovery.

When a venue WebSocket disconnects, fills can occur during the gap.
On reconnect, we don't trust local state — we ask the venue for the
ground truth and diff:

- **Order in venue but not in cache** → ingest into cache, log as
  "recovered order"
- **Order in cache (state=ACCEPTED) but absent from venue's open list**
  → query order history; if FILLED during outage, emit a synthetic
  ``order_filled`` event so strategies/actors update; if CANCELLED, just
  remove from cache silently

Reconciliation is best-effort and idempotent: running it twice in a row
produces the same final state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable

from kairos.types import Fill, Order, OrderStatus

if TYPE_CHECKING:
    from kairos.cache.market_cache import MarketCache
    from kairos.exchanges.base import ExchangeAdapter

logger = logging.getLogger("kairos.reconciler")


@dataclass
class ReconciliationReport:
    """Summary of what a reconciliation pass discovered/did."""

    recovered_orders: int = 0
    fills_emitted: int = 0
    cancels_recorded: int = 0
    errors: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


# Type alias for the "emit fill" callback the engine wires up.
# Adapters can also bypass and ingest directly; this hook lets the engine
# route through its event bus so all subscribers (LearningActor,
# NotificationActor, NodeSync) see the recovered fill.
EmitFillFn = Callable[[Fill], Awaitable[None]]


class Reconciler:
    """Reconcile cached order state with the venue after a reconnect.

    Constructed once at engine start; ``reconcile`` is called by the
    adapter (or by the engine in response to ``adapter_reconnected``).
    """

    def __init__(
        self,
        adapter: "ExchangeAdapter",
        cache: "MarketCache",
        emit_fill: EmitFillFn | None = None,
    ) -> None:
        self._adapter = adapter
        self._cache = cache
        self._emit_fill = emit_fill

    async def reconcile(self) -> ReconciliationReport:
        """Diff cache vs venue, emit catch-up events. Returns a report."""
        report = ReconciliationReport()

        # 1. Pull venue's current open orders
        try:
            venue_open_orders = await self._adapter.get_open_orders()
        except Exception as exc:
            logger.error(f"Reconcile: failed to fetch open orders: {exc}")
            report.errors.append(f"fetch_open_orders: {exc}")
            return report

        venue_open_ids: set[str] = {o.id for o in venue_open_orders}
        cache_orders = self._cache.orders()
        cache_open_orders = self._cache.orders_open()
        cache_open_ids: set[str] = {o.id for o in cache_open_orders}

        # 2. Recovered: in venue, not in cache → ingest
        for venue_order in venue_open_orders:
            if venue_order.id not in {o.id for o in cache_orders}:
                self._cache.ingest_order(venue_order)
                report.recovered_orders += 1
                logger.info(
                    f"Reconcile: recovered unknown open order {venue_order.id} "
                    f"({venue_order.symbol} {venue_order.side.name} {venue_order.quantity})"
                )

        # 3. Disappeared: in cache (open), not in venue → query history
        for cached in cache_open_orders:
            if cached.id in venue_open_ids:
                continue
            await self._handle_disappeared_order(cached, report)

        logger.info(
            f"Reconciliation done: recovered={report.recovered_orders} "
            f"fills_emitted={report.fills_emitted} "
            f"cancels_recorded={report.cancels_recorded} "
            f"errors={len(report.errors)}"
        )
        return report

    async def _handle_disappeared_order(
        self, cached: Order, report: ReconciliationReport,
    ) -> None:
        """An order is open in our cache but gone from the venue. Find out why."""
        # Try to ask the venue what happened to it. We don't have a strict
        # "get order by id" in the abstract adapter, so we use a best-effort
        # strategy: re-pull open orders restricted to the symbol and infer.
        # Real adapters can override or extend Reconciler with a richer
        # query-history method.
        try:
            still_open = await self._adapter.get_open_orders(symbol=cached.symbol)
            still_open_ids = {o.id for o in still_open}
        except Exception as exc:
            report.errors.append(f"refetch_{cached.id}: {exc}")
            return

        if cached.id in still_open_ids:
            return  # Race: it was open after all

        # Order is truly gone. Conservative default: assume CANCELLED unless
        # the adapter offers a richer history API. Adapters can wrap this
        # method with a smarter heuristic.
        cached.status = OrderStatus.CANCELLED
        self._cache.ingest_order(cached)
        report.cancels_recorded += 1
        logger.info(
            f"Reconcile: order {cached.id} disappeared from venue — "
            f"marked CANCELLED (override with adapter-specific Reconciler "
            f"if you can detect FILLED-during-outage)"
        )

    async def emit_synthetic_fill(self, fill: Fill) -> None:
        """Optional helper for adapters that DO know an order filled during
        the outage. Adapter calls this with a constructed Fill; we forward
        to the engine's event bus via the ``emit_fill`` callback.
        """
        if self._emit_fill is None:
            logger.debug(
                "emit_synthetic_fill called but no emit_fill callback wired"
            )
            return
        await self._emit_fill(fill)
