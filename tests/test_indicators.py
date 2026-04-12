"""Tests for all indicators."""

from kairos.types import Bar
from kairos.indicators.ema import EMA
from kairos.indicators.sma import SMA
from kairos.indicators.rsi import RSI
from kairos.indicators.atr import ATR
from kairos.indicators.bollinger import BollingerBands
from kairos.indicators.macd import MACD


def _bar(close: float, high: float = 0, low: float = 0, volume: float = 100) -> Bar:
    h = high or close * 1.001
    lo = low or close * 0.999
    return Bar(symbol="TEST", timeframe="1h", timestamp=0,
               open=close, high=h, low=lo, close=close, volume=volume)


class TestEMA:
    def test_first_value_is_price(self):
        ema = EMA(10)
        ema.update(_bar(100))
        assert ema.value == 100

    def test_converges(self):
        ema = EMA(3)
        for price in [10, 20, 30, 40, 50]:
            ema.update(_bar(price))
        assert ema.value > 40  # Should be close to recent prices

    def test_initialized_after_period(self):
        ema = EMA(5)
        for i in range(4):
            ema.update(_bar(100))
            assert not ema.initialized
        ema.update(_bar(100))
        assert ema.initialized


class TestSMA:
    def test_simple_average(self):
        sma = SMA(3)
        for price in [10, 20, 30]:
            sma.update(_bar(price))
        assert sma.value == 20.0

    def test_rolling_window(self):
        sma = SMA(3)
        for price in [10, 20, 30, 40]:
            sma.update(_bar(price))
        assert sma.value == 30.0  # (20+30+40)/3


class TestRSI:
    def test_returns_0_to_100(self):
        rsi = RSI(14)
        prices = [44, 44.34, 44.09, 43.61, 44.33, 44.83, 45.10,
                  45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28,
                  46.28, 46.00, 46.03, 46.41, 46.22, 45.64]
        for p in prices:
            rsi.update(_bar(p))
        assert 0 <= rsi.value <= 100

    def test_all_gains_is_100(self):
        rsi = RSI(5)
        for i in range(20):
            rsi.update(_bar(100 + i))
        assert rsi.value > 90

    def test_all_losses_near_0(self):
        rsi = RSI(5)
        for i in range(20):
            rsi.update(_bar(100 - i))
        assert rsi.value < 10

    def test_initialized(self):
        rsi = RSI(14)
        for i in range(13):
            rsi.update(_bar(100 + i))
            assert not rsi.initialized
        rsi.update(_bar(114))
        assert rsi.initialized


class TestATR:
    def test_basic_atr(self):
        atr = ATR(3)
        atr.update(Bar("T", "1h", 0, 10, 12, 9, 11, 100))   # range=3
        atr.update(Bar("T", "1h", 0, 11, 14, 10, 13, 100))  # TR=max(4, 3, 1)=4
        atr.update(Bar("T", "1h", 0, 13, 15, 11, 14, 100))  # TR=max(4, 2, 2)=4
        assert atr.initialized
        assert atr.value > 0

    def test_not_initialized_early(self):
        atr = ATR(14)
        for i in range(13):
            atr.update(Bar("T", "1h", 0, 100, 101, 99, 100, 100))
        assert not atr.initialized


class TestBollinger:
    def test_bands(self):
        bb = BollingerBands(5, 2.0)
        for p in [20, 21, 22, 21, 20]:
            bb.update(_bar(p))
        assert bb.upper > bb.middle > bb.lower
        assert bb.middle == 20.8  # (20+21+22+21+20)/5

    def test_not_initialized_early(self):
        bb = BollingerBands(20)
        for i in range(19):
            bb.update(_bar(100))
        assert not bb.initialized


class TestMACD:
    def test_macd_values(self):
        macd = MACD(3, 6, 3)
        prices = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
        for p in prices:
            macd.update(_bar(p))
        # In uptrend, MACD should be positive
        assert macd.macd_value > 0

    def test_histogram(self):
        macd = MACD(3, 6, 3)
        prices = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
        for p in prices:
            macd.update(_bar(p))
        assert macd.histogram == macd.macd_value - macd.signal_value
