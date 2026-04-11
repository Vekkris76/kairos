"""Paper trading adapter — simulated exchange for testing.

No real money. Fills instantly at market price.
Perfect for strategy development and testing.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from typing import Callable

from autopilot.exchanges.base import ExchangeAdapter
from autopilot.types import (
    Balance, Bar, Fill, Instrument, Order,
    OrderSide, OrderStatus, OrderType, TimeInForce,
)

logger = logging.getLogger("autopilot.paper")


class PaperAdapter(ExchangeAdapter):
    """Simulated exchange — instant fills, no fees by default."""

    def __init__(
        self,
        initial_balances: dict[str, float] | None = None,
        fee_rate: float = 0.001,  # 0.1% default
    ) -> None:
        self._balances: dict[str, Balance] = {}
        self._orders: dict[str, Order] = {}
        self._open_orders: list[Order] = []
        self._instruments: dict[str, Instrument] = {}
        self._bar_callbacks: dict[str, list[Callable]] = defaultdict(list)
        self._fill_callback: Callable | None = None
        self._order_callback: Callable | None = None
        self._fee_rate = fee_rate
        self._last_prices: dict[str, float] = {}

        # Set initial balances
        if initial_balances:
            for currency, amount in initial_balances.items():
                self._balances[currency] = Balance(
                    currency=currency, free=amount, locked=0.0,
                )

    async def connect(self) -> None:
        logger.info("Paper exchange connected")

    async def disconnect(self) -> None:
        logger.info("Paper exchange disconnected")

    # ── Market Data ───────────────────────────────────

    async def subscribe_bars(
        self, symbol: str, timeframe: str, callback: Callable[[Bar], None],
    ) -> None:
        key = f"{symbol}:{timeframe}"
        self._bar_callbacks[key].append(callback)
        logger.info(f"Paper: subscribed to {key}")

        # Create default instrument if not exists
        if symbol not in self._instruments:
            base = symbol.replace("USDC", "").replace("USDT", "")
            self._instruments[symbol] = Instrument(
                symbol=symbol, base=base, quote="USDC",
                min_qty=0.00001, max_qty=1000000,
                qty_step=0.00001, min_notional=5.0,
                price_precision=2, qty_precision=5,
            )

    async def get_historical_bars(
        self, symbol: str, timeframe: str,
        start_ms: int, end_ms: int,
    ) -> list[Bar]:
        return []  # Paper mode has no history

    def feed_bar(self, bar: Bar) -> None:
        """Feed a bar to all subscribers (used by backtest engine)."""
        self._last_prices[bar.symbol] = bar.close
        key = f"{bar.symbol}:{bar.timeframe}"
        for cb in self._bar_callbacks.get(key, []):
            cb(bar)
        # Check pending limit/stop orders
        self._check_pending_orders(bar)

    # ── Orders ────────────────────────────────────────

    async def submit_order(
        self,
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
        order_id = str(uuid.uuid4())[:8]
        order = Order(
            id=order_id, symbol=symbol, side=side, type=order_type,
            quantity=quantity, price=price, stop_price=stop_price,
            time_in_force=time_in_force, post_only=post_only,
            reduce_only=reduce_only,
        )
        self._orders[order_id] = order

        if order_type == OrderType.MARKET:
            # Fill immediately at last price
            fill_price = self._last_prices.get(symbol, price or 0)
            if fill_price > 0:
                self._execute_fill(order, fill_price)
            else:
                order.status = OrderStatus.REJECTED
        else:
            # Pending limit/stop order
            order.status = OrderStatus.ACCEPTED
            self._open_orders.append(order)

        return order

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        order = self._orders.get(order_id)
        if order and order.status == OrderStatus.ACCEPTED:
            order.status = OrderStatus.CANCELLED
            self._open_orders = [o for o in self._open_orders if o.id != order_id]
            return True
        return False

    async def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        if symbol:
            return [o for o in self._open_orders if o.symbol == symbol]
        return list(self._open_orders)

    # ── Account ───────────────────────────────────────

    async def get_balances(self) -> dict[str, Balance]:
        return dict(self._balances)

    async def get_instrument(self, symbol: str) -> Instrument:
        if symbol in self._instruments:
            return self._instruments[symbol]
        base = symbol.replace("USDC", "").replace("USDT", "")
        return Instrument(
            symbol=symbol, base=base, quote="USDC",
            min_qty=0.00001, max_qty=1000000,
            qty_step=0.00001, min_notional=5.0,
            price_precision=2, qty_precision=5,
        )

    # ── Internal ──────────────────────────────────────

    def _execute_fill(self, order: Order, fill_price: float) -> None:
        """Simulate an order fill."""
        commission = fill_price * order.quantity * self._fee_rate
        order.status = OrderStatus.FILLED

        fill = Fill(
            order_id=order.id,
            trade_id=str(uuid.uuid4())[:8],
            symbol=order.symbol,
            side=order.side,
            price=fill_price,
            quantity=order.quantity,
            commission=commission,
            timestamp=0,
        )

        # Update balances
        inst = self._instruments.get(order.symbol)
        quote = inst.quote if inst else "USDC"
        base = inst.base if inst else order.symbol.replace("USDC", "")

        if order.side == OrderSide.BUY:
            cost = fill_price * order.quantity + commission
            if quote in self._balances:
                self._balances[quote].free -= cost
            if base not in self._balances:
                self._balances[base] = Balance(currency=base, free=0, locked=0)
            self._balances[base].free += order.quantity
        else:
            revenue = fill_price * order.quantity - commission
            if base in self._balances:
                self._balances[base].free -= order.quantity
            if quote not in self._balances:
                self._balances[quote] = Balance(currency=quote, free=0, locked=0)
            self._balances[quote].free += revenue

        if self._fill_callback:
            self._fill_callback(fill)

        logger.info(
            f"Paper FILL: {order.side.value} {order.quantity} "
            f"{order.symbol} @ {fill_price:.2f} "
            f"(fee: {commission:.4f})",
        )

    def _check_pending_orders(self, bar: Bar) -> None:
        """Check if any pending orders should be triggered."""
        filled = []
        for order in self._open_orders:
            if order.symbol != bar.symbol:
                continue

            if order.type == OrderType.LIMIT:
                if order.side == OrderSide.BUY and bar.low <= (order.price or 0):
                    self._execute_fill(order, order.price or bar.low)
                    filled.append(order)
                elif order.side == OrderSide.SELL and bar.high >= (order.price or 0):
                    self._execute_fill(order, order.price or bar.high)
                    filled.append(order)

            elif order.type == OrderType.STOP_MARKET:
                if order.side == OrderSide.SELL and bar.low <= (order.stop_price or 0):
                    self._execute_fill(order, order.stop_price or bar.low)
                    filled.append(order)
                elif order.side == OrderSide.BUY and bar.high >= (order.stop_price or 0):
                    self._execute_fill(order, order.stop_price or bar.high)
                    filled.append(order)

        for o in filled:
            self._open_orders.remove(o)
