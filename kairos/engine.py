"""Autopilot Engine — multi-strategy trading engine.

Connects all components: exchange, data, orders, risk, strategies.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any

from kairos.data.cache import BarCache
from kairos.events import EventBus
from kairos.orders.manager import OrderManager
from kairos.orders.position import PositionTracker
from kairos.risk.validator import RiskValidator
from kairos.strategy import Strategy
from kairos.types import Bar, Fill, OrderSide, OrderType

logger = logging.getLogger("autopilot.engine")


class Engine:
    """Multi-strategy trading engine.

    Usage:
        engine = Engine(exchange="binance", api_key="...", api_secret="...")
        engine.add(MyStrategy, symbol="BTCUSDC", timeframe="1h")
        engine.run()
    """

    def __init__(
        self,
        exchange: str = "paper",
        api_key: str = "",
        api_secret: str = "",
        base_currency: str = "USDC",
        initial_balance: float = 1000.0,
        **kwargs: Any,
    ) -> None:
        self._exchange_name = exchange
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_currency = base_currency
        self._initial_balance = initial_balance

        self._strategies: list[dict] = []
        self._events = EventBus()
        self._cache = BarCache()
        self._order_manager = OrderManager()
        self._positions = PositionTracker()
        self._risk = RiskValidator(**kwargs)
        self._adapter = None
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None

    def add(
        self,
        strategy_cls: type[Strategy],
        symbol: str,
        timeframe: str = "1h",
    ) -> None:
        """Register a strategy on a symbol/timeframe."""
        self._strategies.append({
            "cls": strategy_cls,
            "symbol": symbol,
            "timeframe": timeframe,
            "instance": None,
        })

    def run(self) -> None:
        """Start the engine (blocking)."""
        logger.info(
            f"Autopilot Engine v0.1 — "
            f"{len(self._strategies)} strategies, "
            f"exchange={self._exchange_name}",
        )

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        for sig in (signal.SIGINT, signal.SIGTERM):
            self._loop.add_signal_handler(sig, self._stop)

        try:
            self._loop.run_until_complete(self._run_async())
        except KeyboardInterrupt:
            pass
        finally:
            self._loop.run_until_complete(self._shutdown())
            self._loop.close()

    async def _run_async(self) -> None:
        # 1. Create adapter
        self._adapter = self._create_adapter()
        await self._adapter.connect()
        self._adapter.on_fill(self._on_fill)

        # 2. Init strategies
        for entry in self._strategies:
            inst = entry["cls"]()
            inst._bind(self, entry["symbol"], entry["timeframe"])
            inst.setup()
            entry["instance"] = inst

        # 3. Subscribe bars
        subs = set()
        for entry in self._strategies:
            key = f"{entry['symbol']}:{entry['timeframe']}"
            if key not in subs:
                await self._adapter.subscribe_bars(
                    entry["symbol"], entry["timeframe"], self._on_bar,
                )
                subs.add(key)

        self._running = True
        logger.info("Engine RUNNING")

        while self._running:
            await self._events.drain()
            await asyncio.sleep(0.1)

    def _create_adapter(self):
        if self._exchange_name == "binance":
            from kairos.exchanges.binance import BinanceAdapter
            return BinanceAdapter(self._api_key, self._api_secret)
        from kairos.exchanges.paper import PaperAdapter
        return PaperAdapter(
            initial_balances={self._base_currency: self._initial_balance},
        )

    def _on_bar(self, bar: Bar) -> None:
        """New bar received — update indicators and call strategies."""
        self._cache.add(bar)
        for entry in self._strategies:
            inst = entry.get("instance")
            if not inst or entry["symbol"] != bar.symbol:
                continue
            if entry["timeframe"] != bar.timeframe:
                continue
            inst._update_indicators(bar)
            if inst.indicators_ready:
                try:
                    inst.on_bar(bar)
                except Exception as e:
                    logger.error(f"Strategy error: {e}")

    def _on_fill(self, fill: Fill) -> None:
        """Order filled — update positions, notify strategies."""
        price = self._cache.last_price(fill.symbol)
        self._positions.update(fill, price)

        to_cancel = self._order_manager.process_fill(fill)
        for oid in to_cancel:
            if self._loop and self._adapter:
                self._loop.create_task(
                    self._adapter.cancel_order(fill.symbol, oid),
                )

        for entry in self._strategies:
            inst = entry.get("instance")
            if inst and entry["symbol"] == fill.symbol:
                try:
                    inst.on_fill(fill)
                except Exception as e:
                    logger.error(f"on_fill error: {e}")

    def _stop(self) -> None:
        logger.info("Shutdown signal")
        self._running = False

    async def _shutdown(self) -> None:
        self._running = False
        for entry in self._strategies:
            inst = entry.get("instance")
            if inst:
                try:
                    inst.on_stop()
                except Exception:
                    pass
        if self._adapter:
            await self._adapter.disconnect()
        logger.info("Engine stopped")

    # ── Called by Strategy ────────────────────────────

    def _submit_market_order(
        self, symbol: str, side: OrderSide, pct: float,
    ) -> bool:
        price = self._cache.last_price(symbol)
        if price <= 0 or not self._adapter or not self._loop:
            return False

        bal = self._loop.run_until_complete(self._adapter.get_balances())
        free = bal.get(self._base_currency)
        if not free or free.free <= 0:
            return False

        inst = self._loop.run_until_complete(
            self._adapter.get_instrument(symbol),
        )

        qty = (free.free * pct / 100) / price
        qty = int(qty / inst.qty_step) * inst.qty_step

        error = self._risk.validate_order(
            symbol, side, qty, price, inst, bal,
        )
        if error:
            logger.info(f"Rejected: {error}")
            return False

        self._loop.create_task(
            self._adapter.submit_order(symbol, side, OrderType.MARKET, qty),
        )
        return True

    def _submit_sell_all(self, symbol: str) -> bool:
        pos = self._positions.get(symbol)
        if not pos.is_open or not self._loop:
            return False
        self._loop.create_task(
            self._adapter.submit_order(
                symbol, OrderSide.SELL, OrderType.MARKET, pos.quantity,
            ),
        )
        return True

    def _submit_limit_order(
        self, symbol: str, side: OrderSide, price: float,
        pct: float | None = None, qty: float | None = None,
    ) -> str | None:
        if not self._loop or not self._adapter:
            return None
        if qty is None and pct:
            free = self._get_free_balance(self._base_currency)
            qty = (free * pct / 100) / price if price > 0 else 0
        if not qty or qty <= 0:
            return None
        self._loop.create_task(
            self._adapter.submit_order(
                symbol, side, OrderType.LIMIT, qty, price=price,
            ),
        )
        return "pending"

    def _submit_bracket_order(
        self, symbol: str, pct: float,
        sl_distance: float, tp_distance: float,
    ) -> bool:
        price = self._cache.last_price(symbol)
        if price <= 0:
            return False
        ok = self._submit_market_order(symbol, OrderSide.BUY, pct)
        if not ok:
            return False
        pos = self._positions.get(symbol)
        qty = pos.quantity
        if self._loop and self._adapter:
            self._loop.create_task(self._adapter.submit_order(
                symbol, OrderSide.SELL, OrderType.STOP_MARKET,
                qty, stop_price=price - sl_distance,
            ))
            self._loop.create_task(self._adapter.submit_order(
                symbol, OrderSide.SELL, OrderType.LIMIT,
                qty, price=price + tp_distance,
            ))
        return True

    def _cancel_order(self, order_id: str) -> bool:
        order = self._order_manager.get_order(order_id)
        if order and self._loop and self._adapter:
            self._loop.create_task(
                self._adapter.cancel_order(order.symbol, order_id),
            )
            return True
        return False

    def _get_free_balance(self, currency: str) -> float:
        if not self._loop or not self._adapter:
            return 0.0
        try:
            bal = self._loop.run_until_complete(self._adapter.get_balances())
            b = bal.get(currency)
            return b.free if b else 0.0
        except Exception:
            return 0.0

    def _has_position(self, symbol: str) -> bool:
        return self._positions.get(symbol).is_open

    def _get_position_qty(self, symbol: str) -> float:
        return self._positions.get(symbol).quantity

    def _get_position_pnl(self, symbol: str) -> float:
        return self._positions.get(symbol).unrealized_pnl
