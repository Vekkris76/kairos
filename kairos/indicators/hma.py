"""Hull Moving Average — smoother and faster than EMA."""

import math

from kairos.indicators.base import Indicator
from kairos.indicators.ema import EMA
from kairos.types import Bar


class HMA(Indicator):
    def __init__(self, period: int = 16) -> None:
        super().__init__(period)
        half = max(period // 2, 1)
        sqrt_p = max(int(math.sqrt(period)), 1)
        self._ema_half = EMA(half)
        self._ema_full = EMA(period)
        self._ema_sqrt = EMA(sqrt_p)
        self._value = 0.0

    def update(self, bar: Bar) -> None:
        super().update(bar)
        self._ema_half.update(bar)
        self._ema_full.update(bar)

        if self._ema_full.initialized:
            diff = 2 * self._ema_half.value - self._ema_full.value
            diff_bar = Bar(
                symbol="", timeframe="", timestamp=0,
                open=diff, high=diff, low=diff, close=diff, volume=0,
            )
            self._ema_sqrt.update(diff_bar)
            self._value = self._ema_sqrt.value

    @property
    def value(self) -> float:
        return self._value

    @property
    def initialized(self) -> bool:
        return self._ema_full.initialized and self._ema_sqrt.initialized
