"""On Balance Volume."""

from kairos.indicators.base import Indicator
from kairos.types import Bar


class OBV(Indicator):
    def __init__(self, period: int = 0) -> None:
        super().__init__(period or 1)
        self._prev_close = 0.0
        self._obv = 0.0

    def update(self, bar: Bar) -> None:
        super().update(bar)
        if self._count == 1:
            self._prev_close = bar.close
            return

        if bar.close > self._prev_close:
            self._obv += bar.volume
        elif bar.close < self._prev_close:
            self._obv -= bar.volume
        self._prev_close = bar.close

    @property
    def value(self) -> float:
        return self._obv

    @property
    def initialized(self) -> bool:
        return self._count >= 2
