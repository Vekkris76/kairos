"""State persistence — save and restore engine state across restarts.

Saves positions, open orders, and indicator state to JSON.
On restart, loads the state to resume without losing track.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("autopilot.state")


class StateManager:
    """Persists engine state to disk for crash recovery."""

    def __init__(self, path: str = "./data/state.json") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, state: dict[str, Any]) -> None:
        """Save state to disk (atomic write)."""
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, default=str))
        tmp.rename(self._path)
        logger.debug("State saved")

    def load(self) -> dict[str, Any]:
        """Load state from disk. Returns empty dict if no state."""
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load state: {e}")
            return {}

    def save_positions(self, positions: dict) -> None:
        """Save position state."""
        state = self.load()
        state["positions"] = {
            symbol: {
                "quantity": pos.quantity,
                "avg_entry": pos.avg_entry,
                "realized_pnl": pos.realized_pnl,
            }
            for symbol, pos in positions.items()
            if pos.quantity > 0
        }
        self.save(state)

    def save_orders(self, orders: list) -> None:
        """Save open orders."""
        state = self.load()
        state["open_orders"] = [
            {
                "id": o.id, "symbol": o.symbol,
                "side": o.side.value, "type": o.type.value,
                "quantity": o.quantity, "price": o.price,
                "stop_price": o.stop_price,
            }
            for o in orders
        ]
        self.save(state)

    def clear(self) -> None:
        """Remove state file."""
        if self._path.exists():
            self._path.unlink()
            logger.info("State cleared")
