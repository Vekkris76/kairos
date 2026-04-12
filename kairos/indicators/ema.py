"""Exponential Moving Average."""

from kairos.indicators.base import Indicator
from kairos.types import Bar


class EMA(Indicator):
    def __init__(self, period: int) -> None:
        super().__init__(period)
        self._multiplier = 2.0 / (period + 1)
        self._value = 0.0

    def update(self, bar: Bar) -> None:
        super().update(bar)
        price = bar.close
        if self._count == 1:
            self._value = price
        else:
            self._value = price * self._multiplier + self._value * (1 - self._multiplier)

    @property
    def value(self) -> float:
        return self._value
