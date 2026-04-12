# Kairos

[![CI](https://github.com/Vekkris76/kairos/actions/workflows/ci.yml/badge.svg)](https://github.com/Vekkris76/kairos/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![PyPI](https://img.shields.io/pypi/v/kairos-engine.svg)](https://pypi.org/project/kairos-engine/)
[![Tests](https://img.shields.io/badge/tests-181%20passing-brightgreen.svg)](https://github.com/Vekkris76/kairos/tree/main/tests)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

> **Κairós** (καιρός) — ancient Greek for *"the opportune moment"*.
> In trading, timing is everything.

**Kairos is an adaptive crypto trading engine.** It curates the best primitives from the open-source ecosystem (ccxt for connectivity, pandas-ta for math, hummingbot patterns for reconnect) and adds a single proprietary layer on top: **adaptivity**. Adaptive execution, adaptive risk, adaptive parameter tuning, regime-aware everything — and an **IngestionActor** that surveys the open-source ecosystem weekly and incorporates improvements automatically.

## Status

- **v0.1.x** (shipped): backtesting + paper trading + Binance Spot adapter + 12 indicators + order manager + risk validator + strategy marketplace + analytics + `parity` module
- **v0.2.x** (shipped): live runtime + actors + market cache + atomic bracket orders with OCO + reconciliation + Binance live adapter + design hooks for adaptive features
- **v0.3+ → v1.0** (roadmap): the differentiators — adaptive execution, behavioral risk, continual tuning, IngestionActor, why-cards, counterfactual shadow, federated learning, signed track records

See [`docs/vision.md`](docs/vision.md) for the full product vision.

## Notable history

This package was published as **`autopilot-engine`** at v0.1.0 (March 2026). It was renamed to **`kairos-engine`** at v0.2.0a0 to reflect its evolution into an adaptive engine with proprietary IP. The legacy `autopilot-engine` PyPI name remains available with a deprecation alias for 6 months.

## Quick start

```bash
pip install kairos-engine
```

```python
from kairos import Engine, Strategy

class MyBot(Strategy):
    def setup(self):
        self.add_ema(8, "fast")
        self.add_ema(21, "slow")
        self.add_rsi(14)

    def on_bar(self, bar):
        if self.fast_ema() > self.slow_ema() and self.rsi() > 50:
            self.buy(15)        # 15% of balance
        elif self.fast_ema() < self.slow_ema():
            self.sell_all()

engine = Engine(exchange="binance", api_key="...", api_secret="...")
engine.add(MyBot, symbol="BTCUSDC", timeframe="1h")
engine.add(MyBot, symbol="ETHUSDC", timeframe="1h")
engine.run()
```

## What makes Kairos different

The pitch in one sentence: **the only trading framework that improves itself by learning from the entire open-source ecosystem**.

### The curation principle

We don't reinvent. We curate the best primitives the open-source community has produced and assemble them into a coherent engine. Examples:

| Primitive | Source | License | What we use it for |
|-----------|--------|---------|--------------------|
| Exchange transport | `ccxt` | MIT | 200+ exchanges, auth quirks handled |
| Indicator math | `pandas-ta` | MIT | Proven implementations of EMA, RSI, ATR, etc. |
| WebSocket reconnect | Pattern adapted from `hummingbot` | MIT | Battle-tested backoff + reconnection |
| Order state machine | Inspired by `NautilusTrader` | LGPL (study only) | Mature design, clean-room reimplementation |
| Strategy lifecycle | Inspired by `Jesse`, `Freqtrade` | MIT/Apache | Familiar API for the community |

Full list at [`CREDITS.md`](CREDITS.md). All cited in code comments. License-clean.

### The differentiation principle

On top of the curated foundation, Kairos adds a single coherent layer: **adaptivity**.

The 10 differentiators:

1. **Adaptive execution** — OrderManager learns optimal order type + timing per (instrument × regime × spread)
2. **Behavioral risk model** — ProtectionActor learns user's true risk tolerance from revealed preferences
3. **Continual tuning** — Bayesian posterior over strategy parameters, updated per trade
4. **Cross-asset signal fusion** — regime + factor events consumed by any strategy
5. **Regime-aware everything** — execution, risk, sizing, UI all modulated by detected regime
6. **Why card on every trade** — explanation record (indicators, regime, win probability, counterfactual)
7. **Counterfactual shadow** — always-on parallel sim of alternative strategies → data-driven upgrade recommendations
8. **Cryptographically-signed track records** — Ed25519-signed performance, not falsifiable
9. **Federated cross-user learning** — privacy-preserving patterns, compounds with user count
10. **IngestionActor** — the meta-improvement engine: weekly crawls NT, ccxt, Freqtrade, Jesse, hummingbot, arxiv. LLM-classifies changes. Evaluates against our backtest data. Auto-merges or proposes PRs. **This is the moat.**

§1-9 are user-facing features. §10 is the structural differentiator: a framework that gets smarter every week without manual releases.

## Features (v0.1, what works today)

### Core
- Async event-driven engine with deterministic execution (paper / backtest)
- Multi-strategy on multiple pairs simultaneously
- 12 built-in indicators: EMA, SMA, RSI, ATR, Bollinger, MACD, Stochastic, VWAP, OBV, Donchian, ADX, HMA
- Pre-trade risk validation (balance, lot size, notional, rate limits)
- Real-time position tracking with PnL calculation

### Orders
- Market, Limit, Stop-Market, Stop-Limit
- Bracket orders (entry + SL + TP)
- Post-only, reduce-only execution flags

### Exchanges
- Binance Spot (REST + WebSocket)
- Paper exchange for backtesting / simulation

### Backtest
- Tick-level replay with parquet data catalog
- Sharpe, Sortino, profit factor analytics
- Walkforward parameter sweeps

### Strategy marketplace
- Registry + builder for composable strategies
- JSON-config → Strategy class

### Parity module
- `kairos.parity.match_fills(baseline, candidate)` — compare two engine outputs (fills) with configurable tolerances, produce PASS/WARN/FAIL verdict
- 21 unit tests, pure Python, no I/O
- Use case: validate a new engine version against a baseline before cutover

## Roadmap

- **v0.2.x — Production runtime** (3-4 weeks)
  - Live event loop with adapter registration
  - Actor base class + event routing
  - MarketCache with warmup gating
  - OrderManager extensions (brackets, OCO, reconciler)
  - Binance live adapter with user-data WebSocket
- **v0.3 — Learning milestone** (3-4 weeks after v0.2)
  - Adaptive execution (§1)
  - Continual tuning (§3)
  - Why card on every fill (§6)
- **v0.4 — Meta-improvement milestone** (4-6 weeks)
  - IngestionActor v1 (§10)
  - Counterfactual shadow (§7)
- **v0.5 — Personalization** — behavioral risk + cross-asset fusion + federated v1
- **v0.6 — Marketplace trust** — signed track records + marketplace integration
- **v1.0 — GA, commercial launch**

Roughly 6-9 months from today to v1.0 at a steady pace. Quality > speed.

## Reference customer

[Trading Autopilot](https://trading-autopilot.dev) is the flagship SaaS that runs on Kairos. After v3 of Trading Autopilot ships on Kairos v0.2 (~13 weeks of migration work), every Kairos differentiator that ships will be deployed to real users running real trades.

## Documentation

- [Vision](docs/vision.md) — manifesto, differentiators, moat, glossary
- [Architecture](docs/architecture.md) — runtime, actors, cache, execution
- [Getting Started](docs/getting-started.md) — first strategy in 10 lines
- [Strategy Guide](docs/strategy-guide.md) — patterns, examples, anti-patterns
- [Indicators](docs/indicators.md) — full list + parameters
- [Backtesting](docs/backtesting.md) — data catalog, metrics, walkforward
- [Exchange Setup](docs/exchange-setup.md) — Binance API key configuration
- [CREDITS.md](CREDITS.md) — adopted primitives + license attribution

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Note: Kairos is moving toward a more proprietary licensing model from v1.0 onwards. v0.1.x and v0.2.x stay MIT. Contributions to v0.1.x / v0.2.x are welcome under MIT terms; contributions to v0.3+ work will be subject to the final license terms (TBD).

## License

**v0.1.x and v0.2.x: MIT** (see [LICENSE](LICENSE)).

The Kairos team is reviewing the license model for v1.0+. The current intent is **source-available** with **commercial-use restrictions** (similar to Business Source License or Elastic License). The MIT-licensed v0.1/v0.2 code remains MIT forever — license changes are not retroactive.

If you're considering Kairos for commercial use, [open an issue](https://github.com/Vekkris76/kairos/issues) or reach out so we can keep you informed.

## Citations

If Kairos contributes to academic or commercial work:

```bibtex
@software{kairos2026,
  title  = {Kairos: an adaptive crypto trading engine},
  author = {Trading Autopilot Team},
  year   = {2026},
  url    = {https://github.com/Vekkris76/kairos}
}
```
