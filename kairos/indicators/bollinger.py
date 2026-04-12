"""Bollinger Bands."""

import math
from collections import deque

from kairos.indicators.base import Indicator
from kairos.types import Bar


class BollingerBands(Indicator):
    def __init__(self, period: int = 20, std_dev: float = 2.0) -> None:
        super().__init__(period)
        self._std_dev = std_dev
        self._window: deque[float] = deque(maxlen=period)
        self.upper = 0.0
        self.middle = 0.0
        self.lower = 0.0

    def update(self, bar: Bar) -> None:
        super().update(bar)
        self._window.append(bar.close)

        if len(self._window) < self.period:
            return

        self.middle = sum(self._window) / len(self._window)
        variance = sum((x - self.middle) ** 2 for x in self._window) / len(self._window)
        std = math.sqrt(variance)
        self.upper = self.middle + self._std_dev * std
        self.lower = self.middle - self._std_dev * std

    @property
    def value(self) -> float:
        return self.middle
