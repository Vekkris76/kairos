# Getting Started

## Installation

```bash
pip install autopilot-engine
```

Or from source:

```bash
git clone https://github.com/Vekkris76/autopilot-engine.git
cd autopilot-engine
pip install -e .
```

## Your First Strategy

Create a file called `my_bot.py`:

```python
from kairos import Engine, Strategy

class SimpleBot(Strategy):
    def setup(self):
        self.add_ema(8, "fast")
        self.add_ema(21, "slow")

    def on_bar(self, bar):
        if self.fast_ema() > self.slow_ema():
            if not self.has_position():
                self.buy(20)  # Buy with 20% of balance
        else:
            if self.has_position():
                self.sell_all()

# Paper trading (simulated — no real money)
engine = Engine(exchange="paper", initial_balance=1000)
engine.add(SimpleBot, symbol="BTCUSDC", timeframe="1h")
engine.run()
```

Run it:

```bash
python my_bot.py
```

## Going Live

Replace `paper` with `binance` and add your API keys:

```python
engine = Engine(
    exchange="binance",
    api_key="your_api_key",
    api_secret="your_api_secret",
)
engine.add(SimpleBot, symbol="BTCUSDC", timeframe="1h")
engine.run()
```

> **Important**: Create API keys with **trading permissions only** — never enable withdrawals.

## Multi-Strategy

Run multiple strategies simultaneously — each one operates independently:

```python
engine = Engine(exchange="paper", initial_balance=1000)

# Different strategies on different pairs
engine.add(TrendFollower, symbol="BTCUSDC", timeframe="1h")
engine.add(MeanReversion, symbol="ETHUSDC", timeframe="15m")
engine.add(GridBot, symbol="SOLUSDC", timeframe="4h")

engine.run()  # All three run at the same time!
```

## Backtesting

Test your strategy on historical data before risking real money:

```python
from kairos import BacktestEngine
from kairos.types import Bar

# Load your data (from CSV, API, or any source)
bars = [
    Bar("BTCUSDC", "1h", 1700000000000, 70000, 70500, 69500, 70200, 100),
    Bar("BTCUSDC", "1h", 1700003600000, 70200, 71000, 70000, 70800, 150),
    # ... more bars
]

bt = BacktestEngine(initial_balance=1000)
bt.load_bars("BTCUSDC", "1h", bars)
bt.add(SimpleBot, symbol="BTCUSDC", timeframe="1h")
results = bt.run()

print(results)
# === Backtest Results ===
# Trades:        42
# Win Rate:      61.9%
# Return:        +12.50%
# Max Drawdown:  3.20%
```

## Next Steps

- [Strategy Guide](strategy-guide.md) — Learn all available methods
- [Indicator Reference](indicators.md) — 12 built-in indicators
- [Exchange Setup](exchange-setup.md) — Configure Binance
- [Backtesting Guide](backtesting.md) — Test strategies properly
