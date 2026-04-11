"""Stochastic Oscillator (%K and %D)."""

from collections import deque

from autopilot.indicators.base import Indicator
from autopilot.types import Bar


class Stochastic(Indicator):
    def __init__(self, k_period: int = 14, d_period: int = 3) -> None:
        super().__init__(k_period)
        self._k_period = k_period
        self._d_period = d_period
        self._highs: deque[float] = deque(maxlen=k_period)
        self._lows: deque[float] = deque(maxlen=k_period)
        self._k_values: deque[float] = deque(maxlen=d_period)
        self.k = 50.0
        self.d = 50.0

    def update(self, bar: Bar) -> None:
        super().update(bar)
        self._highs.append(bar.high)
        self._lows.append(bar.low)

        if len(self._highs) < self._k_period:
            return

        highest = max(self._highs)
        lowest = min(self._lows)
        diff = highest - lowest
        self.k = ((bar.close - lowest) / diff * 100) if diff > 0 else 50.0
        self._k_values.append(self.k)
        self.d = sum(self._k_values) / len(self._k_values)

    @property
    def value(self) -> float:
        return self.k
