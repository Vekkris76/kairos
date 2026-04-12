# Changelog

All notable changes documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) + semver.

## [0.2.0a0] — 2026-04-12 — *Kairos launch*

This is the rename release. The package transitions from `autopilot-engine` to `kairos-engine`. No new features in this alpha — the runtime work for v0.2 starts after this. Publishing now to claim the PyPI namespace and signal the rebrand.

### Renamed
- **Package on PyPI**: `autopilot-engine` → `kairos-engine`
- **Top-level Python module**: `autopilot` → `kairos`
- **GitHub repo**: `Vekkris76/autopilot-engine` → `Vekkris76/kairos` (auto-redirect active)

### Added
- [`docs/vision.md`](docs/vision.md) — full product vision: manifesto, 10 differentiators, glossary, moat, roadmap to v1.0
- README rewrite around the *curate-plus-differentiate* principle
- License model note: v0.1.x and v0.2.x stay MIT; v1.0+ under review (likely source-available with commercial restrictions)

### Migration from `autopilot-engine` 0.1.0

For users (none external yet — only us):

```bash
pip uninstall autopilot-engine
pip install kairos-engine
```

In your code, replace:
```python
from autopilot import Engine, Strategy
```
with:
```python
from kairos import Engine, Strategy
```

A deprecation alias for `autopilot-engine` will be published as `0.1.99` separately, providing a 6-month transition window.

### What's NOT in this release

- Live runtime (LiveEngine, Actor, MarketCache) — coming in 0.2.0 final
- Adaptive features (§1-10 from vision) — coming v0.3+
- IngestionActor — coming v0.4

This is purely a rename + rebrand release.

---

## [0.1.0] — 2026-03 — *Initial public release as autopilot-engine*

First release. Preserved here for historical reference.

### Added
- Async event-driven engine (paper trading + backtest)
- 12 built-in indicators (EMA, SMA, RSI, ATR, MACD, Bollinger, Stochastic, VWAP, OBV, Donchian, ADX, HMA)
- Order manager (market, limit, stop variants, brackets)
- Position tracker with PnL netting
- Risk validator (balance, lot size, notional, drawdown, rate limits)
- Backtest engine with parquet data catalog
- Binance Spot adapter (CCXT + WebSocket)
- Strategy marketplace (registry + builder)
- Analytics (Sharpe, Sortino, profit factor)
- 38 unit tests
- CI/CD pipeline
- Public PyPI release as `autopilot-engine`

### Subsequent additions (pre-rename)
- [`autopilot.parity`](autopilot/parity/) module — fill matcher with PASS/WARN/FAIL verdict for cross-engine parity checks (21 tests). Originally added 2026-04 in commit `1bcc6d1`.
