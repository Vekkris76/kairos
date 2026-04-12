"""Volume Weighted Average Price."""

from kairos.indicators.base import Indicator
from kairos.types import Bar


class VWAP(Indicator):
    def __init__(self, period: int = 0) -> None:
        super().__init__(period or 1)
        self._cum_volume = 0.0
        self._cum_tp_volume = 0.0

    def update(self, bar: Bar) -> None:
        super().update(bar)
        typical_price = (bar.high + bar.low + bar.close) / 3
        self._cum_volume += bar.volume
        self._cum_tp_volume += typical_price * bar.volume

    @property
    def value(self) -> float:
        if self._cum_volume == 0:
            return 0.0
        return self._cum_tp_volume / self._cum_volume

    @property
    def initialized(self) -> bool:
        return self._count > 0
