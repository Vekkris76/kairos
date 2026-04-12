# autopilot-engine — DEPRECATED

This package has been **renamed to [`kairos-engine`](https://pypi.org/project/kairos-engine/)**.

## What you should do

```bash
pip uninstall autopilot-engine
pip install kairos-engine
```

In your code, replace:

```python
# Old
from autopilot import Engine, Strategy

# New
from kairos import Engine, Strategy
```

## What this package still does

`autopilot-engine==0.1.99` is a **deprecation alias**: it depends on `kairos-engine` and re-exports the public API. Existing imports will keep working but emit a `DeprecationWarning` on import.

This alias will stop being maintained on **2026-10-12** (6 months after the rename). After that date, no new releases of `autopilot-engine` will be published — please migrate before then.

## Why the rename?

We refocused the project on its differentiators (an adaptive trading engine with a meta-improvement layer) and gave it a commercial name: **Kairos** (Greek καιρός — the opportune moment). See [https://github.com/Vekkris76/kairos](https://github.com/Vekkris76/kairos) for the full vision and roadmap.

## Earlier history

`autopilot-engine` was published at v0.1.0 in March 2026 with indicators, paper trading, Binance Spot adapter, order manager, risk validator, backtest engine, strategy marketplace, analytics, and a parity module. All of that lives on in `kairos-engine` 0.2.0a0 and beyond.

## License

MIT (same as before).
