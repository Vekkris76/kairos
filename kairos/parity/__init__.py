"""Parity tooling — compare fills from two engines (or two runs of the same
engine) to detect divergence. Used for:

- Validating a new engine version vs a baseline
- Comparing backtest outputs across strategies
- Gating a production cutover from one engine to another

This module is pure data/logic — no I/O, no DB. Feed it two lists of
`FillRecord` and get back a `MatchReport`.
"""

from __future__ import annotations

from kairos.parity.matcher import (
    QUANTITY_TOLERANCE_PCT,
    PRICE_TOLERANCE_PCT,
    DEFAULT_TIME_TOLERANCE_SECONDS,
    FillMatch,
    FillRecord,
    MatchReport,
    Verdict,
    match_fills,
)

__all__ = [
    "DEFAULT_TIME_TOLERANCE_SECONDS",
    "FillMatch",
    "FillRecord",
    "MatchReport",
    "PRICE_TOLERANCE_PCT",
    "QUANTITY_TOLERANCE_PCT",
    "Verdict",
    "match_fills",
]
