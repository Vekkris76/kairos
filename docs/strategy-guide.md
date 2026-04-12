# Strategy Guide

## Anatomy of a Strategy

Every strategy extends `Strategy` and overrides two methods:

```python
from kairos import Strategy

class MyStrategy(Strategy):
    def setup(self):
        """Called once — declare your indicators here."""
        self.add_rsi(14)

    def on_bar(self, bar):
        """Called on every new bar — your trading logic here."""
        if self.rsi() < 30:
            self.buy(10)
```

## Lifecycle

```
Engine starts
    → strategy.setup()           # Declare indicators
    → Exchange subscribes bars
    → Bars arrive every N minutes
        → strategy.on_bar(bar)   # Your logic runs here
        → (if order fills)
            → strategy.on_fill(fill)
Engine stops
    → strategy.on_stop()         # Cleanup
```

## Indicators

### Declaration (in setup)

```python
def setup(self):
    # Moving Averages
    self.add_ema(8, "fast")      # EMA with alias "fast"
    self.add_ema(21, "slow")     # EMA with alias "slow"
    self.add_sma(50)             # Simple Moving Average

    # Oscillators
    self.add_rsi(14)             # Relative Strength Index
    self.add_macd(12, 26, 9)     # MACD
    self.add_bollinger(20, 2.0)  # Bollinger Bands

    # Volatility
    self.add_atr(14)             # Average True Range
```

### Reading Values (in on_bar)

```python
def on_bar(self, bar):
    # Moving Averages
    self.fast_ema()        # → 71250.50
    self.slow_ema()        # → 70800.20
    self.ema("custom")     # → by alias

    # RSI (always 0-100, no quirks)
    self.rsi()             # → 65.3

    # ATR
    self.atr()             # → 150.25

    # MACD
    m = self.macd()
    m["macd"]              # → 125.5
    m["signal"]            # → 100.2
    m["histogram"]         # → 25.3

    # Bollinger Bands
    b = self.bollinger()
    b["upper"]             # → 72000
    b["middle"]            # → 71000
    b["lower"]             # → 70000

    # Warmup check
    if not self.indicators_ready:
        return  # Not enough data yet
```

## Order Methods

### Market Orders

```python
# Buy with X% of free balance
self.buy(15)          # 15% of USDC → market buy

# Sell entire position
self.sell_all()       # Market sell everything
```

### Limit Orders

```python
# Limit buy at specific price
order_id = self.buy_limit(69000, pct=10)  # 10% of balance at $69k

# Limit sell at specific price
order_id = self.sell_limit(72000)          # Sell position at $72k

# Cancel an order
self.cancel(order_id)
```

### Bracket Orders (Entry + SL + TP)

```python
# Buy with automatic Stop Loss and Take Profit
self.buy_bracket(
    pct=15,       # 15% of balance
    sl_atr=1.5,   # SL at 1.5× ATR below entry
    tp_atr=3.0,   # TP at 3.0× ATR above entry (1:2 R:R)
)
```

## Portfolio Methods

```python
# Check balance
self.free_balance("USDC")    # → 132.59

# Position info
self.has_position()           # → True/False
self.position_qty()           # → 0.001 (BTC)
self.position_pnl()           # → 2.50 (unrealized)
```

## Bar Data

The `bar` parameter in `on_bar` contains:

```python
def on_bar(self, bar):
    bar.symbol      # "BTCUSDC"
    bar.timeframe   # "1h"
    bar.timestamp   # 1700000000000 (milliseconds)
    bar.open        # 70000.0
    bar.high        # 70500.0
    bar.low         # 69500.0
    bar.close       # 70200.0
    bar.volume      # 150.5
```

## Fill Callbacks

Override `on_fill` to react to order executions:

```python
def on_fill(self, fill):
    print(f"Filled: {fill.side} {fill.quantity} @ {fill.price}")
    print(f"Commission: {fill.commission}")
```

## Common Patterns

### EMA Crossover

```python
class EMACross(Strategy):
    def setup(self):
        self.add_ema(8, "fast")
        self.add_ema(21, "slow")

    def on_bar(self, bar):
        if self.fast_ema() > self.slow_ema() and not self.has_position():
            self.buy(15)
        elif self.fast_ema() < self.slow_ema() and self.has_position():
            self.sell_all()
```

### RSI Mean Reversion

```python
class RSIMeanReversion(Strategy):
    def setup(self):
        self.add_rsi(14)

    def on_bar(self, bar):
        if self.rsi() < 30 and not self.has_position():
            self.buy(20)  # Oversold — buy
        elif self.rsi() > 70 and self.has_position():
            self.sell_all()  # Overbought — sell
```

### Bollinger Bounce

```python
class BollingerBounce(Strategy):
    def setup(self):
        self.add_bollinger(20, 2.0)
        self.add_rsi(14)

    def on_bar(self, bar):
        bb = self.bollinger()
        if bar.close < bb["lower"] and self.rsi() < 30:
            self.buy(15)  # Price below lower band + oversold
        elif bar.close > bb["upper"] and self.has_position():
            self.sell_all()  # Price above upper band
```

### Multi-Timeframe Confirmation

```python
class TrendWithMomentum(Strategy):
    def setup(self):
        self.add_ema(50, "trend")
        self.add_rsi(14)
        self.add_atr(14)

    def on_bar(self, bar):
        trend_bullish = bar.close > self.ema("trend")
        momentum_ok = self.rsi() > 50

        if trend_bullish and momentum_ok and not self.has_position():
            self.buy_bracket(15, sl_atr=1.5, tp_atr=3.0)
        elif not trend_bullish and self.has_position():
            self.sell_all()
```
