"""In-memory bar cache."""

from __future__ import annotations

from collections import deque

from autopilot.types import Bar


class BarCache:
    """Rolling cache of recent bars per symbol/timeframe."""

    def __init__(self, max_bars: int = 500) -> None:
        self._bars: dict[str, deque[Bar]] = {}
        self._max_bars = max_bars

    def add(self, bar: Bar) -> None:
        key = f"{bar.symbol}:{bar.timeframe}"
        if key not in self._bars:
            self._bars[key] = deque(maxlen=self._max_bars)
        self._bars[key].append(bar)

    def get(self, symbol: str, timeframe: str, count: int = 0) -> list[Bar]:
        key = f"{symbol}:{timeframe}"
        bars = self._bars.get(key, deque())
        if count > 0:
            return list(bars)[-count:]
        return list(bars)

    def last(self, symbol: str, timeframe: str) -> Bar | None:
        key = f"{symbol}:{timeframe}"
        bars = self._bars.get(key)
        return bars[-1] if bars else None

    def count(self, symbol: str, timeframe: str) -> int:
        key = f"{symbol}:{timeframe}"
        return len(self._bars.get(key, []))

    def last_price(self, symbol: str) -> float:
        """Get last close price from any timeframe for a symbol."""
        for key, bars in self._bars.items():
            if key.startswith(f"{symbol}:") and bars:
                return bars[-1].close
        return 0.0
