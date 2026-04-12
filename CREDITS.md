# Credits — Curated Foundation

Per Kairos's *"curate the best, don't reinvent"* principle, we openly stand on the shoulders of the open-source trading ecosystem. This file lists every primitive we adopt, with license attribution.

If we ship code that adapts a pattern from one of these projects, the corresponding source file carries an attribution comment pointing here.

## Direct dependencies (declared in `pyproject.toml`)

| Project | Version | License | What we use it for |
|---------|---------|---------|--------------------|
| [ccxt](https://github.com/ccxt/ccxt) | >=4.0.0 | MIT | Exchange transport for 200+ venues — REST + auth signing for non-Binance |
| [websockets](https://github.com/python-websockets/websockets) | >=14.0 | BSD-3 | WebSocket transport |
| [pydantic](https://github.com/pydantic/pydantic) | >=2.0.0 | MIT | Configuration validation |
| [httpx](https://github.com/encode/httpx) | >=0.27.0 | BSD-3 | HTTP client |

## Optional dependencies

| Project | Version | License | What we use it for |
|---------|---------|---------|--------------------|
| [pandas](https://github.com/pandas-dev/pandas) | >=2.0.0 | BSD-3 | Bar/tick data, backtesting |
| [pyarrow](https://github.com/apache/arrow) | >=15.0.0 | Apache-2.0 | Parquet data catalog |
| [matplotlib](https://github.com/matplotlib/matplotlib) | >=3.8.0 | PSF-based | Equity curves in examples |

## Patterns adapted (no code vendored)

These are projects whose *patterns* and *design* informed Kairos's implementation. We did NOT copy code; we studied, then wrote our own. Where applicable, source files reference these inspirations.

| Project | License | What we adopted |
|---------|---------|-----------------|
| [hummingbot](https://github.com/hummingbot/hummingbot) | MIT | WebSocket reconnect-with-exponential-backoff pattern; rate-limiter design |
| [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) | LGPL-3.0 | Order state machine design, MessageBus concept (study only — clean-room reimplementation; no code copied) |
| [Jesse](https://github.com/jesse-ai/jesse) | MIT | Strategy class lifecycle (`on_bar`, `on_event`) ergonomics |
| [Freqtrade](https://github.com/freqtrade/freqtrade) | GPL-3.0 | Strategy structure conventions (study only — clean-room) |
| [vectorbt](https://github.com/polakowo/vectorbt) | Apache-2.0 | Backtest tick-replay loop design |
| [pandas-ta](https://github.com/twopirllc/pandas-ta) | MIT | Indicator math reference (verify our implementations against this library) |
| [ta-lib](https://github.com/TA-Lib/ta-lib-python) | BSD | Indicator parity reference |

## License compatibility

Kairos v0.1.x and v0.2.x are MIT-licensed.

- **MIT/BSD/Apache-2** dependencies and pattern sources: fully compatible
- **LGPL-3 (NautilusTrader)**: we do NOT vendor any LGPL code. We study the design and write our own clean-room implementation. This is the standard practice for clean-room reverse engineering and avoids LGPL contagion to our codebase.
- **GPL-3 (Freqtrade)**: same approach — study only, no code reuse.

## Verifying the curation principle

If you find Kairos source code that matches a pattern from one of these projects, you should also find an attribution comment near the implementation. Example:

```python
# Reconnect-with-backoff pattern adapted from hummingbot v1.25
# (https://github.com/hummingbot/hummingbot/blob/master/.../ws_assistant.py)
# MIT licensed. See CREDITS.md.
async def _reconnect_with_backoff(self) -> None:
    ...
```

If you find a pattern without attribution, please [open an issue](https://github.com/Vekkris76/kairos/issues) — we want this transparent.

## Anti-credits (what is original to Kairos)

The following is original Kairos work, not adopted from any external source:

- The `parity` module (fill matching with verdict)
- The vision and roadmap of the adaptive layer (§1-10 differentiators)
- The IngestionActor concept (no known prior art for "framework that crawls competitors and auto-improves itself")
- The `kairos.runtime.LiveEngine` orchestration shape (informed by NT but designed independently to support our adaptive hooks)

## Updating this file

When adopting a new primitive or studying a new project, add a row here in the same PR. CI does not yet enforce this, but reviewers will.
