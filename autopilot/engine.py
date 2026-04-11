"""Autopilot Engine — multi-strategy trading engine.

The main entry point. Manages strategies, exchange connection,
data feed, orders, and risk validation.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any

from autopilot.events import EventBus
from autopilot.strategy import Strategy
from autopilot.types import Bar, OrderSide

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
        **kwargs: Any,
    ) -> None:
        self._exchange_name = exchange
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_currency = base_currency
        self._kwargs = kwargs

        self._strategies: list[dict] = []  # [{strategy, symbol, timeframe}]
        self._events = EventBus()
        self._running = False

        # These are initialized in _setup()
        self._adapter = None  # ExchangeAdapter
        self._order_manager = None
        self._position_tracker = None
        self._risk_validator = None

    def add(
        self,
        strategy_cls: type[Strategy],
        symbol: str,
        timeframe: str = "1h",
        **params: Any,
    ) -> None:
        """Register a strategy to run on a symbol/timeframe."""
        self._strategies.append({
            "cls": strategy_cls,
            "symbol": symbol,
            "timeframe": timeframe,
            "params": params,
        })
        logger.info(
            f"Registered {strategy_cls.__name__} "
            f"on {symbol} @ {timeframe}",
        )

    def run(self) -> None:
        """Start the engine (blocking). Handles SIGINT/SIGTERM."""
        logger.info(
            f"Autopilot Engine starting "
            f"({len(self._strategies)} strategies)",
        )

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Graceful shutdown
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._handle_signal)

        try:
            loop.run_until_complete(self._run_async())
        except KeyboardInterrupt:
            pass
        finally:
            loop.run_until_complete(self._shutdown())
            loop.close()
            logger.info("Engine stopped")

    async def _run_async(self) -> None:
        """Main async loop."""
        await self._setup()
        self._running = True

        logger.info("Engine RUNNING — waiting for bars...")

        while self._running:
            await self._events.process()

    async def _setup(self) -> None:
        """Initialize all components."""
        # TODO: Initialize exchange adapter, order manager, etc.
        # For now, create strategy instances and bind them
        for entry in self._strategies:
            instance = entry["cls"]()
            instance._bind(self, entry["symbol"], entry["timeframe"])
            instance.setup()
            entry["instance"] = instance
            logger.info(
                f"Strategy {entry['cls'].__name__} ready "
                f"on {entry['symbol']}",
            )

    async def _shutdown(self) -> None:
        """Graceful shutdown — cancel orders, close connections."""
        self._running = False
        for entry in self._strategies:
            instance = entry.get("instance")
            if instance:
                instance.on_stop()
        logger.info("Shutdown complete")

    def _handle_signal(self) -> None:
        """Handle SIGINT/SIGTERM."""
        logger.info("Received shutdown signal")
        self._running = False

    # ── Order Submission (called by Strategy) ─────────

    def _submit_market_order(
        self, symbol: str, side: OrderSide, pct: float,
    ) -> bool:
        """Submit a market order. Called by Strategy.buy()/sell_all()."""
        # TODO: Implement with exchange adapter
        logger.info(f"ORDER: {side.value} {pct}% {symbol}")
        return True

    def _submit_sell_all(self, symbol: str) -> bool:
        """Sell entire position. Called by Strategy.sell_all()."""
        # TODO: Implement
        logger.info(f"ORDER: SELL ALL {symbol}")
        return True

    def _submit_limit_order(
        self, symbol: str, side: OrderSide, price: float,
        pct: float | None = None, qty: float | None = None,
    ) -> str | None:
        """Submit a limit order. Returns order_id."""
        # TODO: Implement
        logger.info(f"ORDER: {side.value} LIMIT {symbol} @ {price}")
        return None

    def _submit_bracket_order(
        self, symbol: str, pct: float,
        sl_distance: float, tp_distance: float,
    ) -> bool:
        """Submit bracket order (entry + SL + TP)."""
        # TODO: Implement
        logger.info(
            f"ORDER: BRACKET BUY {pct}% {symbol} "
            f"SL={sl_distance} TP={tp_distance}",
        )
        return True

    def _cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        # TODO: Implement
        return True

    # ── Portfolio Queries (called by Strategy) ────────

    def _get_free_balance(self, currency: str) -> float:
        # TODO: Implement
        return 0.0

    def _has_position(self, symbol: str) -> bool:
        # TODO: Implement
        return False

    def _get_position_qty(self, symbol: str) -> float:
        # TODO: Implement
        return 0.0

    def _get_position_pnl(self, symbol: str) -> float:
        # TODO: Implement
        return 0.0
