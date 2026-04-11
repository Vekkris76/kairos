"""Average True Range."""

from autopilot.indicators.base import Indicator
from autopilot.types import Bar


class ATR(Indicator):
    def __init__(self, period: int = 14) -> None:
        super().__init__(period)
        self._prev_close = 0.0
        self._value = 0.0
        self._sum = 0.0

    def update(self, bar: Bar) -> None:
        super().update(bar)

        if self._count == 1:
            tr = bar.high - bar.low
            self._prev_close = bar.close
            self._sum += tr
            return

        # True Range = max of:
        #   high - low
        #   |high - prev_close|
        #   |low - prev_close|
        tr = max(
            bar.high - bar.low,
            abs(bar.high - self._prev_close),
            abs(bar.low - self._prev_close),
        )
        self._prev_close = bar.close

        if self._count <= self.period:
            self._sum += tr
            if self._count == self.period:
                self._value = self._sum / self.period
        else:
            # Wilder's smoothing
            self._value = (self._value * (self.period - 1) + tr) / self.period

    @property
    def value(self) -> float:
        return self._value
