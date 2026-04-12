"""Relative Strength Index — always returns 0-100."""

from kairos.indicators.base import Indicator
from kairos.types import Bar


class RSI(Indicator):
    def __init__(self, period: int = 14) -> None:
        super().__init__(period)
        self._prev_close = 0.0
        self._avg_gain = 0.0
        self._avg_loss = 0.0
        self._value = 50.0

    def update(self, bar: Bar) -> None:
        super().update(bar)
        price = bar.close

        if self._count == 1:
            self._prev_close = price
            return

        diff = price - self._prev_close
        gain = max(diff, 0)
        loss = max(-diff, 0)
        self._prev_close = price

        if self._count <= self.period + 1:
            # Initial SMA
            self._avg_gain += gain / self.period
            self._avg_loss += loss / self.period
            if self._count == self.period + 1:
                self._calc_rsi()
        else:
            # Wilder's smoothing
            self._avg_gain = (self._avg_gain * (self.period - 1) + gain) / self.period
            self._avg_loss = (self._avg_loss * (self.period - 1) + loss) / self.period
            self._calc_rsi()

    def _calc_rsi(self) -> None:
        if self._avg_loss == 0:
            self._value = 100.0
        else:
            rs = self._avg_gain / self._avg_loss
            self._value = 100.0 - (100.0 / (1.0 + rs))

    @property
    def value(self) -> float:
        return self._value
