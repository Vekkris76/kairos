# Indicator Reference

Autopilot Engine includes 12 built-in indicators. All are pure Python, no external dependencies.

## Moving Averages

### EMA — Exponential Moving Average

Gives more weight to recent prices. Faster to react than SMA.

```python
self.add_ema(8, "fast")    # Period 8 with alias
self.add_ema(21, "slow")   # Period 21

# Access
self.fast_ema()            # → 71250.50
self.ema("slow")           # → 70800.20
```

**When to use**: Trend direction, crossover signals, dynamic support/resistance.

### SMA — Simple Moving Average

Equal weight to all prices in the window. Smoother but slower.

```python
self.add_sma(50)
self.ema("sma_50")         # → 70500.00  (accessed by auto-key)
```

**When to use**: Long-term trend identification, baseline comparison.

### HMA — Hull Moving Average

Eliminates lag while maintaining smoothness. Best of both worlds.

```python
self.add_hma(16)
```

**When to use**: When you need a fast, smooth average without lag.

## Oscillators

### RSI — Relative Strength Index

Measures momentum on a 0-100 scale. **Always returns 0-100** (no quirks).

```python
self.add_rsi(14)
self.rsi()                 # → 65.3

# Classic levels
if self.rsi() < 30:        # Oversold
if self.rsi() > 70:        # Overbought
```

**When to use**: Overbought/oversold signals, momentum confirmation, divergences.

### Stochastic Oscillator

Compares close price to the high-low range. Returns %K and %D (0-100).

```python
self.add_stochastic(14, 3)  # K period, D period
```

Access via `self._indicators["stochastic_14"]`:
- `.k` — Fast line (0-100)
- `.d` — Slow line (signal, 0-100)

**When to use**: Overbought/oversold in ranging markets, crossover of %K and %D.

### MACD — Moving Average Convergence Divergence

Trend-following momentum indicator. Three components.

```python
self.add_macd(12, 26, 9)

m = self.macd()
m["macd"]         # → 125.5  (MACD line)
m["signal"]       # → 100.2  (Signal line)
m["histogram"]    # → 25.3   (MACD - Signal)
```

**When to use**: Trend changes (histogram crosses zero), momentum strength.

## Volatility

### ATR — Average True Range

Measures volatility in price units. Essential for position sizing and SL/TP.

```python
self.add_atr(14)
self.atr()                 # → 150.25 (in price units)

# Usage: bracket with 1.5× ATR stop loss
self.buy_bracket(15, sl_atr=1.5, tp_atr=3.0)
```

**When to use**: Stop loss placement, position sizing, volatility filters.

### Bollinger Bands

SMA with upper/lower bands at N standard deviations.

```python
self.add_bollinger(20, 2.0)

bb = self.bollinger()
bb["upper"]       # → 72000
bb["middle"]      # → 71000  (SMA)
bb["lower"]       # → 70000
```

**When to use**: Mean reversion (buy at lower, sell at upper), squeeze detection.

### Donchian Channel

Highest high and lowest low over N periods.

```python
self.add_donchian(20)
```

Access via `self._indicators["donchian"]`:
- `.upper` — Highest high
- `.lower` — Lowest low
- `.middle` — Midpoint

**When to use**: Breakout strategies (Turtle Trading), trend channels.

## Volume

### VWAP — Volume Weighted Average Price

Average price weighted by volume. Institutional benchmark.

```python
self.add_vwap()
```

**When to use**: Intraday fair value, institutional reference, support/resistance.

### OBV — On Balance Volume

Cumulative volume — adds on up days, subtracts on down days.

```python
self.add_obv()
```

**When to use**: Confirm trends (rising OBV = accumulation), divergences.

## Trend

### ADX — Average Directional Index

Measures trend strength (0-100). Does NOT indicate direction.

```python
self.add_adx(14)
```

Access via `self._indicators["adx_14"]`:
- `.value` — ADX (trend strength, >25 = trending)
- `.plus_di` — +DI (bullish direction)
- `.minus_di` — -DI (bearish direction)

**When to use**: Filter trending vs ranging markets. Only trade trends when ADX > 25.

## Adding Custom Indicators

Create a file in `autopilot/indicators/`:

```python
from kairos.indicators.base import Indicator
from kairos.types import Bar

class MyIndicator(Indicator):
    def __init__(self, period: int = 14) -> None:
        super().__init__(period)
        self._value = 0.0

    def update(self, bar: Bar) -> None:
        super().update(bar)
        # Your calculation here
        self._value = bar.close  # Example

    @property
    def value(self) -> float:
        return self._value
```

Then register it in your strategy:

```python
class MyStrategy(Strategy):
    def setup(self):
        from my_indicators import MyIndicator
        self._indicators["my_ind"] = MyIndicator(14)

    def on_bar(self, bar):
        val = self._indicators["my_ind"].value
```
