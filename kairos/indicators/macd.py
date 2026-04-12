"""Moving Average Convergence Divergence."""

from kairos.indicators.base import Indicator
from kairos.indicators.ema import EMA
from kairos.types import Bar


class MACD(Indicator):
    def __init__(
        self, fast: int = 12, slow: int = 26, signal: int = 9,
    ) -> None:
        super().__init__(slow)
        self._fast_ema = EMA(fast)
        self._slow_ema = EMA(slow)
        self._signal_ema = EMA(signal)
        self.macd_value = 0.0
        self.signal_value = 0.0
        self.histogram = 0.0

    def update(self, bar: Bar) -> None:
        super().update(bar)
        self._fast_ema.update(bar)
        self._slow_ema.update(bar)

        if self._slow_ema.initialized:
            self.macd_value = self._fast_ema.value - self._slow_ema.value
            # Feed MACD value into signal EMA via synthetic bar
            macd_bar = Bar(
                symbol="", timeframe="", timestamp=0,
                open=self.macd_value, high=self.macd_value,
                low=self.macd_value, close=self.macd_value,
                volume=0,
            )
            self._signal_ema.update(macd_bar)
            self.signal_value = self._signal_ema.value
            self.histogram = self.macd_value - self.signal_value

    @property
    def value(self) -> float:
        return self.macd_value

    @property
    def initialized(self) -> bool:
        return self._slow_ema.initialized and self._signal_ema.initialized
