"""Exchange adapter interface — all exchanges implement this."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from autopilot.types import Balance, Bar, Fill, Instrument, Order, OrderSide, OrderType, TimeInForce


class ExchangeAdapter(ABC):
    """Abstract base for exchange adapters."""

    @abstractmethod
    async def connect(self) -> None:
        """Connect to the exchange (REST + WebSocket)."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect gracefully."""

    # ── Market Data ───────────────────────────────────

    @abstractmethod
    async def subscribe_bars(
        self, symbol: str, timeframe: str, callback: Callable[[Bar], None],
    ) -> None:
        """Subscribe to real-time OHLCV bars."""

    @abstractmethod
    async def get_historical_bars(
        self, symbol: str, timeframe: str,
        start_ms: int, end_ms: int,
    ) -> list[Bar]:
        """Fetch historical bars."""

    # ── Orders ────────────────────────────────────────

    @abstractmethod
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
        """Submit an order to the exchange."""

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an open order."""

    @abstractmethod
    async def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        """Get all open orders."""

    # ── Account ───────────────────────────────────────

    @abstractmethod
    async def get_balances(self) -> dict[str, Balance]:
        """Get account balances."""

    @abstractmethod
    async def get_instrument(self, symbol: str) -> Instrument:
        """Get instrument specifications (lot size, tick size, etc.)."""

    # ── Callbacks ─────────────────────────────────────

    def on_fill(self, callback: Callable[[Fill], None]) -> None:
        """Register a callback for order fills."""
        self._fill_callback = callback

    def on_order_update(self, callback: Callable[[Order], None]) -> None:
        """Register a callback for order status updates."""
        self._order_callback = callback
