"""Average Directional Index (ADX) — trend strength indicator."""

from kairos.indicators.base import Indicator
from kairos.types import Bar


class ADX(Indicator):
    def __init__(self, period: int = 14) -> None:
        super().__init__(period)
        self._prev_high = 0.0
        self._prev_low = 0.0
        self._prev_close = 0.0
        self._smooth_plus_dm = 0.0
        self._smooth_minus_dm = 0.0
        self._smooth_tr = 0.0
        self._adx = 0.0
        self._dx_sum = 0.0
        self._dx_count = 0
        self.plus_di = 0.0
        self.minus_di = 0.0

    def update(self, bar: Bar) -> None:
        super().update(bar)

        if self._count == 1:
            self._prev_high = bar.high
            self._prev_low = bar.low
            self._prev_close = bar.close
            return

        # Directional Movement
        up_move = bar.high - self._prev_high
        down_move = self._prev_low - bar.low
        plus_dm = up_move if up_move > down_move and up_move > 0 else 0
        minus_dm = down_move if down_move > up_move and down_move > 0 else 0

        # True Range
        tr = max(
            bar.high - bar.low,
            abs(bar.high - self._prev_close),
            abs(bar.low - self._prev_close),
        )

        self._prev_high = bar.high
        self._prev_low = bar.low
        self._prev_close = bar.close

        # Smoothing (Wilder's)
        if self._count <= self.period + 1:
            self._smooth_plus_dm += plus_dm
            self._smooth_minus_dm += minus_dm
            self._smooth_tr += tr
            if self._count == self.period + 1:
                self._smooth_plus_dm /= self.period
                self._smooth_minus_dm /= self.period
                self._smooth_tr /= self.period
        else:
            self._smooth_plus_dm = (
                self._smooth_plus_dm * (self.period - 1) + plus_dm
            ) / self.period
            self._smooth_minus_dm = (
                self._smooth_minus_dm * (self.period - 1) + minus_dm
            ) / self.period
            self._smooth_tr = (
                self._smooth_tr * (self.period - 1) + tr
            ) / self.period

        # DI values
        if self._smooth_tr > 0:
            self.plus_di = 100 * self._smooth_plus_dm / self._smooth_tr
            self.minus_di = 100 * self._smooth_minus_dm / self._smooth_tr

        # DX and ADX
        di_sum = self.plus_di + self.minus_di
        if di_sum > 0:
            dx = 100 * abs(self.plus_di - self.minus_di) / di_sum
            if self._dx_count < self.period:
                self._dx_sum += dx
                self._dx_count += 1
                if self._dx_count == self.period:
                    self._adx = self._dx_sum / self.period
            else:
                self._adx = (self._adx * (self.period - 1) + dx) / self.period

    @property
    def value(self) -> float:
        return self._adx

    @property
    def initialized(self) -> bool:
        return self._count >= self.period * 2
