# 🚀 Autopilot Engine

[![CI](https://github.com/Vekkris76/autopilot-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/Vekkris76/autopilot-engine/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

**The simple, powerful, Python-first crypto trading framework.**

Open source alternative to NautilusTrader — built for the community, designed for retail traders.

```python
from autopilot import Engine, Strategy

class MyBot(Strategy):
    def setup(self):
        self.add_ema(8, "fast")
        self.add_ema(21, "slow")
        self.add_rsi(14)

    def on_bar(self, bar):
        if self.fast_ema() > self.slow_ema() and self.rsi() > 50:
            self.buy(15)  # 15% of balance
        elif self.fast_ema() < self.slow_ema():
            self.sell_all()

engine = Engine(exchange="binance", api_key="...", api_secret="...")
engine.add(MyBot, symbol="BTCUSDC", timeframe="1h")
engine.add(MyBot, symbol="ETHUSDC", timeframe="1h")  # Multi-strategy!
engine.run()
```

## Why Autopilot Engine?

| | NautilusTrader | Autopilot Engine |
|---|---|---|
| First strategy | 50+ lines + JSON config | **10 lines** |
| Installation | Compile Rust/Cython | **`pip install autopilot-engine`** |
| Multi-strategy | 1 engine = 1 profile | **N strategies simultaneously** |
| Learning curve | Weeks | **Minutes** |
| Contributing | Need Rust knowledge | **Pure Python** |
| License | LGPL (restrictive) | **MIT (do anything)** |

## Features

### Core
- ⚡ Async event-driven engine with deterministic execution
- 🔄 Run multiple strategies simultaneously on multiple pairs
- 📊 15+ built-in indicators (EMA, RSI, ATR, MACD, Bollinger, VWAP...)
- 🛡️ Pre-trade risk validation (balance, lot size, notional, rate limits)
- 📈 Real-time position tracking with PnL calculation

### Orders
- Market, Limit, Stop-Market, Stop-Limit
- Bracket orders (entry + SL + TP) with one line
- OCO (one-cancels-other) and OTO (one-triggers-other)
- Post-only, reduce-only execution flags

### Exchanges
- Binance Spot (REST + WebSocket)
- Paper trading (simulated exchange for testing)
- Extensible adapter interface for adding more exchanges

### Backtesting
- Event-driven replay with historical data
- Realistic fee models (maker/taker)
- Parquet data catalog for fast loading
- Compare strategies side by side

### Risk Management
- Trading states: ACTIVE → REDUCING → HALTED
- Max drawdown protection
- Daily loss limits
- Order rate throttling

## Installation

```bash
pip install autopilot-engine
```

## Quick Start

See [examples/](examples/) for complete working strategies:
- `ema_cross.py` — Simple EMA crossover (10 lines)
- `dca_bot.py` — Dollar Cost Averaging on dips
- `grid_bot.py` — Grid trading for ranging markets
- `scalping.py` — Smart Money Concepts liquidity sweep detection

## Documentation

- [Getting Started](docs/getting-started.md)
- [Strategy Guide](docs/strategy-guide.md)
- [Exchange Setup](docs/exchange-setup.md)
- [Indicator Reference](docs/indicators.md)
- [Backtesting Guide](docs/backtesting.md)
- [Architecture](docs/architecture.md)

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

```bash
git clone https://github.com/Vekkris76/autopilot-engine.git
cd autopilot-engine
pip install -e ".[dev]"
pytest
```

## License

MIT — do whatever you want. See [LICENSE](LICENSE).

## Roadmap

- [x] v0.1 — Engine + Binance + basic orders + 12 indicators
- [x] v0.2 — Multi-strategy + risk engine
- [x] v0.3 — Backtesting engine + Parquet data catalog
- [x] v0.4 — Production hardening (reconciliation, state recovery, reconnect)
- [x] v0.5 — PyPI release + documentation + CI/CD
- [x] v1.0 — Community launch 🎉

### What's Next

- [x] WebSocket streaming (real-time via Binance WS)
- [ ] More exchanges (Bybit, Kraken, OKX)
- [ ] Strategy marketplace
- [ ] Web-based strategy builder
- [ ] Performance analytics dashboard
