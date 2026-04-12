# Backtesting Guide

## Why Backtest?

Never trade a strategy with real money before testing it on historical data. Backtesting tells you:
- Would this strategy have been profitable?
- What's the maximum drawdown?
- How many trades does it generate?
- What's the win rate?

## Quick Start

```python
from kairos import BacktestEngine, Strategy
from kairos.types import Bar

class MyBot(Strategy):
    def setup(self):
        self.add_ema(8, "fast")
        self.add_ema(21, "slow")

    def on_bar(self, bar):
        if not self.indicators_ready:
            return
        if self.fast_ema() > self.slow_ema() and not self.has_position():
            self.buy(20)
        elif self.fast_ema() < self.slow_ema() and self.has_position():
            self.sell_all()

# Create bars (normally loaded from CSV or API)
bars = load_your_data()  # list of Bar objects

# Run backtest
bt = BacktestEngine(initial_balance=1000, fee_rate=0.001)
bt.load_bars("BTCUSDC", "1h", bars)
bt.add(MyBot, symbol="BTCUSDC", timeframe="1h")
results = bt.run()

print(results)
```

## Loading Data

### From Binance API

```python
import json
from urllib.request import urlopen
from kairos.types import Bar

def fetch_binance_bars(symbol, interval, days=30):
    import time
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (days * 86400 * 1000)
    bars = []

    while start_ms < end_ms:
        url = (
            f"https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}&interval={interval}"
            f"&startTime={start_ms}&limit=1000"
        )
        with urlopen(url) as resp:
            klines = json.loads(resp.read())
        if not klines:
            break
        for k in klines:
            bars.append(Bar(
                symbol=symbol, timeframe=interval,
                timestamp=k[0],
                open=float(k[1]), high=float(k[2]),
                low=float(k[3]), close=float(k[4]),
                volume=float(k[5]),
            ))
        start_ms = klines[-1][6] + 1
        time.sleep(0.2)

    return bars

# Usage
bars = fetch_binance_bars("BTCUSDC", "1h", days=90)
print(f"Loaded {len(bars)} bars")
```

### From CSV

```python
import csv
from kairos.types import Bar

def load_csv(filename, symbol, timeframe):
    bars = []
    with open(filename) as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append(Bar(
                symbol=symbol, timeframe=timeframe,
                timestamp=int(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            ))
    return bars
```

## Understanding Results

```
=== Backtest Results ===
Bars:          2160        # Total bars processed
Trades:        42          # Completed round-trips (buy + sell)
Win Rate:      61.9%       # Percentage of profitable trades
Return:        +12.50%     # Total return on initial capital
PnL:           +125.00     # Absolute profit/loss
Max Drawdown:  3.20%       # Largest peak-to-trough decline
Profit Factor: 1.85        # Gross profits / gross losses (>1 = profitable)
Initial:       1000.00     # Starting balance
Final:         1125.00     # Ending balance
```

### What Good Results Look Like

| Metric | Bad | OK | Good | Excellent |
|--------|-----|-----|------|-----------|
| Win Rate | <40% | 40-55% | 55-65% | >65% |
| Profit Factor | <1.0 | 1.0-1.3 | 1.3-2.0 | >2.0 |
| Max Drawdown | >20% | 10-20% | 5-10% | <5% |
| Return/Drawdown | <1 | 1-2 | 2-5 | >5 |

## Comparing Strategies

```python
bt1 = BacktestEngine(initial_balance=1000)
bt1.load_bars("BTCUSDC", "1h", bars)
bt1.add(EMACross, symbol="BTCUSDC", timeframe="1h")
r1 = bt1.run()

bt2 = BacktestEngine(initial_balance=1000)
bt2.load_bars("BTCUSDC", "1h", bars)
bt2.add(RSIMeanReversion, symbol="BTCUSDC", timeframe="1h")
r2 = bt2.run()

print(f"EMA Cross:      {r1.return_pct:+.2f}% | WR: {r1.win_rate:.0%}")
print(f"RSI Reversion:  {r2.return_pct:+.2f}% | WR: {r2.win_rate:.0%}")
```

## Common Pitfalls

1. **Overfitting**: A strategy that works on 2024 data might fail on 2025. Test on multiple periods.
2. **Ignoring fees**: Always set `fee_rate=0.001` (0.1% Binance). Fees eat into small trades.
3. **Survivorship bias**: Don't just test on BTC — test on pairs that also went down.
4. **Too few trades**: 10 trades isn't statistically significant. Aim for 50+.
5. **Look-ahead bias**: Your strategy should only use data available at the time of decision.
