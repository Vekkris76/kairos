"""Order Manager — handles order lifecycle and bracket orders."""

from __future__ import annotations

import logging
from typing import Callable

from autopilot.types import Fill, Order, OrderSide, OrderStatus

logger = logging.getLogger("autopilot.orders")


class OrderManager:
    """Manages order state, bracket linkage, and fill routing."""

    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}
        self._brackets: dict[str, list[str]] = {}  # entry_id → [sl_id, tp_id]
        self._fill_handlers: list[Callable[[Fill], None]] = []

    def register_order(self, order: Order) -> None:
        self._orders[order.id] = order

    def register_bracket(
        self, entry_id: str, sl_id: str, tp_id: str,
    ) -> None:
        """Link bracket orders: when one fills, cancel the other."""
        self._brackets[entry_id] = [sl_id, tp_id]
        # Link SL and TP to each other
        self._brackets[sl_id] = [tp_id]
        self._brackets[tp_id] = [sl_id]

    def on_fill(self, handler: Callable[[Fill], None]) -> None:
        self._fill_handlers.append(handler)

    def process_fill(self, fill: Fill) -> list[str]:
        """Process a fill — returns list of order_ids to cancel (bracket)."""
        order = self._orders.get(fill.order_id)
        if order:
            order.status = OrderStatus.FILLED

        # Notify handlers
        for handler in self._fill_handlers:
            handler(fill)

        # Cancel linked bracket orders
        to_cancel = []
        linked = self._brackets.pop(fill.order_id, [])
        for linked_id in linked:
            if linked_id in self._orders:
                self._orders[linked_id].status = OrderStatus.CANCELLED
                to_cancel.append(linked_id)
                self._brackets.pop(linked_id, None)

        return to_cancel

    def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        orders = [
            o for o in self._orders.values()
            if o.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.ACCEPTED)
        ]
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        return orders
