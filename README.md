# Kairos

[![CI](https://github.com/Vekkris76/kairos/actions/workflows/ci.yml/badge.svg)](https://github.com/Vekkris76/kairos/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/kairos-engine.svg)](https://pypi.org/project/kairos-engine/)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-227%20passing-brightgreen.svg)](https://github.com/Vekkris76/kairos/tree/main/tests)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

An event-driven trading engine for Python — live execution, backtesting
and paper trading with one API. Built for spot crypto, designed to
scale to multi-venue and derivatives.

---

## Installation

```bash
pip install kairos-engine
```

Requires Python 3.11 or newer.

## Quick start

```python
from kairos import LiveEngine, LiveStrategy, BinanceLive
from kairos.types import ActorConfig


class MeanReversion(LiveStrategy):
    def on_start(self):
        self.sma = self.indicator.sma("close", window=20)
        self.rsi = self.indicator.rsi(window=14)

    async def on_bar(self, bar):
        if self.rsi.value < 30 and bar.close < self.sma.value:
            await self.buy_bracket_pct(
                pct=0.10,          # 10% of USDC balance
                sl_atr_mult=2.0,   # stop-loss = entry - 2×ATR
                tp_atr_mult=3.0,   # take-profit = entry + 3×ATR
            )


engine = LiveEngine()
engine.register_adapter(BinanceLive(api_key="...", api_secret="..."))
engine.add_strategy(
    MeanReversion(ActorConfig(symbol="BTCUSDC", timeframe="1h")),
)
await engine.run()
```

A ten-minute tutorial lives in [`docs/getting-started.md`](docs/getting-started.md).

## What's in the box

| Area | Capability |
|---|---|
| **Runtime** | Async event loop · actor model · market-data cache · warmup gating |
| **Strategies** | `LiveStrategy` base class · 12 built-in indicators · bar + tick hooks |
| **Execution** | Market / limit / stop / bracket orders · OCO · atomic entry+SL+TP via `BracketManager` |
| **Adapters** | `BinanceLive` (Spot, REST + market WS + user-data WS) · `PaperAdapter` for sims |
| **Backtesting** | `BacktestEngine` with parquet catalog · Sharpe / Sortino / profit factor |
| **Reconciliation** | Fill parity tooling (`kairos.parity.match_fills`) to diff engine outputs |
| **Ops** | Structured logging · graceful shutdown · reconnect with exponential backoff |

227 tests cover the public surface; CI runs on Python 3.11, 3.12 and 3.13.

## Design goals

1. **Stable primitives, pluggable policy.** The engine handles the
   boring parts (event loop, reconnects, order state, reconciliation)
   so strategies stay small and testable.
2. **Same API for backtest, paper and live.** A strategy you write for
   backtesting runs unchanged against a paper adapter and then against
   a live exchange.
3. **Composable actors.** Risk limits, parameter tuning, notifications
   and regime detection are actors subscribed to the engine bus. Add
   your own by subclassing `kairos.Actor`.
4. **Readable over clever.** Typed public surface, minimal magic, every
   decision documented in source.

## Example — `Actor` for risk halt

```python
from kairos import Actor


class DailyLossLimit(Actor):
    def __init__(self, max_loss_pct: float = 3.0):
        super().__init__()
        self._max_loss = max_loss_pct
        self._start_equity: float | None = None

    async def on_event(self, kind: str, event):
        if kind == "equity_update":
            if self._start_equity is None:
                self._start_equity = event.equity
                return
            drawdown = (self._start_equity - event.equity) / self._start_equity
            if drawdown >= self._max_loss / 100:
                await self.publish_signal("risk_halt", reason="daily_loss")
```

The engine's `SignalDispatcher` picks up `risk_halt` and stops new
entries until the actor publishes a resume signal.

## Status and versioning

Current release: **v0.3.1** — production-deployed as the execution core
of [Trading Autopilot](https://trading-autopilot.dev) since 2026-04-13,
powering DCA strategies on BTCUSDC and ETHUSDC on Binance Spot.

Semantic versioning. Pre-1.0 releases may still contain minor
breaking changes; the CHANGELOG calls them out explicitly.

## Roadmap

| Milestone | Focus |
|---|---|
| **v0.4** | Adaptive execution — order-type + timing learned per (symbol × regime × spread) |
| **v0.5** | Continual parameter tuning — Bayesian posterior updated per trade |
| **v0.6** | Multi-venue — Kraken adapter + venue-registry abstraction |
| **v1.0** | Stable public API · long-term support |

Details in [`docs/roadmap.md`](docs/roadmap.md).

## Documentation

- [Getting started](docs/getting-started.md) — first strategy in ten lines
- [Architecture](docs/architecture.md) — runtime, actors, cache, execution
- [Strategy guide](docs/strategy-guide.md) — patterns and anti-patterns
- [Indicators](docs/indicators.md) — full list with parameters
- [Backtesting](docs/backtesting.md) — data catalog, metrics, walkforward
- [Exchange setup](docs/exchange-setup.md) — Binance API key configuration
- [Credits](CREDITS.md) — adopted primitives and license attribution

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and pull requests are
welcome. Please run `pytest` before submitting.

## Naming

*Kairós* (καιρός) is the ancient Greek word for "the opportune moment".
This package was originally published as `autopilot-engine` (v0.1.0,
March 2026) and renamed at v0.2.0a0. The legacy PyPI name redirects
here for deprecation notices.

## License

MIT — see [LICENSE](LICENSE). Derivatives and commercial use are both
permitted; attribution is appreciated.

## Citation

```bibtex
@software{kairos2026,
  title  = {Kairos: an event-driven crypto trading engine for Python},
  author = {Rovira, Oscar},
  year   = {2026},
  url    = {https://github.com/Vekkris76/kairos}
}
```
