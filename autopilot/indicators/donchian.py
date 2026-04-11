"""Donchian Channel."""

from collections import deque

from autopilot.indicators.base import Indicator
from autopilot.types import Bar


class DonchianChannel(Indicator):
    def __init__(self, period: int = 20) -> None:
        super().__init__(period)
        self._highs: deque[float] = deque(maxlen=period)
        self._lows: deque[float] = deque(maxlen=period)
        self.upper = 0.0
        self.lower = 0.0
        self.middle = 0.0

    def update(self, bar: Bar) -> None:
        super().update(bar)
        self._highs.append(bar.high)
        self._lows.append(bar.low)

        if len(self._highs) >= self.period:
            self.upper = max(self._highs)
            self.lower = min(self._lows)
            self.middle = (self.upper + self.lower) / 2

    @property
    def value(self) -> float:
        return self.middle
