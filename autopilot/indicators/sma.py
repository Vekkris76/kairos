"""Simple Moving Average."""

from collections import deque

from autopilot.indicators.base import Indicator
from autopilot.types import Bar


class SMA(Indicator):
    def __init__(self, period: int) -> None:
        super().__init__(period)
        self._window: deque[float] = deque(maxlen=period)

    def update(self, bar: Bar) -> None:
        super().update(bar)
        self._window.append(bar.close)

    @property
    def value(self) -> float:
        if not self._window:
            return 0.0
        return sum(self._window) / len(self._window)
