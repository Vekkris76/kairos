"""Position Tracker — netting mode position management."""

from __future__ import annotations

import logging

from autopilot.types import Fill, OrderSide, Position

logger = logging.getLogger("autopilot.positions")


class PositionTracker:
    """Tracks positions per instrument (netting mode)."""

    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}

    def get(self, symbol: str) -> Position:
        if symbol not in self._positions:
            self._positions[symbol] = Position(symbol=symbol)
        return self._positions[symbol]

    def update(self, fill: Fill, last_price: float | None = None) -> None:
        """Update position from a fill."""
        pos = self.get(fill.symbol)

        if fill.side == OrderSide.BUY:
            # Adding to position
            if pos.quantity == 0:
                pos.avg_entry = fill.price
            else:
                # Volume-weighted average
                total_cost = pos.avg_entry * pos.quantity + fill.price * fill.quantity
                pos.quantity += fill.quantity
                pos.avg_entry = total_cost / pos.quantity if pos.quantity > 0 else 0
                pos.quantity = round(pos.quantity, 8)
        else:
            # Reducing position
            if pos.quantity > 0:
                realized = (fill.price - pos.avg_entry) * fill.quantity
                pos.realized_pnl += realized - fill.commission
                pos.quantity -= fill.quantity
                pos.quantity = max(round(pos.quantity, 8), 0)

                if pos.quantity <= 0:
                    # Position closed
                    pos.quantity = 0
                    pos.avg_entry = 0

        # Update unrealized PnL
        if last_price and pos.quantity > 0:
            pos.unrealized_pnl = (last_price - pos.avg_entry) * pos.quantity

        logger.info(
            f"Position {fill.symbol}: "
            f"qty={pos.quantity:.6f}, "
            f"avg={pos.avg_entry:.2f}, "
            f"realized={pos.realized_pnl:.4f}",
        )

    def update_prices(self, prices: dict[str, float]) -> None:
        """Update unrealized PnL from latest prices."""
        for symbol, price in prices.items():
            pos = self._positions.get(symbol)
            if pos and pos.quantity > 0:
                pos.unrealized_pnl = (price - pos.avg_entry) * pos.quantity

    @property
    def all_positions(self) -> dict[str, Position]:
        return dict(self._positions)

    @property
    def open_positions(self) -> list[Position]:
        return [p for p in self._positions.values() if p.is_open]
